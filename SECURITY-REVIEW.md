# 安全评审：CodeBuddy 客户端身份信任模型

| 项目 | 内容 |
|---|---|
| 评审对象 | `@tencent-ai/codebuddy-code@2.171.0`（npm 全局安装，本机 `C:\nvm4w\nodejs\node_modules\@tencent-ai\codebuddy-code`） |
| 对照实现 | 本仓库 `converter.py`（逆向锚点：官方 2.169.0） |
| 方法 | 纯静态分析（bundle 字符串/结构检索）；无主动探测、无伪造请求 |
| 日期 | 2026-10-21 |
| 结论摘要 | 客户端身份**全部由客户端单方声明**，无出站签名/证书/attestation；服务端将其用作准入输入时，任何第三方客户端均可构造 |

---

## 1. 结论（按置信度分级）

| # | 结论 | 置信度 | 依据 |
|---|---|---|---|
| C1 | 服务端**解析 User-Agent 并据此分支**，UA 是安全相关输入而非纯遥测 | 高 | 仓库内 `converter.py:61` 注释记录的两组对照结果（见 §3.1） |
| C2 | 客户端身份字段全部由客户端单方声明（`X-IDE-*` / `X-Product*` / UA），出站无签名、无客户端证书、无 attestation | 高 | §3.2 常量表、§3.3 UA 拼接、§3.5 HMAC 方向 |
| C3 | 身份可替换是**厂商设计意图**，不属实现缺陷 | 高 | §3.4 共 15 个 `CLIENT_INFO_*` 环境变量覆盖通道 |
| C4 | 除 UA 外，其余身份头是否参与准入判决 | 中（未验证） | 静态无法判定，需对照实验 |
| C5 | token 是否与设备/客户端强绑定（device-bound） | 未知（未分析） | 未评审 refresh 全链路 |

**综合结论**

> 在该产品中，「客户端身份」不构成安全边界，实质是遥测与业务分段标签。
> 任何建立在这些字段之上的访问控制（配额判定、版本准入、企业策略），均可被**单个 HTTP 请求**构造绕过。

**CWE**：CWE-290（Authentication Bypass by Spoofing）、CWE-345（Insufficient Verification of Data Authenticity）

---

## 2. 边界声明（报告完整性要求）

本报告只支持以下命题：**身份面是可伪造的**。

本报告**不**支持、也不应被引用为：**服务端确实基于这些字段做安全裁决并已被绕过**。

未经（或未记录）主动验证的事项，一律按「未验证」处理，不得在对外结论中推定「无风险」。

---

## 3. 证据链

### 3.1 服务端对 UA 的行为分支（转述的实测结果）

来源：本仓库 `converter.py:55-61` 注释（逆向自 2.169.0 并实测），**非本次复测**：

- UA 缺 `CodeBuddy/<version>` 段 → `HTTP 400`，`code=12403`，`"check ua, get coding copilot version error"`
- UA 缺 `CLI/<x>` 段 → `HTTP 200`，但响应不下发 `models` / `agents`（空配置）
- `CodeBuddy-Code/2.169.0` 这类命名不被识别

推断：服务端存在一个显式的 UA 解析与准入判断，且失败路径可区分（硬失败 vs 软降级）。这是**目前唯一一条服务端侧行为证据**，也是 C1 的唯一支撑。

### 3.2 身份头常量表（集中定义）

位置：`dist/codebuddy.js`（单文件 minified bundle）内一处连续赋值块：

```
TRACE_ID_HEADER="X-Trace-ID"                      REQUEST_ID_HEADER="X-Request-ID"
ROOT_REQUEST_ID_HEADER="X-Root-Request-ID"        PARENT_CONVERSATION_ID_HEADER="X-Parent-Conversation-ID"
AGENT_TYPE_HEADER="X-Agent-Type"                  AGENT_INTENT="X-Agent-Intent"
AGENT_RUNTIME="X-Agent-Runtime"                   AGENT_RUNTIMES=[local-agent, cloud-agent, agent-agent]
PRODUCT="X-Product"                               IDE_TYPE_HEADER="X-IDE-Type"
IDE_NAME_HEADER="X-IDE-Name"                      IDE_VERSION_HEADER="X-IDE-Version"
API_KEY_HEADER="X-API-Key"                        PRODUCT_VERSION_HEADER="X-Product-Version"
USER_ID_HEADER="X-User-Id"                        PRIVATE_DATA_HEADER="X-Private-Data"
DATA_TAG_HEADER="X-Data-Tag"                      MODEL_ID_HEADER="X-Model-ID"
```

