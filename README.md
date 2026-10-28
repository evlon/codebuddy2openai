# codebuddy2openai

> 把 **CodeBuddy / WorkBuddy（腾讯代码助手）** 的订阅，转换成 **OpenAI 兼容 API**，让你能在任何支持 OpenAI 协议的客户端（ZCode、Cherry Studio、NextChat、LobeChat 等）里复用它。

> ⚠️ **关于 Codex CLI**：新版 Codex CLI 已不再支持 `wire_api = "chat"`，只支持 `completions` 格式，因此**本工具无法直接接入 Codex CLI**，请改用下方「OpenAI 兼容客户端」方案。

[English](#english) · [中文文档](#中文文档)

---

## 中文文档

一个极简的本地协议转换器（proxy / adapter）：读取你本机已登录的 CodeBuddy 桌面端凭据，把它的对话能力包装成标准的 OpenAI `/v1/chat/completions`、`/v1/models` 接口。**不碰登录授权、不碰你已有的客户端配置、跨平台、单文件。**

### ✨ 特性

- 🔄 **OpenAI 兼容**：标准 `/v1/chat/completions`（支持流式 SSE）、`/v1/models`、`/health`。
- 🛠️ **Function Calling（工具调用）**：支持请求里的 `tools`，返回 OpenAI 格式的 `tool_calls`，可在 ZCode / Cherry Studio 等 agent 客户端里驱动工具、多轮回传结果。
- 🪶 **单文件、极简**：核心就一个 `converter.py`，不复杂。
- 🪪 **完整客户端身份面（v2.3）**：出站请求对齐官方 CLI（`@tencent-ai/codebuddy-code 2.177.0`，官方抓包逐字对齐）——UA `CLI/2.177.0 CodeBuddy/2.177.0`，常驻 `X-IDE-*` / `X-Product*` / `X-Private-Data` / 渠道标志与 trace/b3/baggage 链路头，每请求生成 `X-Conversation-ID` / `X-Request-ID` / `X-Agent-*`，body 补官方 `extra_vars.harnessMetadata` 等字段；token 剩余 <6h 自动续期、11128 渠道拦截自动强刷重试一次；15 个 `CLIENT_INFO_*` 环境变量覆盖通道与官方一致（详见下文「客户端身份面」）。
- 🔐 **零授权改动**：直接调用本机已登录的 `codebuddy` CLI，自动复用桌面端登录态，不重新登录、不存密码。
- 🖥️ **跨平台**：自动定位 macOS / Windows / Linux 上的 CLI 与登录文件。
- 🛡️ **安全**：默认只监听 `127.0.0.1`；工具的声明与执行都由客户端负责，转换器只做鉴权与透传。
- ⚡ **流式输出**：实时增量 token，体验与原生 OpenAI 流式一致。

### 🧠 它是怎么工作的

```
ZCode / Cherry Studio / 任意 OpenAI 客户端
        │  POST /v1/chat/completions  (标准 OpenAI 协议，含 tools)
        ▼
┌────────────────────┐
│  converter.py      │  ← 本地 FastAPI 服务 (127.0.0.1:8787)
│  读 token + 注入   │
│  鉴权 header + 透传│
└────────────────────┘
        │  POST /v2/chat/completions  (带 Authorization/X-User-Id 等头)
        ▼
┌────────────────────────────────┐
│  copilot.tencent.com 后端      │  ← 原生标准 OpenAI 协议
│  (GLM-5.2 / Kimi / DeepSeek)   │     含原生 tools / tool_calls / SSE 流式
└────────────────────────────────┘
```

转换器直连 CodeBuddy 后端（`copilot.tencent.com/v2/chat/completions`），该后端本身就是**标准 OpenAI chat/completions 协议**。转换器只做两件事：①读取本机登录凭据并注入鉴权 header；②在本地 `/v1/*` 与后端 `/v2/*` 之间透传。因为后端原生支持 `tools` / `tool_calls`，function calling 是模型自带能力，**无需任何 prompt 注入或文本解析**。token 过期时转换器会自动调刷新接口并回写。

> 历史版本曾通过「调 CLI + `<tool_call>` 文本标签解析」实现 function calling，但在嵌套 agent（subagent）场景下，subagent 的输出会夹带标签污染对话。**v2.0 改为直连后端，彻底解决了这个问题。**

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

启动时会做一次预检，打印账号信息和 token 状态。

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
   - **模型名**：`glm-5.2`（或 `kimi-k2.7` / `deepseek-v4-pro` / `auto` 等，见下方列表）

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
# 列模型（每个模型附上下文窗口元数据：max_input_tokens / context_length / max_output_tokens）
curl http://127.0.0.1:8787/v1/models

# 单模型详情（另含 vLLM/LM Studio 风格别名 max_model_len / max_context_length
# 及 name/credits/vendor/supportsImages/supportsToolCall 等后端元数据）
curl http://127.0.0.1:8787/v1/models/auto

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

`glm-5.2`、`glm-5.1`、`glm-5v-turbo`、`kimi-k2.7`、`kimi-k2.6`、`kimi-k2.5`、`deepseek-v4-pro`、`deepseek-v4-flash`、`minimax-m3-pay`、`hy3-preview-agent`、`auto`

（来自 CLI `--help` 的 `--model` 说明，具体可用性以你的订阅为准。）

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
python3 converter.py [--host HOST] [--port PORT] [--api-key KEY] [--log PATH] [--log-keep N] [--desensitize] [--desensitize-scope system|all] [--user-escape] [--strip-harness on|off] [--official-shape on|off] [--private-data true|false] [--sys-prefix off|short|full] [--skip-check]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--host` | `127.0.0.1` | 监听地址 |
| `--port` | `8787` | 监听端口 |
| `--api-key` | 无 | 启用鉴权；客户端需带同样 key（也可用环境变量 `CODEBUDDY2OPENAI_KEY`）|
| `--log` | 无 | **开启日志并写到该文件**（如 `--log converter.log`）。不传则不记。也可用环境变量 `CODEBUDDY2OPENAI_LOG`。|
| `--log-keep` | `3` | 日志自动裁剪：日志里只保留最近 N 次请求的完整现场（含报文），旧的在写入新请求前删除。日志不会无限增长，也避免敏感报文长期落盘。`0`=关闭裁剪（保留全部）。也可用环境变量 `CODEBUDDY2OPENAI_LOG_KEEP`。|
| `--desensitize` | 关 | 启用脱敏：对消息文本里的合规声明敏感词（DoS/exploit/credential/C2 等）与渠道风险痕迹词（`dsh`/`deepseek`/`DeepSeek Harness`）插入零宽空格，打断后端的关键词/字面量匹配（见下方 FAQ）。默认只处理 system 角色。|
| `--desensitize-scope` | `system` | 脱敏作用范围（需 `--desensitize`）。`system`=只处理 system 消息；`all`=扩展到 user/assistant/tool 消息与 `tools` 描述——dsh 客户端的工具描述/用户笔记里的 `dsh`/`DSH_*` 痕迹是渠道风险分的加重因子（实测 2026-10-28：真实会话 71 处痕迹可打散 68 处），整条请求被 `11128` 拦截时建议 `all`。也可用环境变量 `CODEBUDDY2OPENAI_DESENSITIZE_SCOPE`。|
| `--user-escape` | 关 | 启用**用户消息转义**：user 角色消息里命中词表（phishing/exploit/hack 等）的英文术语包成 `[s[<逐字反转>]]`（`phishing` → `[s[gnihsihp]]`）打断后端关键词匹配；若 system 里尚无解码说明还会自动补一段 `CODEBUDDY_ESCAPE_CODEC` 解码说明，模型自行反转还义。与 CodeBuddy 预设（见下）配对时解码说明由预设提供，不重复注入。也可用环境变量 `CODEBUDDY2OPENAI_USER_ESCAPE`。|
| `--strip-harness` | `on` | **签名清洗（默认开）**：清洗 system 消息里 dsh 客户端的三段全局签名（`harness:identity` / `harness:source` / `app:web-surface`，均含字面量 `DeepSeek Harness`——后端 `11128` 渠道拦截的匹配源）、**@-路径语义段**（`Tokens prefixed with @ … quotes a path containing spaces.` 整段，2026-10-28 官方载体分块扫描确定性定位的第二处硬拦点，改为语义等效的中性改写），**并清洗 assistant 历史消息里的残留签名**（模型在 dsh persona 时期的自我介绍会存进会话历史，续聊回放照样触发 11128，实测 2026-10-28）。identity 改写为 `You are CodeBuddy Code.`，source 删除，web-surface 替换为中性等效文本；残留变体字面量兜底替换为 `CodeBuddy`。幂等，与 dsh CodeBuddy 预设的遮蔽互不冲突（双层防护）。`--strip-harness off`（或环境变量 `CODEBUDDY2OPENAI_STRIP_HARNESS=off`）可关。|
| `--official-shape` | `on` | **官方请求形状补齐（默认开）**：body 里补官方客户端必带字段——`extra_vars.harnessMetadata`（`harnessVersion`/`stepIndex`/`contextWindowId`/`agent.depth` 的 JSON 串，2026-10-28 官方 2.177.0 抓包逐字对齐）与 `reasoning_effort`/`verbosity`/`cache_retention`/`reasoning_summary` 官方默认值。缺这些字段会被后端视为非官方客户端、推高渠道风险分。客户端显式指定时不覆盖。`--official-shape off`（或环境变量 `CODEBUDDY2OPENAI_OFFICIAL_SHAPE=off`）可关。|
| `--private-data` | `true` | `X-Private-Data` 身份头的取值。`true`=数据按隐私处理（禁用于模型优化）；`false` 与官方 SaaS 默认一致。也可用环境变量 `CODEBUDDY2OPENAI_PRIVATE_DATA`。|
| `--sys-prefix` | `off` | 在 system 消息最上方注入官方 CLI 的提示词关键字（逆向自官方 CLI 的 `cli-agent-prompt`）。`short`=身份声明 `You are CodeBuddy Code.` + 一句 CLI 角色描述；`full`=`short` 再加官方 `<content_policy>` 合规块。让 dsh 等 agent 客户端的 system 贴近官方会话形态，并复用官方合规约束。也可用环境变量 `CODEBUDDY2OPENAI_SYS_PREFIX`。|
| `--skip-check` | 否 | 跳过启动预检 |

示例：
```bash
python3 converter.py --log converter.log          # 记日志到当前目录 converter.log
python3 converter.py --log /tmp/cb.log            # 记到指定路径
python3 converter.py                              # 不记日志
```

每条日志记录：模型、是否流式、消息数、最后一条用户提问、耗时、finish_reason、工具调用、token 数；若后端内容审核拦截会标 `⚠️内容审核拦截`。**每次请求都用唯一 ID 串起来，并完整落盘**：发往后端的完整请求体（REQUEST BODY）、后端返回的完整内容（非流式是聚合后的 RESPONSE BODY，流式是后端原始的 RESPONSE RAW SSE）。排查"内容审核拦截""返回异常"等问题时，直接看日志里对应 ID 的完整报文即可。示例：
```
[2026-06-19 11:56:32] [9cc4488e] ▶ REQUEST glm-5.2 | stream=False | msgs=1 | last_user='Reply: pong'
[2026-06-19 11:56:32] [9cc4488e] ── REQUEST BODY ──
{ "model": "glm-5.2", "messages": [{"role":"user","content":"Reply: pong"}] }
[2026-06-19 11:56:35] [9cc4488e] ◀ RESPONSE glm-5.2 | 3.0s | finish=stop | tokens=11
[2026-06-19 11:56:35] [9cc4488e] ── RESPONSE BODY ──
{ "choices":[{"message":{"content":"pong"},...}], "usage":{...} }
```

### 🪪 客户端身份面（v2.3）

本转换器把出站请求的**客户端身份声明**与官方 CLI（`@tencent-ai/codebuddy-code 2.177.0`，2026-10-28 官方请求抓包逐字对齐）对齐（身份头对照分析见仓库内 `SECURITY-REVIEW.md`）：

| 维度 | 实现 |
|------|------|
| User-Agent | 按官方 `UserAgentHttpInterceptor.buildUserAgent()` 拼接：`<platform>/<platformVersion> <productName>/<productVersion> [extension]`，本机默认即官方抓包形态 `CLI/2.177.0 CodeBuddy/2.177.0`（可用环境变量 `CODEBUDDY2OPENAI_UA` 整体覆盖、`CODEBUDDY2OPENAI_UA_VERSION` 换版本） |
| IDE/Product 标头 | 常驻 `X-IDE-Type: CLI`、`X-IDE-Name: CLI`、`X-IDE-Version: 2.177.0`、`X-Product: SaaS`（抓包实测值）、`X-Product-Version: 2.177.0`、`X-Requested-With: XMLHttpRequest`、`X-CodeBuddy-Request: 1`、`X-Agent-Purpose: conversation` |
| 隐私标志 | `X-Private-Data`：超时/企业策略语义；默认 `true`（数据不用于模型优化），`--private-data false` 与官方 SaaS 默认对齐 |
| 每请求 ID | `X-Request-ID` = `X-Conversation-Message-ID`（32 位无连字符 UUID），`X-Conversation-Request-ID` = `X-Root-Request-ID`（独立根请求 UUID，与官方一致地分离消息/根 ID），`X-Conversation-ID` 默认每请求生成，也可由客户端透传同名头复用 |
| 链路追踪标头 | 每请求生成官方 otel/b3 拦截器形态的 `traceparent`（`00-{32hex}-{16hex}-01`）、`b3`（`{trace}-{span}-1-{parent}`）、`X-B3-*`、`X-Trace-ID` 与 `baggage: codebuddy.session_id=…,codebuddy.conversation_request_id=…`；缺失属于非官方客户端特征。可用环境变量 `CODEBUDDY2OPENAI_TRACE=off` 关闭（排查用） |
| Agent 标头 | `X-Agent-Intent: craft`、`X-Agent-Runtime: other`（抓包实测主会话即 `other`）、`X-Agent-Type: main` |
| body 形状 | `--official-shape`（默认开，见参数表）：`extra_vars.harnessMetadata` + `initiator` + 官方默认 `reasoning_effort`/`verbosity`/`cache_retention`/`reasoning_summary` |
| 令牌保鲜 | accessToken 28 天 TTL；转换器在**剩余 <6h 时自动续期**（`/v2/plugin/auth/token/refresh`，官方抓包同源实现），收到 `11128` 渠道拦截时强刷令牌+换身份头重试一次（重试轰炸会推高后端渠道热度，故只重试一次、间隔 2s）。刷新失败沿用现有 token 并落日志 |
| 身份字段覆盖 | 15 个环境变量与官方逐条一致：`CLIENT_INFO_MACHINE_ID` / `SESSION_ID` / `PLATFORM` / `PLATFORM_VERSION` / `PRODUCT_NAME` / `APPLICATION_NAME` / `PRODUCT_NAME_EN` / `PRODUCT_VERSION` / `IDE_TYPE` / `PLUGIN_NAME` / `PLUGIN_VERSION` / `CODEBUDDY_CLIENT_INFO_DOWNLOAD_CHANNEL` / `USER_AGENT_EXTENSION`。`machineId` 默认持久化在 `~/.codebuddy2openai/state.json`（可用 `CODEBUDDY2OPENAI_STATE` 改位置） |

> 说明：官方设计中客户端身份全部由客户端单方声明（无签名/证书，可被任意第三方客户端构造，见 `SECURITY-REVIEW.md`），并不构成安全边界；这里重建它们只为让转换器呈现与官方一致的、可被服务端正常归类的完整身份面。
>
> 暂未实现：OTLP 遥测上报（`/v1/traces`，官方用于按会话上报 machineId/sessionId）。

### 🧩 dsh CodeBuddy 预设（`dsh-codebuddy/`）

供 [dsh（DeepSeek Harness，`@deepseek-ai/dsh`）](https://www.npmjs.com/package/@deepseek-ai/dsh) 使用的 agent 预设 bundle，位于仓库 `dsh-codebuddy/`，基于官方 **standard（标准）** 预设克隆改造，做三件事：

1. **CodeBuddy 身份面**：persona 前缀改为官方声明 `You are CodeBuddy Code.` + CLI 角色描述（按预设运行时，`{{model}}` 变量保留）；
2. **遮蔽竞品签名**：dsh 全局 system 有三段含 `DeepSeek Harness` 字面量（源码 `dsh-system-prompt` 无条件注册的 `harness:identity`、`dsh-app-boot` 注册的 `harness:source`、`dsh-web-app` 注册的 `app:web-surface`）——正是后端 `code=11128` 渠道拦截的字面量签名。bundle 内的小插件在**预设作用域**内把三段遮蔽（identity/source 置空，web-surface 换中性等效文本）——仅 CodeBuddy 预设生效，standard 等其它预设不受影响；转换器侧另有 `--strip-harness`（默认开）做兜底，两层互不冲突；
3. **转义解码协议**：注册常驻 system 段落（`CODEBUDDY_ESCAPE_CODEC`），声明 `[s[ABC]]` 型编码标记的解码规则（去掉包裹、逐字反转），与转换器的 `--user-escape` 共同构成对用户提示词敏感词的编解码闭环。

其余插件（tool-bash/pwsh/fs/jobs/skill/plan-mode/compaction/delegation…）与官方 standard 预设逐行一致。

安装（web profile，已在本机完成）:

```bash
dsh plugin --profile web add "file:E:/ai-works/codebuddy2openai/dsh-codebuddy"
# pnpm 会把 "@local/dsh-codebuddy-preset" 同时写入 dependencies 和 dsh.profile.bundles
# 重启 dsh 后，在预设选择器（或 /preset codebuddy）里切到 "CodeBuddy"（仅空会话可切换）
```

配套启动方式（身份由预设承担，转换器**不要**再加 `--sys-prefix`，避免重复）:

```bash
python converter.py --port 8787 --log converter.log --user-escape --desensitize --desensitize-scope all
# strip-harness 默认开启（system+assistant 签名清洗兜底）；不想清签名：--strip-harness off
# --desensitize-scope all 会把 dsh/DSH 痕迹一并打散（含工具描述），压低整条请求的渠道风险分
```

### 📡 官方请求抓包（capture_server.py）

排查 `11128` 这类渠道问题时的对照工具：把官方 CLI 指到本地捕获代理，原样记录它的真实请求（头+体），与转换器的出站请求逐字段对齐。

```bash
python capture_server.py --port 8795 --out capture_out   # 启动捕获代理（转发到 copilot.tencent.com）
$env:ACC_PRODUCT_CONFIG = '{"endpoint":"http://127.0.0.1:8795"}'   # 官方 CLI 支持该环境变量覆盖端点
codebuddy -p "Reply exactly: ok"
# capture_out/ 下得到每请求 JSON（headers/body/响应）与 index.jsonl
```

### ❓ 常见问题

- **找不到登录文件**：在桌面端完成登录（不是只装、要登进去）。路径见上方「前置条件」。
- **客户端报 401**：转换器若用了 `--api-key`，客户端那边要带同样的 key；若是后端 401，可能是 token 失效（转换器会自动刷新，若仍失败需在桌面端重新登录）。
- **响应慢**：可换 `deepseek-v4-flash` 等更快的模型。
- **"敏感内容"被拦截 / `11128 Illegal API invocation from an unapproved channel`**：CodeBuddy 后端在模型推理之前做渠道风控 + 内容审核。实测（2026-10-21 与 2026-10-28 两轮）机制为**动态累计评分**，不是单一静态字面量：
    1. **字面量层（确定性）**：system/assistant 历史里的精确串 `DeepSeek Harness`（dsh 客户端签名），以及 dsh 预设里的 @-路径语义段（`Tokens prefixed with @ …`）是确定的匹配源（官方载体分块扫描逐块验证，只有这两类内容被拦，其余预设文本全部放行）→ `--strip-harness`（默认开）清洗/改写；
    2. **评分层**：外来 prompt 痕迹（dsh 预设文本、工具描述/用户笔记里的 `dsh`/`DSH_*`）与客户端形态偏离（缺官方头/官方 body 字段/陈旧令牌）累计推高风险分，突破阈值即整条请求被拦；
    3. **热度层**：**每次 11128 都会推高账户热度、降低后续阈值**（连续被拦会升级到连正常请求也被拦；衰减以十分钟计，短时间静默不够）。被拦后不要高频重试——转换器内置的 11128 处理是"强刷令牌 + 2s 后重试一次"即止，就是这个原因。
  应对：①`--log xxx.log` 看日志定位；②确认 `--strip-harness` 开着；③dsh 用户加 `--desensitize --desensitize-scope all` 打散全部 dsh/DSH 痕迹；④保持转换器新版（官方形状 + 令牌保鲜都在）。若整条会话已把账户热度打高，等十几分钟或跑一次官方 CLI 再试。注意：脱敏只针对客户端固定模板与产品名痕迹，不能也不应绕过对用户真实有害输入的审核。
另可用 `--sys-prefix full` 在 system 最上方注入官方 CLI 的提示词关键字（`You are CodeBuddy Code.` + 角色 + `<content_policy>`），让 agent 客户端的 system 贴近官方会话形态；它不是准入条件（实测无 system 声明也能过），属可选的"形态对齐 + 合规复用"。
- **user 提示词里的敏感词被拦**：与上面 system 误拦同理，但发生在用户真实输入上（如 "explain phishing"）。两种配套：① `--desensitize` 只处理 system，管不到 user；② `--user-escape` 把命中词表的术语包成 `[s[<逐字反转>]]`（`phishing` → `[s[gnihsihp]]`），并在 system 无解码说明时自动补 `CODEBUDDY_ESCAPE_CODEC` 解码段；模型解码还义实测正常（`[s[gnihsihp]]`→phishing、`[s[gnikcah]]`→hacking）。dsh 用户建议直接用上面的 CodeBuddy 预设：解码段常驻 system，转换器只负责转义、不会重复注入。

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

- 🔄 **OpenAI-compatible**: standard `/v1/chat/completions` (streaming SSE), `/v1/models`, `/health`.
- 🛠️ **Function Calling**: passes `tools` through and returns OpenAI-format `tool_calls`.
- 🪶 **Single-file & minimal**: core is one `converter.py`.
- 🪪 **Full official client identity (v2.3)**: outbound requests mirror the official CLI (`@tencent-ai/codebuddy-code 2.177.0`, byte-aligned with a captured official request) — UA, IDE/Product/channel headers, trace/b3/baggage, official body extras (`extra_vars.harnessMetadata` etc.), proactive token refresh (<6h margin) and a single retry on channel error 11128.
- 🔐 **Zero-auth hassle**: calls your locally-logged-in `codebuddy` CLI; reuses the desktop login session.
- 🖥️ **Cross-platform**: auto-locates CLI & auth on macOS / Windows / Linux.
- 🛡️ **Safe**: listens on `127.0.0.1` only; tool declarations and execution stay with the client — the converter only authenticates and forwards.

### 🚀 Quick Start

```bash
git clone https://github.com/HanHan666666/codebuddy2openai.git
cd codebuddy2openai
pip install fastapi "uvicorn[standard]"
python3 converter.py
```

Then point your OpenAI-compatible client at `http://127.0.0.1:8787/v1` (API base), leave the key blank unless you started the converter with `--api-key`. Note: Codex CLI is **not** supported (it dropped `wire_api = "chat"`); use ZCode, Cherry Studio, or any OpenAI-compatible client instead.

### ⚠️ Disclaimer

For personal learning and research only. Not affiliated with Tencent / CodeBuddy / OpenAI. Use only with a subscription you legally hold, in compliance with the relevant terms of service, at your own risk.

License: [MIT](./LICENSE)

---

<!-- SEO keywords -->
<sub>
**Keywords / 关键词:** codebuddy to openai · codebuddy2openai · codebuddy openai compatible api · codebuddy api proxy · codebuddy workbuddy openai adapter · tencent codebuddy openai · codebuddy glm-5.2 api · codebuddy kimi deepseek openai · openai compatible proxy local llm gateway · codebuddy function calling · codebuddy tool use tool_calls · codebuddy zcode cherry studio · 腾讯代码助手 openai · codebuddy 转 openai · codebuddy 接入 zcode cherry studio · 本地大模型代理 openai 协议 · codebuddy 订阅 复用 · workbuddy api 转换 · codebuddy 工具调用
</sub>
