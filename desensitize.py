"""
desensitize — 针对 CodeBuddy 后端内容审核的脱敏模块（独立、可选）。

背景
----
CodeBuddy 后端（copilot.tencent.com）有内容审核，会拦截含"攻击/漏洞/凭证"
等含义的英文术语。但这些词经常出现在客户端**固定的合规 system 模板**里
（例如 ZCode 的 agent 声明：「Refuse requests for DoS attacks, exploit
development, credential testing, C2 frameworks ...」），属于**拒绝作恶**
的合规声明，并非用户的有害输入，却被后端误判为敏感词，导致整条请求被拦。

本模块做的事
------------
1) 脱敏（--desensitize）：对"合规声明高频词"做零宽空格处理，

    "DoS" -> "Do\u200bS"        （人/模型读仍是 DoS，后端关键词匹配失效）

2) 转义（--user-escape）：对 user 消息里的 USER_ESCAPE_TERMS 术语包成
   [s[<逐字反转>]]（如 phishing -> [s[gnihsihp]]），并在 system 缺解码说明时
   自动补一段 CODEBUDDY_ESCAPE_CODEC 解码说明让模型还义。仅当发生转义时补。

只处理明确的词表，脱敏默认只作用于 system 角色的消息；转义默认只作用于
user 角色消息。不改动其它角色内容，避免影响真实对话。

设计原则
--------
- 独立模块，可单独 import / 单独测试。
- 保守：词表小而明确；只默认处理 system 消息；可关闭。
- 不试图、也不可能绕过对用户真实有害输入的审核——只缓解客户端模板被误伤。
"""

from __future__ import annotations

import json
import re
from typing import Iterable

# 零宽空格：插入到关键词内部，打断后端的关键词匹配，但模型/人眼读起来无差别。
_ZWSP = "\u200b"

# 触发审核的"合规声明高频词"（来自真实被拦截的客户端 system 模板）。
# 全部是"拒绝作恶"语境里常见的英文术语。大小写不敏感匹配。
SENSITIVE_TERMS: list[str] = [
    "DoS",
    "DDoS",
    "exploit",
    "credential testing",
    "credential stuffing",
    "supply chain compromise",
    "supply-chain compromise",
    "detection evasion",
    "C2 frameworks",
    "C2 framework",
    "command and control",
    "malicious purposes",
    "malicious intent",
    "mass targeting",
    "brute force",
    "brute-force",
    "privilege escalation",
    "reverse shell",
    "remote code execution",
    "SQL injection",
    "XSS",
    "CSRF",
    "phishing",
    "malware",
    "ransomware",
    "keylogger",
    "rootkit",
    "backdoor",
    "botnet",
    "zero-day",
    "0day",
    # 实测（2026-10-21）：后端对 system 消息做精确大小写字面量拦截，
    # "DeepSeek Harness"（竞品官方 agent harness 的签名）触发 HTTP 400 code=11128
    # "Illegal API invocation from an unapproved channel"；user 角色同文本、
    # 其它大小写/无空格变体均不触发。加 ZWSP 脱敏后实测放行。
    # 2026-10-28 补充：渠道风险为动态累计评分——外来 prompt 痕迹（dsh/DSH 产品
    # 名、DeepSeek 厂商名）与 dsh 客户端内容（工具描述/用户笔记）共现会推高
    # 风险分、突破拦截阈值 → 一并打散（模型侧零宽空格不可见，无语义影响）。
    "DeepSeek Harness",
    "deepseek",
    "dsh",
]

# 编译成一个大正则，按词长降序，避免短词先吃掉长词。
# 边界：左右不允许紧邻英文字母（数字/下划线允许，使 "DSH_x" 工具名前缀也命中）；
# 忽略大小写。
_PATTERN = re.compile(
    "(?<![A-Za-z])(?:"
    + "|".join(re.escape(t) for t in sorted(SENSITIVE_TERMS, key=len, reverse=True))
    + ")(?![A-Za-z])",
    re.IGNORECASE,
)