特征：**全部为普通 HTTP 请求头**，无一个属于密码学凭据。

### 3.3 UA 由客户端本地拼接

`UserAgentHttpInterceptor.buildUserAgent()`（全局拦截器，作用于所有 RestOperations）：

```js
async buildUserAgent(existing = "") {
  const parts = existing ? [existing] : [];
  const ci = await this.clientInfoProvider.get() || {};
  const name = ci.applicationName || ci.productName;
  if (name)        parts.unshift(name + "/" + (ci.productVersion || "unknown"));
  if (ci.platform) parts.unshift(ci.platform + "/" + (ci.platformVersion || "unknown"));
  if (ci.userAgentExtension) parts.push(ci.userAgentExtension);
  return parts.join(" ");
}
```

形态：`<platform>/<platformVersion> <productName>/<productVersion> [<原UA>] [<extension>]`
另有 `X-Skip-User-Agent-Merge` 控制是否覆盖既有 UA。

要点：纯字符串拼接，输入全部来自 `ClientInfoProvider`，而该 provider 的输入可被环境变量整体替换（§3.4）。

### 3.4 身份可被环境变量整体覆盖

`ENV_CLIENT_INFO_KEYS`（共 15 项）：

```
machineId           CLIENT_INFO_MACHINE_ID              sessionId        CLIENT_INFO_SESSION_ID
platform            CLIENT_INFO_PLATFORM                 platformVersion  CLIENT_INFO_PLATFORM_VERSION
productName         CLIENT_INFO_PRODUCT_NAME             applicationName  CLIENT_INFO_APPLICATION_NAME
productNameEn       CLIENT_INFO_PRODUCT_NAME_EN          productVersion   CLIENT_INFO_PRODUCT_VERSION
ideType             CLIENT_INFO_IDE_TYPE                 pluginName       CLIENT_INFO_PLUGIN_NAME
pluginVersion       CLIENT_INFO_PLUGIN_VERSION           downloadChannel  CODEBUDDY_CLIENT_INFO_DOWNLOAD_CHANNEL
userAgentExtension  CLIENT_INFO_USER_AGENT_EXTENSION
```

判断依据：官方 IDE 插件正是通过该通道把自己声明为 `VSCode` / `CodeBuddy` / `WSL` 等。
**身份必须可覆盖**，因此**不可能**同时成为安全边界——这是设计层面的必然，不是疏漏。

### 3.5 出站请求无密码学绑定

- `hmac` / `verifyHmac()` / `timingSafeEqual` 仅出现在**入站** webhook 校验路径（校验 `x-signature` / `x-timestamp` / `x-nonce`），不出现在出站请求构造中
- 出站凭据仅 `Authorization: Bearer <accessToken>`
- 未发现请求体签名、客户端证书、mTLS、TPM/TEE attestation

### 3.6 反向侧证：内部头剥离名单

`isSkippableInternalHeader()` 显式剥离：
`X-User-Id` / `X-Enterprise-Id` / `X-Tenant-Id` / `X-Department-Info` / `X-Domain` / `User-Agent` / `X-Requested-With` / `x-stainless-*`

说明：厂商自身把这些视为「不应外流的身份信息」——恰恰确认它们是身份载体。

### 3.7 交互链路

