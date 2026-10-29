# -*- coding: utf-8 -*-
"""响应侧 U+200B 清洗的单元测试：_scrub_zwsp / _SSEScrubber / _collect_stream。"""
import asyncio
import json
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import converter as cv


def _sse(*events: str, trailing_newline: bool = True) -> bytes:
    s = "".join(e + "\n" for e in events)
    if not trailing_newline:
        s = s.rstrip("\n")
    return s.encode("utf-8")


def test_scrub_basics():
    assert cv._scrub_zwsp("d\u200bsh") == "dsh"
    assert cv._scrub_zwsp("普通文本") == "普通文本"
    assert cv._scrub_strings_deep({"a": "x\u200by", "b": ["m\u200bn", {"c": "k\u200bl"}]}) == {"a": "xy", "b": ["mn", {"c": "kl"}]}
    assert cv._scrub_strings_deep({"n": 1, "ok": True}) == {"n": 1, "ok": True}
    print("PASS scrub_basics")


def test_scrubber_stream_end_to_end():
    # 构造完整的 OpenAI 风格 SSE：content 增量、tool_calls 增量、usage、[DONE]
    ev1 = {"id": "c1", "choices": [{"index": 0, "delta": {"content": "前文 d\u200bsh 中段"}}]}
    ev2 = {"id": "c1", "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "function": {"name": "run_cmd", "arguments": "{\"command\":\"npm i d"}},
    ]}}]}
    ev3 = {"id": "c1", "choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": "\u200bsh-pkg\"}"}},
    ]}}]}
    ev4 = {"id": "c1", "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 99}}
    raw = "".join("data: " + json.dumps(e, ensure_ascii=False) + "\n\n" for e in (ev1, ev2, ev3, ev4))
    raw += "data: [DONE]\n\n"
    data = raw.encode("utf-8")

    stats = {"finish": None, "usage": None, "tools": []}

    def stats_cb(store):
        def cb(obj):
            for ch in obj.get("choices") or []:
                if ch.get("finish_reason"):
                    store["finish"] = ch["finish_reason"]
                for tc in (ch.get("delta") or {}).get("tool_calls") or []:
                    nm = (tc.get("function") or {}).get("name")
                    if nm:
                        store["tools"].append(nm)
            if obj.get("usage"):
                store["usage"] = obj["usage"]
        return cb

    sc = cv._SSEScrubber(on_json=stats_cb(stats))

    # 按刁钻切分点逐段喂：把字节流切成 1 字节半逐段喂入，覆盖跨 chunk 的 JSON/ZWSP
    out = bytearray()
    for i in range(len(data)):
        out += sc.feed(bytes(data[i:i+1]))
    out += sc.flush()
    text = out.decode("utf-8")

    assert "\u200b" not in text, "输出流里不允许残留 U+200B"
    assert "data: [DONE]\n" in text, "DONE 保留"
    # 重新解析：content 干净、tool_call arguments 拼接后干净
    contents, args = "", ""
    for line in text.split("\n"):
        if not line.startswith("data: ") or "[DONE]" in line:
            continue
        obj = json.loads(line[6:])
        for ch in obj.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                contents += d["content"]
            for tc in d.get("tool_calls") or []:
                args += tc.get("function", {}).get("arguments") or ""
    assert "dsh 中段" in contents, contents
    assert json.loads(args)["command"] == "npm i dsh-pkg", args
    assert stats["finish"] == "tool_calls" and stats["usage"]["total_tokens"] == 99
    assert stats["tools"] == ["run_cmd"]
    print("PASS scrubber_stream_end_to_end")


def test_scrubber_non_data_lines_and_malformed():
    raw = b"event: ping\ndata: {bad json\n\ndata: {\"choices\":[{\"delta\":{\"content\":\"a\xe2\x80\x8bb\"}}]}\n\ndata: [DONE]\n\n"
    sc = cv._SSEScrubber()
    out = (sc.feed(raw) + sc.flush()).decode("utf-8")
    assert out.startswith("event: ping\n"), "非 data 行透传"
    assert "data: {bad json\n" in out, "结构异常的 data 行原样透传"
    assert "\u200b" not in out
    assert out.endswith("data: [DONE]\n\n"), out
    print("PASS scrubber_non_data_lines_and_malformed")


def test_collect_stream_scrubs():
    import json as _json
    lines = [
        'data: ' + _json.dumps({"choices": [{"delta": {"content": "在 d\u200bsh 目录运行"}}]}, ensure_ascii=False),
        'data: ' + _json.dumps({"choices": [{"delta": {"reasoning_content": "想一下 d\u200bsh"}}]}, ensure_ascii=False),
        'data: ' + _json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "id": "c9", "function": {"name": "wri\u200bte", "arguments": "{\"path\":\"d"}},
        ]}}]}, ensure_ascii=False),
        'data: ' + _json.dumps({"choices": [{"delta": {"tool_calls": [
            {"index": 0, "function": {"arguments": "\u200bsh.txt\"}"}},
        ]}}]}, ensure_ascii=False),
        'data: ' + _json.dumps({"choices": [{"delta": {}, "finish_reason": "tool_calls"}], "usage": {"total_tokens": 7}}, ensure_ascii=False),
    ]

    class FakeResp:
        async def aiter_lines(self):
            for l in lines:
                yield l

    result = asyncio.run(cv._collect_stream(FakeResp()))
    msg = result["choices"][0]["message"]
    assert msg["content"] == "在 dsh 目录运行", msg["content"]
    assert msg["reasoning_content"] == "想一下 dsh"
    tc = msg["tool_calls"][0]
    assert tc["function"]["name"] == "write"
    assert json.loads(tc["function"]["arguments"])["path"] == "dsh.txt"
    assert result["usage"]["total_tokens"] == 7
    assert result["choices"][0]["finish_reason"] == "tool_calls"
    print("PASS collect_stream_scrubs")


def test_flush_without_trailing_newline():
    # 最后一个 data 行没有换行结尾也能输出
    raw = b'data: {"choices":[{"delta":{"content":"tail\xe2\x80\x8bZ"}}]}'
    sc = cv._SSEScrubber()
    out_b = sc.feed(raw)
    out_f = sc.flush()
    text = (out_b + out_f).decode("utf-8")
    obj = json.loads(text[len("data: "):])
    assert obj["choices"][0]["delta"]["content"] == "tailZ"
    print("PASS flush_without_trailing_newline")


if __name__ == "__main__":
    test_scrub_basics()
    test_scrubber_stream_end_to_end()
    test_scrubber_non_data_lines_and_malformed()
    test_collect_stream_scrubs()
    test_flush_without_trailing_newline()
    print("ALL PASS")