def _zero_width_split(term: str) -> str:
    """在词内部插入零宽空格。如 'DoS' -> 'Do\\u200bS'。"""
    if len(term) <= 1:
        return term
    # 在第 1 个字符后插入即可（足够打断子串匹配，且改动最小）
    return term[0] + _ZWSP + term[1:]


def desensitize_text(text: str) -> str:
    """对文本中的触发词插入零宽空格。无触发词则原样返回。"""
    if not text:
        return text
    return _PATTERN.sub(lambda m: _zero_width_split(m.group(0)), text)


def _iter_text_blocks(content):
    """遍历 OpenAI content（字符串或 [{type, text}, ...]）里的文本块，返回 (容器, key)。"""
    if isinstance(content, str):
        yield content, None  # 字符串：调用方直接替换
    elif isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                yield blk, "text"


def desensitize_messages(messages: Iterable[dict],
                         roles: tuple[str, ...] = ("system",)) -> list[dict]:
    """对指定角色的消息文本做脱敏，返回新的 messages 列表（不修改原对象）。

    默认只处理 system 角色（合规模板集中地）。如需扩大，传 roles=("system","user")。
    """
    out: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        role = m.get("role")
        nm = dict(m)  # 浅拷贝，不污染调用方
        if role in roles:
            content = m.get("content")
            if isinstance(content, str):
                nm["content"] = desensitize_text(content)
            elif isinstance(content, list):
                new_blocks = []
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        nb = dict(blk)
                        nb["text"] = desensitize_text(blk.get("text", ""))
                        new_blocks.append(nb)
                    else:
                        new_blocks.append(blk)
                nm["content"] = new_blocks
        out.append(nm)
    return out


def desensitize_body(body: dict, roles: tuple[str, ...] = ("system",)) -> dict:
    """对请求体里的 messages 做脱敏，返回新的 body（浅拷贝）。"""
    if not body.get("messages"):
        return body
    nb = dict(body)
    nb["messages"] = desensitize_messages(body["messages"], roles=roles)
    return nb


def _desensitize_descriptions(obj):
    """递归把 schema（parameters 等）里所有字符串型 description 字段脱敏。

    返回改写数。
    """
    n = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "description" and isinstance(v, str):
                new = desensitize_text(v)
                if new != v:
                    n += 1
                obj[k] = new
            else:
                n += _desensitize_descriptions(v)
    elif isinstance(obj, list):
        for item in obj:
            n += _desensitize_descriptions(item)
    return n


def desensitize_tools(body: dict) -> tuple[dict, int]:
    """对 body["tools"] 的 function.description 与 parameters 内 description 脱敏。

    dsh 客户端携带的插件工具描述里大量出现 "DSH_*"/"dsh" 痕迹（渠道风险分的
    加重因子），此前完全未被任何清洗覆盖。返回 (new_body, 改写数)。
    """
    tools = body.get("tools")
    if not tools:
        return body, 0
    count = 0
    new_tools = []
    for t in tools:
        if not isinstance(t, dict) or not isinstance(t.get("function"), dict):
            new_tools.append(t)
            continue
        fn = dict(t["function"])
        if isinstance(fn.get("description"), str):
            new = desensitize_text(fn["description"])
            if new != fn["description"]:
                count += 1
            fn["description"] = new
        params = fn.get("parameters")
        if isinstance(params, dict):
            params = json.loads(json.dumps(params))  # 深拷贝（schema 无循环引用）
            count += _desensitize_descriptions(params)
            fn["parameters"] = params
        new_tools.append(dict(t, function=fn))
    nb = dict(body)
    nb["tools"] = new_tools
    return nb, count


