# -*- coding: utf-8 -*-
"""--user-escape 转义行为的单元测试（词表与边界规则）。"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from desensitize import escape_user_text, escape_user_body, USER_ESCAPE_TERMS


def test_still_wraps_security_review_terms():
    new, n = escape_user_text("explain how phishing works and what malware does")
    assert "[s[gnihsihp]]" in new, new
    assert "[s[erawlam]]" in new, new
    assert n >= 2, n
    print("PASS still_wraps_security_review_terms")


def test_dos_ddos_no_longer_wrapped():
    # 2026-11-01 词表摘除 dos/ddos：普通技术语境字面量不能被吃掉
    for literal in (
        "convert to dos line endings",
        "check MS-DOS format",
        "disk is FAT dos style",
        "run ddos protection setup",
    ):
        new, n = escape_user_text(literal)
        assert n == 0, (literal, new, n)
        assert "[s[" not in new, new
    assert "dos" not in USER_ESCAPE_TERMS and "ddos" not in USER_ESCAPE_TERMS
    print("PASS dos_ddos_no_longer_wrapped")


def test_boundaries_and_real_words():
    # 子串/前后字母相连不命中
    new, n = escape_user_text("phishing-similarity, dosage, phishy2, isothermal")
    # phishing 命中（词边界 - 相连），dosage/phishy2/isothermal 都不命中
    assert n == 1, n
    assert "[s[gnihsihp]]-similarity" in new, new
    assert "dosage" in new and "phishy2" in new, new
    print("PASS boundaries_and_real_words")


def test_credentials_hit():
    new, n = escape_user_text("rotate the AWS credentials for staging")
    assert "[s[slaitnederc]]" in new, new
    assert n == 1
    print("PASS credentials_hit")


def test_code_blocks_protected():
    # 围栏代码块内不转义（贴命令/路径/配置是工具调用字面量的主要来源）
    text = "先用这个命令：\n```powershell\nnpm i dsh-utils\ncurl http://x/payload.txt\n```\n然后解释 phishing 原理"
    new, n = escape_user_text(text)
    assert "```powershell" in new and "npm i dsh-utils" in new, new
    assert "[s[gnihsihp]]" in new, "围栏外的散文要正常转义"
    assert n == 1, n
    assert "[s[" not in text.split("```")[1], "围栏内不得出现转义"

    # 行内 code span 内不转义
    new2, n2 = escape_user_text("查看 `credentials.json`，聊聊 phishing")
    assert "`credentials.json`" in new2, new2
    assert "[s[gnihsihp]]" in new2 and n2 == 1

    # 未闭环的行内反引号：保护到行末
    new3, n3 = escape_user_text("open `exploit.py then fix")
    assert "exploit.py then fix" in new3, new3
    assert n3 == 0

    # 未闭合围栏保护到文末
    new4, n4 = escape_user_text("```json\n{\"tool\": \"keylogger-scan\"}")
    assert n4 == 0 and "{\"tool\": \"keylogger-scan\"}" in new4
    print("PASS code_blocks_protected")


def test_user_body_only_role_and_decoder():
    body = {
        "messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "how does phishing work"},
            {"role": "assistant", "content": "phishing is ..."},
            {"role": "tool", "content": "found 'phishing' in file ..."},
        ]
    }
    new_body, count, decoder_added = escape_user_body(body)
    msgs = new_body["messages"]
    assert count == 1
    assert "[s[gnihsihp]]" in msgs[1]["content"]
    assert "phishing" in msgs[2]["content"], "assistant 不得改写"
    assert "phishing" in msgs[3]["content"], "tool 结果不得改写"
    # 解码说明自动补进 system
    assert decoder_added is True
    assert "CODEBUDDY_ESCAPE_CODEC" in msgs[0]["content"]
    # 幂等：再次调用不再命中 [s[..]] 包裹后的词
    again, cnt2, dec2 = escape_user_body(dict(new_body))
    assert cnt2 == 0 and dec2 is False
    print("PASS user_body_only_role_and_decoder")


if __name__ == "__main__":
    test_still_wraps_security_review_terms()
    test_dos_ddos_no_longer_wrapped()
    test_boundaries_and_real_words()
    test_credentials_hit()
    test_code_blocks_protected()
    test_user_body_only_role_and_decoder()
    print("ALL PASS")