| 环节 | 路径 | 备注 |
|---|---|---|
| 鉴权刷新 | `POST /v2{prefix}/auth/token/refresh` | 头 `X-Refresh-Token`、`X-Auth-Refresh-Source: plugin` |
| 模型调用 | `POST {endpoint}/chat/completions`、`/responses` | 内置 OpenAI SDK，SSE 流式 |
| 模型目录 | `GET /v3/config` | 返回 `models` 全量元数据 + `agents[name=cli].models` 可用列表 |
| 遥测 | `POST /v1/traces`（OTLP） | 每会话上报 machineId/sessionId/platform/node 版本 |
| 策略裁决 | `/v2/chat/decisions` | **语义未明确**，见 §5 |

部署端点差异（`product*.json`）：

| 配置文件 | deploymentType | endpoint |
|---|---|---|
| `product.json` | SaaS | `https://www.codebuddy.ai` |
| `product.internal.json` | — | `https://copilot.tencent.com` |
| `product.ioa.json` | — | `https://copilot.tencent.com` |

本仓库 `converter.py:51` 使用 `copilot.tencent.com`，即 internal/IOA 部署；`X-Product` 本应对应声明该值。

---

## 4. 与本仓库实现的偏差

| 维度 | 官方 2.171.0 | converter.py | 判定 |
|---|---|---|---|
| UA（对话） | 全局拦截器统一构造 | `codebuddy2openai/2.0`（:53） | 偏离：对话链路无官方形态 |
| UA（/v3/config） | 同上 | `CLI/unknown CodeBuddy/2.169.0`（:61） | 形态一致，版本落后 2 个 minor |
| `X-IDE-*` / `X-Product*` | 必带 | 无 | 缺失 |
| `X-Conversation-*` / `X-Request-ID` | 每请求生成 | 无 | 缺失 |
| `X-Private-Data` | 按企业版策略填 | 无 | 缺失 |
| `Authorization` / `X-User-Id` | 有 | 有（:160-173） | 一致 |
| `X-Auth-Refresh-Source: plugin` | 有 | 有（:132） | 一致 |
| refresh 路径 | `/v2{prefix}/auth/token/refresh` | `/v2/plugin/auth/token/refresh`（:133） | 一致（prefix=plugin） |
| 遥测 | 有 | 无 | 缺失 |

结论：偏差性质为**身份面覆盖不全**，而非协议不兼容。

---

## 5. 未验证项（后续可做）

1. **`/v2/chat/decisions` 的语义** —— 从命名看可能是服务端策略裁决入口，是唯一可能不依赖自报头的判定点，静态分析可判
2. **token 与设备/客户端绑定关系** —— 评审 `/v2/auth/token/refresh` 全链路可判
3. **身份头准入权重矩阵** —— 需对照实验（不同头组合 → 服务端行为差异）
4. **遥测缺失是否被区别对待** —— 需主动观测

---

## 6. 修复建议

**结论先行：不要试图「加强客户端身份校验」，该方向在架构上不成立（§3.4）。**

1. **不依赖客户端身份**
   配额、限流、企业策略全部落在账号/token 上；token 与设备指纹、会话强绑定（短期 refresh + 绑定校验）。

2. **要验就验不可伪造的东西**
   - 请求签名：body + 关键头做 HMAC，密钥置于 TEE / 系统钥匙串，服务端可验证
   - 或 mTLS 客户端证书
   - 或平台 attestation（Windows TPM / Apple DeviceCheck / Android Play Integrity）

3. **版本准入下推**
   服务端维护版本白名单，且不要用 UA 字符串做唯一年龄判断（UA 可任意拼接）。

4. **安全相关标志改由服务端推导**
   `X-Private-Data` 这类影响隐私策略的标志，不应由客户端声明。

5. **检测侧（纵深防御）**
   同一 token 的 UA/IDE 组合突变、遥测缺失、请求节奏与官方客户端分布偏离 —— 这些只能作为风险信号，不可作为准入依据。

---

## 附录：可复现性

- 所有代码引用均来自本机已安装的 npm 包，路径见文首
- bundle 为单文件 minified，可用 `grep -o` 按 §3 中的字面量检索复现
- §3.1 的两组服务端响应来自仓库内注释，复测需在授权范围内进行