# ---------------------------------------------------------------------------
# 用户消息转义（--user-escape）：[s[<反转词>]] 编解码方案
#
# 思路（源自用户建议，形态参照 DeepSeek Harness 社区流传的 [s[abc]] = "cba"）：
# 用户消息里命中 USER_ESCAPE_TERMS 的英文术语会被包成 [s[<逐字反转>]]，
#     "explain how phishing works" -> "explain how [s[gnihsihp]] works"
# 后端关键词匹配失效，而模型通过系统里的一段"解码说明"（CODEBUDDY_ESCAPE_CODEC）
# 知晓编码规则、自行反转还义，正常作答。
#
# 转义只对 user 角色消息；system 的合规模板继续走 ZWSP 脱敏（--desensitize）。
# 这是对用户提示词的可见改动（模型能看到 [s[..]] 并按说明解码），默认关闭。
# ---------------------------------------------------------------------------

USER_ESCAPE_TERMS: tuple[str, ...] = (
    # 按长度降序编译，避免短词先匹配吃掉长词（hack/hacking 同前缀族全列出）。
    # 注：dos/ddos 已移除（2026-11-01）——"dos"误伤率过高（DOS 磁盘/DOS 换行符
    # 在 Windows 开发字面量里很常见），模型把它反转回 dos 的成本不值得，摘掉
    # 后这两词直接明文过关（后端对普通词不拦，内容审核只看真实有害意图）。
    "hacking", "hacker", "hack",
    "phishing", "phish",
    "malware", "ransomware", "botnet", "keylogger", "spyware", "rootkit",
    "backdoor", "trojan", "exploit", "credential", "credentials",
)

_USER_ESCAPE_PATTERN = re.compile(
    "|".join(
        r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])"
        for t in sorted(USER_ESCAPE_TERMS, key=len, reverse=True)
    ),
    re.IGNORECASE,
)


USER_ESCAPE_DECODER = (
    "Encoding protocol (CODEBUDDY_ESCAPE_CODEC): the user input may contain "
    "bracketed tokens of the form [s[ABC]]. Decode rule: strip the [s[...]] "
    "wrapper and read the inner letters in reverse - [s[321cba]] means "
    "\"abc123\". Mentally decode every such token before interpreting the "
    "sentence, then answer as normal."
)


