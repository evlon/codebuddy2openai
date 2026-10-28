# -*- coding: utf-8 -*-
"""官方客户端捕获代理：官方 CodeBuddy CLI -> 本地捕获 -> 真实后端。

用途：把官方客户端的 endpoint 指到本代理（ACC_PRODUCT_CONFIG 覆盖），
原样转发到真实后端并完整落盘请求/响应，用于对比官方请求与转换器请求的差异
（system prompt 原文、头部、字段形状等"暗号"）。

用法：
  python capture_server.py --port 8795 --upstream https://copilot.tencent.com --out capture_out

客户端侧（PowerShell）：
  $env:ACC_PRODUCT_CONFIG = '{"endpoint":"http://127.0.0.1:8795"}'
  codebuddy   # 在任意测试目录跑一轮对话即可

落盘：capture_out/req_<序号>_<rid>.json 包含 method/path/headers/body 与
响应 status/headers/body（SSE 会完整拼接）；index.jsonl 是请求流水索引。
"""
import argparse
import gzip
import json
import sys
import time
import uuid
import zlib
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

HOP_HEADERS = {"host", "content-length", "connection", "keep-alive",
               "transfer-encoding", "upgrade", "proxy-connection"}

CFG = {"upstream": "https://copilot.tencent.com", "out": Path("capture_out"), "count": 0}

app = FastAPI()


def _save(index: int, rid: str, record: dict):
    path = CFG["out"] / f"req_{index:04d}_{rid}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    with open(CFG["out"] / "index.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%H:%M:%S"), "n": index, "rid": rid,
                            "method": record["method"], "path": record["path"],
                            "status": record.get("status"),
                            "req_bytes": len(record.get("body", "") or ""),
                            "res_bytes": record.get("res_bytes", 0)},
                           ensure_ascii=False) + "\n")


def _decode_body(data: bytes, headers: dict) -> str:
    """content-encoding 为 gzip/deflate/br 时解压后存储（转发仍用原始字节）。"""
    enc = (headers.get("content-encoding") or headers.get("Content-Encoding") or "").lower()
    try:
        if enc == "gzip" and data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        elif enc == "deflate":
            data = zlib.decompress(data)
        elif enc == "br":
            import brotli  # 可选依赖
            data = brotli.decompress(data)
    except Exception:
        pass  # 解压失败存原文
    return data.decode("utf-8", "replace")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy(path: str, request: Request):
    CFG["count"] += 1
    index, rid = CFG["count"], uuid.uuid4().hex[:8]
    body = await request.body()

    fwd_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in HOP_HEADERS}

    record = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": request.method,
        "path": "/" + path,
        "query": str(request.url.query),
        "headers": dict(request.headers),
        "body": _decode_body(body, request.headers),
    }

    url = CFG["upstream"].rstrip("/") + "/" + path
    if request.url.query:
        url += "?" + str(request.url.query)

    client = httpx.AsyncClient(timeout=httpx.Timeout(600, connect=30))
    try:
        req = client.build_request(request.method, url, headers=fwd_headers, content=body)
        resp = await client.send(req, stream=True)
    except Exception as e:  # 上游连不上也要留下现场
        record.update({"status": None, "error": str(e), "res_bytes": 0})
        _save(index, rid, record)
        return StreamingResponse(iter(["upstream error: " + str(e)]), status_code=502)

    record["status"] = resp.status_code
    record["response_headers"] = dict(resp.headers)

    async def tee():
        chunks = []
        try:
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()
            record["res_body"] = _decode_body(b"".join(chunks), resp.headers)
            record["res_bytes"] = len(record["res_body"])
            _save(index, rid, record)

    resp_headers = {k: v for k, v in resp.headers.items()
                    if k.lower() not in ("content-length", "transfer-encoding", "connection")}
    return StreamingResponse(tee(), status_code=resp.status_code, headers=resp_headers,
                             background=None)


def main():
    ap = argparse.ArgumentParser(description="官方 CodeBuddy 客户端捕获代理")
    ap.add_argument("--port", type=int, default=8795)
    ap.add_argument("--upstream", default="https://copilot.tencent.com")
    ap.add_argument("--out", default="capture_out")
    args = ap.parse_args()

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    CFG["upstream"] = args.upstream
    CFG["out"] = Path(args.out)
    CFG["out"].mkdir(parents=True, exist_ok=True)

    print(f"✅ 捕获代理 http://127.0.0.1:{args.port} -> {args.upstream}")
    print(f"   落盘目录 : {CFG['out'].resolve()}")
    print(f"   客户端注入: $env:ACC_PRODUCT_CONFIG = '{{\"endpoint\":\"http://127.0.0.1:{args.port}\"}}'")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
