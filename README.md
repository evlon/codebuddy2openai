# codebuddy2openai

> 把 **CodeBuddy / WorkBuddy（腾讯代码助手）** 的订阅，转换成 **OpenAI 兼容 API**，让你能在任何支持 OpenAI 协议的客户端（ZCode、Cherry Studio、NextChat、LobeChat 等）里复用它。

> ⚠️ **关于 Codex CLI**：新版 Codex CLI 已不再支持 `wire_api = "chat"`，只支持 `completions` 格式，因此**本工具无法直接接入 Codex CLI**，请改用下方「OpenAI 兼容客户端」方案。

[English](#english) · [中文文档](#中文文档)

---

## 中文文档

一个极简的本地协议转换器（proxy / adapter）：读取你本机已登录的 CodeBuddy 桌面端凭据，把它的对话能力包装成标准的 OpenAI `/v1/chat/completions`、`/v1/models` 接口。**不碰登录授权、不碰你已有的客户端配置、跨平台、单文件。**

### ✨ 特性

- 🔄 **OpenAI 兼容**：标准 `/v1/chat/completions`（支持流式 SSE）、`/v1/models`、`/v1/models/{model}`、`/health`。
- 🧩 **动态模型列表**：`/v1/models` 实时调用官方 CLI 同款的 `/v3/config` 接口拉取你账号的可用模型（官方 `/model` 选择器同款列表），带 TTL 缓存、失败自动兜底，服务端上新模型无需更新本工具。
- 📏 **上下文窗口元数据**：`/v1/models` 每项附 `max_input_tokens` / `context_length` / `max_output_tokens`（详情端点再附 vLLM / LM Studio 风格别名与后端原始元数据），客户端可据此做压缩/截断决策、避免上下文溢出。
- 🛡️ **官方 CLI 请求指纹**：出站请求头模拟官方客户端（UA / X-Product / X-Request-ID / X-IDE / X-Agent / X-Trace / X-Conversation 族），降低被后端画像为"第三方转换器"的概率（见下方「降低风控识别」）。
- 🛠️ **Function Calling（工具调用）**：支持请求里的 `tools`，返回 OpenAI 格式的 `tool_calls`，可在 ZCode / Cherry Studio 等 agent 客户端里驱动工具、多轮回传结果。
- 🪶 **单文件、极简**：核心就一个 `converter.py`，不复杂。
- 🔐 **零授权改动**：自动复用桌面端登录态，不重新登录、不存密码。
- 🖥️ **跨平台**：自动定位 macOS / Windows / Linux 上的登录文件。
- ⚡ **流式输出**：实时增量 token，体验与原生 OpenAI 流式一致。

### 🧠 它是怎么工作的

```
ZCode / Cherry Studio / 任意 OpenAI 客户端
        │  POST /v1/chat/completions  (标准 OpenAI 协议，含 tools)      GET /v1/models
        ▼                                                              ▼
┌────────────────────┐  ① 注入官方 CLI 形态请求头 + 路径透传  ┌─────────────────────────────────┐
│  converter.py      │ ────────────────────────────────────▶│  copilot.tencent.com 后端       │
│  读 token + 注入   │   POST /v2/chat/completions          │  /v2/chat/completions (原生     │
│  鉴权 header + 透传│   GET  /v3/config (动态模型+元数据)   │   OpenAI 协议, tools/流式)      │
└────────────────────┘                                      │   /v3/config (模型目录)         │
                                                            └─────────────────────────────────┘
```

转换器直连 CodeBuddy 后端（`copilot.tencent.com/v2/chat/completions`），该后端本身就是**标准 OpenAI chat/completions 协议**。转换器只做两件事：①读取本机登录凭据并注入请求头；②在本地 `/v1/*` 与后端 `/v2/*` 之间透传。因为后端原生支持 `tools` / `tool_calls`，function calling 是模型自带能力，**无需任何 prompt 注入或文本解析**。token 过期时转换器会自动调刷新接口并回写。

**模型列表与上下文元数据都是动态的**：`/v1/models` 调用官方 CLI 同款的 `GET /v3/config`（逆向自 `@tencent-ai/codebuddy-code`，该接口对 UA 有硬校验，须 `CLI/<x> CodeBuddy/<y>` 形态才放行），取响应里 `agents` 中 `name="cli"` 的 `models` 列表——这正是官方 CLI `/model` 选择器展示的、你账号实际可用的模型。结果带 TTL 缓存（`--models-ttl` 控制，默认 600 秒），拉取失败时依次回退到「上次成功结果 → 内置兜底快照」。每项还附上该模型的上下文窗口大小（`max_input_tokens` 等，"auto" 档位取 `default` 条目的保守值），**客户端 agent 可以据此决定何时压缩会话、避免上下文溢出**。

> 历史版本曾通过「调 CLI + `<tool>` 文本标签解析」实现 function calling，但在嵌套 agent（subagent）场景下，subagent 的输出会夹带标签污染对话。**v2.0 改为直连后端，彻底解决了这个问题。**

### 📦 前置条件

1. 已安装并**登录** CodeBuddy / WorkBuddy 桌面端（[腾讯云 CodeBuddy 官网](https://www.codebuddy.ai/)）。转换器会自动在这些位置找登录态：
   - **macOS**：`~/Library/Application Support/CodeBuddyExtension/Data/Public/auth/*.info`
   - **Windows**：`%LOCALAPPDATA%\CodeBuddyExtension\Data\Public\auth\*.info`
   - **Linux**：`~/.local/share/CodeBuddyExtension\Data\Public\auth\*.info`
2. **Python 3.8+**（无需 Node.js，不再依赖 CLI）。
3. 安装依赖（一次性）：
   ```bash
   pip install fastapi "uvicorn[standard]" httpx
   ```

### 🚀 快速开始

```bash
# 1. 克隆
git clone https://github.com/HanHan666666/codebuddy2openai.git
cd codebuddy2openai

# 2. 装依赖
pip install fastapi "uvicorn[standard]" httpx

# 3. 启动（确保 CodeBuddy 桌面端已登录）
python3 converter.py
# 看到「✅ 监听 http://127.0.0.1:8787」即成功
```

启动时会做一次预检：打印账号信息、token 状态，并**实时拉一次模型列表**（顺便验证后端连通性）。

### 🛠️ Function Calling（工具调用）

后端原生支持标准 OpenAI function calling。客户端（如 ZCode / Cherry Studio）在请求里带 `tools`，模型原生返回 `tool_calls`（`finish_reason:"tool_calls"`），客户端执行工具后把 `role:"tool"` 的结果回传即可——和直连 OpenAI 完全一致。流式、非流式、多轮工具调用都支持。

### 🔌 接入客户端

⚠️ **关于 Codex CLI（重要）**：新版本 Codex CLI 已**移除** `wire_api = "chat"` 的支持，目前只认 `completions` 格式，因此**本转换器无法直接接入 Codex CLI**。仓库里的 `codex-codebuddy.example.toml` 仅作历史/参考保留，实测在当前 Codex 上跑不通，请不要照抄。

✅ **可用方式 —— 任何标准 OpenAI 兼容客户端**（走 `/v1/chat/completions`）。常见选择：

- **ZCode**（OpenAI 兼容 Agent）
- **Cherry Studio**
- **NextChat / LobeChat / Open WebUI**
- 任何支持自定义 `base_url` 的 OpenAI SDK 客户端

通用接入步骤（以这类客户端为例）：

1. 保持转换器运行：`python3 converter.py`
2. 在客户端的「自定义模型 / OpenAI 兼容」设置里：
   - **API Base / 接口地址**：`http://127.0.0.1:8787/v1`
   - **API Key**：留空（转换器默认不校验）；若启动时用了 `--api-key`，则填同一个
   - **模型名**：从 `GET /v1/models` 里选（动态返回你账号当前可用的模型；`auto` 为默认档位）

示例配置（如果你用的客户端读 toml / 自定义 provider 片段）：

```toml
[model_providers.codebuddy]
name = "CodeBuddy (via local converter)"
base_url = "http://127.0.0.1:8787/v1"
env_key = "CODEBUDDY2OPENAI_KEY"
# 注意：本接口是 OpenAI chat 协议（/v1/chat/completions）。
# Codex CLI 因不再支持该 wire_api 而无法使用，请用 ZCode / Cherry Studio 等 OpenAI 兼容客户端。
```

### 🧪 curl 验证

```bash
# 列模型（动态拉取 + 上下文窗口元数据；?refresh=1 强制刷新缓存）
curl http://127.0.0.1:8787/v1/models

# 单个模型详情（附 max_input_tokens / context_length / max_model_len / credits / reasoning 等）
curl http://127.0.0.1:8787/v1/models/glm-5.2

# 非流式
curl http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5.2","messages":[{"role":"user","content":"你好"}]}'

# 流式
curl -N http://127.0.0.1:8787/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5.2","stream":true,"messages":[{"role":"user","content":"数1到5"}]}'
```

### 🤖 可用模型

`GET /v1/models` **动态返回**你账号当前实际可用的模型（官方 CLI `/model` 选择器同款列表，来自后端 `/v3/config` 里 `agents["cli"].models`），服务端上新/下线模型会自动跟进，无需更新本工具。

截至 2026-06 的实测快照（个人版）：`auto`（默认档位）、`hy4-preview`、`hy3`、`hy3-x`、`step-5-preview`、`space-bunny`、`deepseek-v4.1-flash`、`glm-5.3`、`glm-5.3-flash`、`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`minimax-m3`、`minimax-m2.7`、`kimi-k3-1`、`kimi-k2.8-preview`、`kimi-k2.7`、`kimi-k2.6`、`deepseek-v4-pro`、`mimo-v2.6-pro`。具体可用性以你的订阅为准（企业版可能额外下发企业定制模型）。

> 每个模型的上下文窗口大小见 `/v1/models/{model}`（例：`glm-5.3` 为 1M 输入 / 64k 输出；`auto` 档位取 `default` 条目的保守值 200k / 24k）。
>
> 离线兜底：`converter.py` 内置了一份上述快照（`DEFAULT_MODELS`），仅在后端不可达时救急；正常情况一律以动态拉取为准。

### 📁 项目结构

```
codebuddy2openai/
├── converter.py                     # 转换器主程序（单文件）
├── desensitize.py                   # 脱敏模块（可选，--desensitize 启用）
├── codex-codebuddy.example.toml     # provider 配置示例片段（仅供参考；Codex CLI 已不支持，见上方说明）
├── README.md
└── LICENSE
```

### 🔧 命令行参数

```
python3 converter.py [--host HOST] [--port PORT] [--api-key KEY] [--log PATH] [--desensitize] [--models-ttl SECONDS] [--skip-check]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8787` | 监听端口 |
| `--api-key` | 无 | 启用鉴权；客户端需带同样 key（也可用环境变量 `CODEBUDDY2OPENAI_KEY`）|
| `--log` | 无 | **开启日志并写到该文件**（如 `--log converter.log`）。不传则不记。也可用环境变量 `CODEBUDDY2OPENAI_LOG`。|
| `--desensitize` | 关 | 启用脱敏：对 system 消息里的合规声明敏感词（DoS/exploit/credential/C2 等）插入零宽空格，缓解被后端内容审核误拦（见下方 FAQ）。|
| `--models-ttl` | `600` | 动态模型列表缓存秒数，过期后下一次 `/v1/models` 自动重拉；`0` 表示每次都实时拉取。也可用环境变量 `CODEBUDDY2OPENAI_MODELS_TTL`。|
| `--skip-check` | 否 | 跳过启动预检 |

示例：
```bash
python3 converter.py --log converter.log          # 记日志到当前目录 converter.log
python3 converter.py --log /tmp/cb.log            # 记到指定路径
python3 converter.py                              # 不记日志
python3 converter.py --models-ttl 60              # 模型列表缓存 60 秒
```

每条日志记录：模型、是否流式、消息数、最后一条用户提问、耗时、finish_reason、工具调用、token 数；若后端内容审核拦截会标 `⚠️内容审核拦截`；动态模型拉取成功/失败也会记 `[models]` 行。**每次请求都用唯一 ID 串起来，并完整落盘**：发往后端的完整请求体（REQUEST BODY）、后端返回的完整内容（非流式是聚合后的 RESPONSE BODY，流式是后端原始的 RESPONSE RAW SSE）。排查"内容审核拦截""返回异常"等问题时，直接看日志里对应 ID 的完整报文即可。

### 🛡️ 降低风控识别（请求指纹模拟）

早期版本自报 `User-Agent: codebuddy2openai/2.0`，等于在请求头里写明"我是第三方转换器"——后端确实按 UA 做画像与校验（逆向官方客户端 + 实测证实）。现已改为**完整模拟官方 CLI（@tencent-ai/codebuddy-code 2.169.0）的请求指纹**：

| 出站请求 | 模拟的头 |
|---|---|
| 所有请求 | `User-Agent: CLI/unknown CodeBuddy/2.169.0`、`X-Product: SaaS`、`X-Request-ID`（每请求新生成 32 位 hex） |
| `POST /v2/chat/completions` | 基础头 + `X-IDE-Type: CLI`、`X-IDE-Name: CLI`、`X-IDE-Version: unknown`、`X-Agent-Intent: craft`、`X-Agent-Runtime: local-agent`、`X-Trace-ID`、`X-Conversation-ID` / `X-Conversation-Request-ID` / `X-Conversation-Message-ID`（每请求新 UUID） |
| `GET /v3/config` | 基础头（该接口对 UA 有硬校验：缺 `CodeBuddy/<版本>` 段直接 400 code=12403；缺 `CLI/<x>` 段则 200 但不下发模型数据） |

以上头集合与官方 CLI 的拦截器行为一一对应（UserAgentHttpInterceptor / ProductEndpointHttpInterceptor / CommonHeaderHttpInterceptor / ModelRequestProcessor）。实测后端会把 `X-Trace-ID` 回显为响应消息 id——这些头被真实消费，并非摆设。

**仍无法隐藏的行为特征**（知悉后再使用）：

- 使用模式：转换器转发的是客户端请求，无官方 CLI 的会话连续性（Conversation-ID 每请求新生成）、无上下文自动压缩、无子代理（subagent）行为特征；
- 网络环境：把登录态迁到服务器使用时，请求 IP 与桌面端登录 IP 不同，且没有 IDE 心跳等配套流量；
- 请求量与模型分布异常依然可能触发风控。

指纹模拟只能降低"按客户端特征识别"的概率，**不能保证不被识别**；请仅在自己拥有合法订阅的前提下使用，并遵守 CodeBuddy 服务条款。

### ❓ 常见问题

- **找不到登录文件**：在桌面端完成登录（不是只装、要登进去）。路径见上方「前置条件」。
- **客户端报 401**：转换器若用了 `--api-key`，客户端那边要带同样的 key；若是后端 401，可能是 token 失效（转换器会自动刷新，若仍失败需在桌面端重新登录）。
- **`/v1/models` 里的模型和官方不一致 / 模型列表更新了**：默认缓存 600 秒，用 `curl "http://127.0.0.1:8787/v1/models?refresh=1"` 强制刷新，或调小 `--models-ttl`。
- **上下文溢出（请求被后端拒绝）**：会话历史超过该模型的 `max_input_tokens` 时会被拒。查看 `/v1/models/{model}` 拿到上下文大小，让客户端（agent 类多带"自动压缩"开关）在接近上限时裁剪/压缩历史；`auto` 档位的容量取 `default` 条目的保守值（200k）。
- **响应慢**：可换 `deepseek-v4.1-flash` 等更快的模型。
- **`max_tokens` 超过模型上限会不会报错**：不会（实测后端服务端自行钳制，超限的 max_tokens 也能正常返回）；但注意推理型模型（如 hy4-preview）会把小 `max_tokens` 先消耗在 reasoning 上，导致 content 为空、`finish_reason=length`，请给足 `max_tokens`。
- **"敏感内容"被拦截**：这是 CodeBuddy 后端的**内容审核**（腾讯合规策略），在模型推理之前就拦了。常见触发原因是客户端注入的 system prompt 里含安全相关英文术语（如 DoS / exploit / credential / C2 等——这些往往是客户端**合规声明模板**里的"拒绝作恶"措辞，属误伤）。两种应对：①用 `--log xxx.log` 在日志里看 `⚠️内容审核拦截` 标记定位是哪条请求；②加 `--desensitize` 启用脱敏模块（`desensitize.py`），它对 system 消息里的这类合规词插入零宽空格（人/模型读无差别，但后端关键词匹配失效），可显著降低被误拦概率。注意：脱敏只针对客户端固定模板，不能也不应绕过对用户真实有害输入的审核。

### ⚠️ 免责声明

本项目为个人学习与研究用途，非官方产品，与腾讯 / CodeBuddy / OpenAI 无任何关联。使用本工具即表示你已阅读并同意：仅在你拥有合法订阅的前提下使用，遵守相关服务条款，自负风险。

### 📄 开源协议

[MIT](./LICENSE)

---

<a name="english"></a>
# English

A minimal local **protocol converter / proxy** that exposes your already-logged-in **CodeBuddy / WorkBuddy (Tencent coding assistant)** subscription as a standard **OpenAI-compatible API**, so you can use it from any OpenAI-protocol client (ZCode, Cherry Studio, NextChat, LobeChat, Open WebUI, etc.). **No auth changes, no edits to your client config, cross-platform, single file.**

> ⚠️ **Codex CLI note:** newer Codex CLI dropped `wire_api = "chat"` and only supports the `completions` format, so **this tool cannot be used with Codex CLI**. Use any OpenAI-compatible client instead.

### ✨ Features

- 🔄 **OpenAI-compatible**: standard `/v1/chat/completions` (streaming SSE), `/v1/models`, `/v1/models/{model}`, `/health`.
- 🧩 **Dynamic model list**: `/v1/models` calls the same `/v3/config` endpoint the official CLI uses to list the models actually available to your account, with TTL caching and offline fallback.
- 📏 **Context-window metadata**: every model entry carries `max_input_tokens` / `context_length` / `max_output_tokens` so clients can compact history before overflowing the context.
- 🛡️ **Official CLI request fingerprint**: outbound headers mimic the official client (UA / X-Product / X-Request-ID / X-IDE / X-Agent / X-Trace / X-Conversation families) to reduce third-party-proxy profiling.
- 🪶 **Single-file & minimal**: core is one `converter.py`.
- 🔐 **Zero-auth hassle**: reuses your locally-logged-in desktop session; tokens auto-refresh and are written back.
- 🖥️ **Cross-platform**: auto-locates the auth file on macOS / Windows / Linux.
- 🛡️ **Safe**: listens on `127.0.0.1` only.

### 🚀 Quick Start

```bash
git clone https://github.com/HanHan666666/codebuddy2openai.git
cd codebuddy2openai
pip install fastapi "uvicorn[standard]" httpx
python3 converter.py
```

Then point your OpenAI-compatible client at `http://127.0.0.1:8787/v1` (API base), leave the key blank unless you started the converter with `--api-key`. Model names come from `GET /v1/models` (fetched live from your account; `auto` is the default tier). Note: Codex CLI is **not** supported (it dropped `wire_api = "chat"`); use ZCode, Cherry Studio, or any OpenAI-compatible client instead.

### ⚠️ Disclaimer

For personal learning and research only. Not affiliated with Tencent / CodeBuddy / OpenAI. Use only with a subscription you legally hold, in compliance with the relevant terms of service, at your own risk.

License: [MIT](./LICENSE)

---

<!-- SEO keywords -->
<sub>
**Keywords / 关键词:** codebuddy to openai · codebuddy2openai · codebuddy openai compatible api · codebuddy api proxy · codebuddy workbuddy openai adapter · tencent codebuddy openai · codebuddy glm-5.2 api · codebuddy kimi deepseek openai · openai compatible proxy local llm gateway · codebuddy function calling · codebuddy tool use tool_calls · codebuddy zcode cherry studio · 腾讯代码助手 openai · codebuddy 转 openai · codebuddy 接入 zcode cherry studio · 本地大模型代理 openai 协议 · codebuddy 订阅 复用 · workbuddy api 转换 · codebuddy 工具调用 · codebuddy 动态模型列表 · codebuddy v3/config · codebuddy 上下文窗口 · codebuddy proxy rust
</sub>