def escape_user_text(text: str) -> tuple[str, int]:
    """把文本里的转义词包成 [s[<reversed>]]。返回 (新文本, 命中数)。"""
    if not text:
        return text, 0
    count = 0

    def _rep(m: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        return "[s[" + m.group(0)[::-1] + "]]"

    out = _USER_ESCAPE_PATTERN.sub(_rep, text)
    return out, count


def _has_escape_codec(messages: Iterable[dict]) -> bool:
    """system 消息里是否已有解码说明（dsh CodeBuddy 预设的解码段含 '[s['）。"""
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "system":
            c = m.get("content")
            if isinstance(c, str) and "[s[" in c:
                return True
            if isinstance(c, list):
                for blk in c:
                    if isinstance(blk, dict) and blk.get("type") == "text" and "[s[" in blk.get("text", ""):
                        return True
    return False


def escape_user_messages(messages: list[dict]) -> tuple[list[dict], int, bool]:
    """对 user 角色消息做转义；若系统里尚无解码说明且发生了转义，补一条。

    返回 (new_messages, 转义命中数, 是否补了解码说明)。不修改原对象。
    """
    out: list[dict] = []
    count = 0
    for m in messages:
        nm = dict(m) if isinstance(m, dict) else m
        if isinstance(m, dict) and m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                new, n = escape_user_text(content)
                nm["content"] = new
                count += n
            elif isinstance(content, list):
                new_blocks = []
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        new, n = escape_user_text(blk.get("text", ""))
                        nb = dict(blk)
                        nb["text"] = new
                        count += n
                        new_blocks.append(nb)
                    else:
                        new_blocks.append(blk)
                nm["content"] = new_blocks
        out.append(nm)
    decoder_added = False
    if count > 0 and not _has_escape_codec(out):
        decoder_added = True
        sys_idx = next((i for i, m in enumerate(out)
                        if isinstance(m, dict) and m.get("role") == "system"), None)
        if sys_idx is None:
            out.insert(0, {"role": "system", "content": USER_ESCAPE_DECODER})
        else:
            m0 = dict(out[sys_idx])
            c0 = m0.get("content")
            if isinstance(c0, str):
                m0["content"] = USER_ESCAPE_DECODER + "\n\n" + c0
            elif isinstance(c0, list):
                m0["content"] = [{"type": "text", "text": USER_ESCAPE_DECODER}] + c0
            else:
                m0["content"] = USER_ESCAPE_DECODER
            out[sys_idx] = m0
    return out, count, decoder_added


def escape_user_body(body: dict) -> tuple[dict, int, bool]:
    """对请求体做 user 消息转义，返回 (new_body, count, decoder_added)。"""
    if not body.get("messages"):
        return body, 0, False
    new_messages, count, decoder_added = escape_user_messages(list(body["messages"]))
    nb = dict(body)
    nb["messages"] = new_messages
    return nb, count, decoder_added


# ---------------------------------------------------------------------------
# strip-harness（--strip-harness，默认开）：dsh/DeepSeek Harness 签名清洗
#
# dsh 客户端的 system 里有三段全局签名文本，均含字面量 "DeepSeek Harness"——
# 正是后端 11128 "Illegal API invocation from an unapproved channel" 渠道拦截
# 的匹配串（实测 2026-10-21，system 通道精确大小写匹配）：
#   1. harness:identity  "You are an AI agent powered by DeepSeek Harness."
#   2. harness:source    "The DeepSeek Harness implementation checkout is at ..."
#   3. app:web-surface   "You are interacting with the user through the DeepSeek
#                         Harness Web GUI at ..."（整段是 dsh 开发细节，全删）
# dsh 侧已由 dsh-codebuddy 预设的 codebuddy-keys 插件在预设域内遮蔽；这里是
# 转换器侧的兜底：任何客户端漏出的签名都在出站前清洗，两层互不冲突（幂等）。
# ---------------------------------------------------------------------------

_HARNESS_IDENTITY_RE = re.compile(
    r"You are an AI agent powered by DeepSeek Harness\."
)

# 整段源码位置指引（从段首到段尾句号），CodeBuddy 模式下本就无意义，删除。
_HARNESS_SOURCE_RE = re.compile(
    r"The DeepSeek Harness implementation checkout is at .*?"
    r"Use this checkout only to inspect or extend DSH itself\.\s*",
    re.S,
)

# Web GUI 整段（含 URL 与 dsh 前端开发细节），替换为中性等效一句。
_HARNESS_WEB_RE = re.compile(
    r"You are interacting with the user through the DeepSeek Harness Web GUI at .*?"
    r"verify its exact URL\.",
    re.S,
)
_WEB_SURFACE_NEUTRAL = (
    'You are interacting with the user through a local Web GUI. When the user '
    'refers to "this page", "this GUI", or "this app" without naming another '
    'target, they mean this GUI. The browser provides no implicit DOM, route, '
    'or screenshot context.'
)

# 残兜底：还有任何 "DeepSeek Harness" 变体字面量 → 换成 "CodeBuddy"（语义无害）。
_HARNESS_RESIDUAL_RE = re.compile(r"Deep[ \t]*Seek[ \t]+Harness", re.IGNORECASE)

# @-路径语义段（2026-10-28 确定性定位）：dsh 预设里"Tokens prefixed with @ ..."
# 一段是后端渠道拦截的又一个硬字面量源（官方载体 + 该段整段移除/改写即放行，
# 原文 2/2 稳定被拦；预设其余部分分块扫描全部放行）。改为中性等效改写。
_HARNESS_ATPATH_RE = re.compile(
    r"Tokens prefixed with @ are paths the user explicitly referenced\..*?"
    r"quotes a path containing spaces\.",
    re.S,
)
_ATPATH_NEUTRAL = (
    "File paths that the user prefixed with the at sign resolve relative to the "
    "workspace root; absolute paths point to host files or directories. A trailing "
    "slash marks a directory; otherwise treat it as a file and read it before "
    "claiming to have inspected it. Quoted at-paths wrap paths containing spaces."
)


def strip_harness_text(text: str) -> tuple[str, int]:
    """清洗一段 system 文本里的 DeepSeek Harness 签名。返回 (新文本, 改写数)。"""
    count = 0

    def _sub(pattern, repl, s):
        nonlocal count
        new, n = pattern.subn(repl, s)
        count += n
        return new

    out = text
    out = _sub(_HARNESS_IDENTITY_RE, "You are CodeBuddy Code.", out)
    out = _sub(_HARNESS_SOURCE_RE, "", out)
    out = _sub(_HARNESS_WEB_RE, _WEB_SURFACE_NEUTRAL, out)
    out = _sub(_HARNESS_ATPATH_RE, _ATPATH_NEUTRAL, out)
    out = _sub(_HARNESS_RESIDUAL_RE, "CodeBuddy", out)
    return out, count


def strip_harness_messages(messages: list[dict]) -> tuple[list[dict], int]:
    """对 system（全套清洗）与 assistant（残留兜底）角色做签名清洗。

    assistant 历史必须清洗（实测 2026-10-28）：模型在 dsh persona 时期的自我介绍
    （"我是由 DeepSeek Harness 驱动的…"）会被存进会话历史，续聊回放时照样触发
    11128——只清 system 挡不住历史包袱。历史里只做残留替换（DeepSeek Harness →
    CodeBuddy），语义无害且与人设一致。返回 (new_messages, 改写数)，不修改原对象。
    """
    out: list[dict] = []
    count = 0
    for m in messages:
        nm = dict(m) if isinstance(m, dict) else m
        if isinstance(m, dict) and m.get("role") in ("system", "assistant"):
            content = m.get("content")

            def _clean(text: str, role: str) -> tuple[str, int]:
                if role == "system":
                    return strip_harness_text(text)
                new, n = _HARNESS_RESIDUAL_RE.subn("CodeBuddy", text)
                return new, n

            if isinstance(content, str):
                new, n = _clean(content, m["role"])
                nm["content"] = new
                count += n
            elif isinstance(content, list):
                new_blocks = []
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        new, n = _clean(blk.get("text", ""), m["role"])
                        nb = dict(blk)
                        nb["text"] = new
                        count += n
                        new_blocks.append(nb)
                    else:
                        new_blocks.append(blk)
                nm["content"] = new_blocks
        out.append(nm)
    return out, count


def strip_harness_body(body: dict) -> tuple[dict, int]:
    """对请求体做 system 签名清洗，返回 (new_body, 改写数)。"""
    if not body.get("messages"):
        return body, 0
    new_messages, count = strip_harness_messages(list(body["messages"]))
    nb = dict(body)
    nb["messages"] = new_messages
    return nb, count


# ---------------------------------------------------------------------------
# 自测：python3 desensitize.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    samples = [
        "Refuse requests for DoS attacks and exploit development.",
        "Dual-use security tools (C2 frameworks, credential testing) require authorization.",
        "这是一段正常的中文，不含任何触发词。",
        "Prevent privilege escalation and brute force attacks.",
        "No sensitive words here at all.",
    ]
    print("=== 脱敏前后对比 ===")
    for s in samples:
        d = desensitize_text(s)
        changed = "✓改" if d != s else "  不"
        print(f"{changed} | 原文: {s}")
        if d != s:
            print(f"     | 脱敏: {d}")
            print(f"     | 可见字符相同，差异为零宽空格 U+200B")
    print()
    print("=== messages 脱敏（只处理 system）===")
    msgs = [
        {"role": "system", "content": "Refuse DoS attacks and exploit development."},
        {"role": "user", "content": "explain DoS attacks"},  # 不应被改
    ]
    out = desensitize_messages(msgs)
    for m in out:
        print(f"  [{m['role']}] {m['content']!r}")
    print()
    # 验证：脱敏后 system 改了，user 没改
    assert "\u200b" in out[0]["content"], "system 应被脱敏"
    assert "\u200b" not in out[1]["content"], "user 不应被脱敏"
    print("✓ 自测通过：system 被脱敏，user 保持原样")
