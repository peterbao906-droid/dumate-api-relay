# DuMate Relay

> 把 **百度搭子（DuMate）桌面版个人版**的积分额度，变成一套 **OpenAI / Anthropic 兼容 API**，
> 反代给任意 harness、agent、脚本或局域网内的其他机器使用。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4.svg)](#-前置条件重要)

---

## 这是什么

DuMate 桌面版在本地跑了一个 opencode 服务，登录个人账号后，所有对话都消耗你的**个人积分**。
这个项目把那套本地服务包装成标准 API，并加了一层带鉴权的反代，于是你可以：

- 用 `openai` 官方 SDK 直接调（`base_url` 改一下就行，零改造）
- 用 `anthropic` SDK 的 `/v1/messages` 协议调
- 让你自研的 harness / 其他机器上的 agent 共用这份额度
- 顺手查积分余额，做配额守卫

```
┌──────────────┐   relay token    ┌─────────────┐   api token   ┌──────────────┐        ┌────────────────┐
│ 你的 harness  │ ───────────────▶ │  relay.py   │ ────────────▶ │ points_api.py│ ─────▶ │  DuMate 桌面版  │
│ 脚本 / agent  │  OpenAI/Claude   │   :8000     │               │    :8765     │ 本机   │   积分在这扣    │
│ 局域网机器    │     兼容协议      │ 鉴权+注入token│               │  协议翻译层   │ 回环   │  必须保持运行   │
└──────────────┘                  └─────────────┘               └──────────────┘        └────────────────┘
```

三层完全解耦：只想本机脚本用，可以只跑 API 层；要对外/跨机，再叠加 relay 层。

---

## ⚠️ 前置条件（重要）

**这是逆向实现，依赖具体客户端内部结构，版本敏感。** 请先核对下表，缺一不可。

### 运行环境

| 项 | 要求 | 本项目实测通过的环境 |
|---|---|---|
| **操作系统** | **Windows 10 / 11（64 位）** | ✅ Windows 11 专业版 `10.0.22631` |
| **DuMate 桌面版** | **必须已安装、已登录、且运行中** | ✅ 客户端版本 **`1.0.92`** |
| **账号类型** | **个人版**（`DUMATE_LOGIN_MODE=personal`） | ✅ 个人版 |
| **Python** | **3.10 及以上** | ✅ Python `3.13.14` |
| **网络** | 能访问 `console.bce.baidu.com`（查积分用） | ✅ |
| **权限** | 需读取 DuMate **进程环境变量**，普通用户权限即可 | ✅ 无需管理员 |

> **macOS / Linux 不支持。** 读取 DuMate 进程环境变量的实现基于 Windows API
> （`NtQueryInformationProcess` + PEB + `ReadProcessMemory`），其他平台没有对应实现。
> DuMate 客户端本身也只有 Windows 版本。

### Python 依赖

```bash
python -m pip install -r scripts/requirements.txt
```

| 包 | 最低版本 | 实测版本 |
|---|---|---|
| `fastapi` | `>=0.104.0` | `0.163.1` |
| `uvicorn` | `>=0.24.0` | `0.54.0` |
| `requests` | `>=2.31.0` | `2.34.2` |
| `cryptography` | `>=41.0.0` | `50.0.2` |

### 版本兼容性说明

| 情况 | 结果 |
|---|---|
| DuMate `1.0.92` | ✅ 已验证可用 |
| DuMate `1.0.58` | ⚠️ 曾可运行，未做回归测试 |
| DuMate 其他版本 | ❓ 未验证。内部端口/key 发现机制变了就会失效，需等上游更新 |
| DuMate 客户端**未启动** | ❌ 必然失败，所有调用都会报「未检测到 DuMate 桌面版进程」 |

> DuMate 是自动升级的。**升级后如果突然全挂**，先跑 `python scripts/client.py --doctor` 定位，
> 大概率是内部协议变了。

---

## 快速开始

### 1. 装依赖

```bash
git clone https://github.com/<your-name>/dumate-api-relay.git
cd dumate-api-relay
python -m pip install -r scripts/requirements.txt
```

### 2. 确认 DuMate 在跑

先打开 DuMate 桌面版，登录，等它完全启动（约 30 秒），然后验证自动发现是否正常：

```bash
python -c "import sys; sys.path.insert(0,'scripts'); import dumate_client as d; print(d.discover_opencode_url())"
```

打印出 `http://127.0.0.1:<端口>` 就说明发现了本地服务。端口是**动态的**，不用手配。

### 3. 启动

```bash
# 先生成两个强口令
python -c "import secrets;print(secrets.token_urlsafe(24))"

# 再启动（两层一起起）
python start.py --api-token <口令A> --relay-token <口令B>
```

看到这两行就成功了：

```
  ✓ API 层就绪
  ✓ 反代层就绪
```

Windows 用户也可以直接双击 `start.bat`（**记得先改里面的两个 `CHANGE_ME`**）。
`Ctrl+C` 会同时停掉两层。

### 4. 自检

```bash
python scripts/client.py --doctor
```

三项全绿代表全链路通了。

---

## 怎么接进你的 harness

### 方式一：标准 OpenAI SDK（推荐，零改造）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",   # 跨机时换成 http://<Tailscale-IP>:8000/v1
    api_key="<你的 relay token>",
)

r = client.chat.completions.create(
    model="dumate-lite",                   # lite / turbo / ultra
    messages=[{"role": "user", "content": "你好"}],
)
print(r.choices[0].message.content)
```

流式也支持，`stream=True` 即可。

### 方式二：Anthropic SDK

```python
import anthropic

client = anthropic.Anthropic(
    base_url="http://127.0.0.1:8000",      # 注意：Anthropic SDK 自己会拼 /v1/messages
    api_key="<你的 relay token>",
)
msg = client.messages.create(
    model="dumate-lite",
    max_tokens=4096,
    messages=[{"role": "user", "content": "你好"}],
)
print(msg.content[0].text)
```

### 方式三：裸 HTTP / 任意语言

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <你的 relay token>" \
  -d '{"model":"dumate-lite","messages":[{"role":"user","content":"你好"}]}'
```

鉴权头三种都认：`X-Relay-Token` / `Authorization: Bearer` / `x-api-key`。

### 方式四：直接用自带客户端（零依赖）

```python
import sys; sys.path.insert(0, "scripts")
from client import dumate_chat, dumate_points

r = dumate_chat([{"role": "user", "content": "你好"}], model="dumate-lite")
print(r["content"])

print(dumate_points()["availablePoints"])   # 查积分
```

命令行也行：

```bash
python scripts/client.py "帮我写个正则"
python scripts/client.py --model dumate-turbo "分析这段代码"
python scripts/client.py --stream "长输出任务"
python scripts/client.py --points      # 查积分
python scripts/client.py --models      # 查模型档位
python scripts/client.py --doctor      # 全链路自检（排障第一步）
```

更多集成范例（含「包一层统一后端 + 配额守卫」的写法）见 [`examples/harness_example.py`](examples/harness_example.py)。

---

## 模型档位

| 模型名 | 上游档位 | 积分消耗 | 适用场景 |
|---|---|---|---|
| `dumate-lite` | `L0` | 最低 | 日常问答、改写、摘要 |
| `dumate-turbo` | `L1` | 中 | 复杂分析、代码生成 |
| `dumate-ultra` | `L2` | 最高 | 难题攻坚，**慎用** |
| `dumate-points` | — | 0 | 特殊：用它提问会返回真实积分余额 |

档位通过请求头 `X-Dumate-AutoModel-Level` 映射，无需额外配置。

---

## 跨机 / 外网访问

relay 默认监听 `0.0.0.0:8000`，同一局域网可直接用 `http://<内网IP>:8000/v1`。

**跨公网请用 Tailscale**（点对点加密，不暴露公网端口）：

```bash
tailscale up
tailscale ip -4     # 拿到 100.x.x.x 地址，填进 base_url
```

> ❌ **绝对不要**把 8000 端口在路由器上做公网端口映射。这等于把你的积分账号挂到公网上。

---

## 配置

不想每次传参数，可以写 `~/.dumate.json`（环境变量优先级更高）：

```json
{
  "base": "http://127.0.0.1:8000",
  "api_key": "你的relay-token",
  "model": "dumate-lite",
  "upstream": "http://127.0.0.1:8765",
  "api_token": "你的api-token",
  "relay_token": "你的relay-token",
  "relay_host": "0.0.0.0",
  "relay_port": 8000
}
```

- 客户端读 `base` / `api_key` / `model`
- relay 读 `upstream` / `api_token` / `relay_token` / `relay_host` / `relay_port`

### 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `DUMATE_BASE` | 客户端访问的服务地址 | `http://127.0.0.1:8000` |
| `DUMATE_API_KEY` | 客户端携带的 token | — |
| `DUMATE_MODEL` | 默认模型 | `dumate-lite` |
| `DUMATE_TIMEOUT` | 调用超时秒数 | `900` |
| `DUMATE_UPSTREAM` | relay 的上游地址 | `http://127.0.0.1:8765` |
| `DUMATE_API_TOKEN` | relay 注入的上游 token | — |
| `RELAY_TOKEN` | relay 对外鉴权 token | 空（**等于不鉴权**） |
| `RELAY_HOST` / `RELAY_PORT` | relay 监听地址/端口 | `0.0.0.0` / `8000` |

---

## 目录结构

```
dumate-api-relay/
├── start.py                    # 一键启动两层 + 启动自检（零依赖）
├── start.bat                   # Windows 双击入口（记得改 CHANGE_ME）
├── scripts/
│   ├── points_api.py           # OpenAI/Anthropic 兼容翻译层 :8765  ← 上游 MIT 代码
│   ├── dumate_client.py        # DuMate 本地服务发现与封装        ← 上游 MIT 代码
│   ├── relay.py                # 反代层：鉴权 + 注入 token + SSE 流式
│   ├── client.py               # 零依赖客户端（CLI + 可 import）
│   └── requirements.txt
├── references/
│   └── guide.md                # 完整架构说明与 7 类排障手册
├── examples/
│   └── harness_example.py      # 4 种 harness 接入范例
├── docs/
│   └── MAINTAINING.md          # 维护手册：拉 issue → 修 → 提交 → 关闭
├── .github/
│   └── ISSUE_TEMPLATE/         # issue 模板（强制填系统/客户端版本）
├── LICENSE
└── README.md
```

---

## 排障速查

| 现象 | 原因与处置 |
|---|---|
| `未检测到 DuMate 桌面版进程` | DuMate 没开或没启动完。打开等 30 秒 |
| `502 upstream unreachable` | `points_api.py` 没起。先只起 API 层排查 |
| `401 invalid api token` | relay 的 `DUMATE_API_TOKEN` 与 `points_api --token` 不一致 |
| `403 invalid relay token` | 调用方 token 与 relay 的 `RELAY_TOKEN` 不一致 |
| 调用一直不返回 | DuMate 在真干活。`ultra` 档可能跑几分钟，默认超时 900 秒 |
| 积分掉得很快 | 每次调用都是完整 agent 会话（带思考+工具），比纯文本 API 贵。日常用 `lite` |
| `DuMate 升级后全挂` | 内部协议变了。跑 `--doctor` 确认，等上游更新 |
| 流式输出被截断 | 中间有缓冲型代理。relay 用标准 chunked，确保中间层不缓冲 |

完整 7 类排障见 [`references/guide.md`](references/guide.md)。

---

## 反馈与贡献

- **遇到问题**：请用 [Bug 报告](https://github.com/peterbao906-droid/dumate-api-relay/issues/new/choose) 模板提交。
  模板会要求填 **操作系统版本**、**DuMate 客户端版本**、**Python 版本** 和 `--doctor` 自检输出——
  本项目是逆向实现，对客户端版本高度敏感，缺这些信息基本无法定位。
- **想加功能**：用 [功能建议](https://github.com/peterbao906-droid/dumate-api-relay/issues/new/choose) 模板。
- **提交代码**：先在 issue 里说明要改什么，再 fork 或开分支提 PR，commit message 里用 `Fixes #编号` 关联。
- **安全漏洞**：**不要开公开 issue**，请走 [Security Advisory](https://github.com/peterbao906-droid/dumate-api-relay/security/advisories/new)。

维护者操作手册（拉取 issue、分支策略、自动关闭关键词、标签体系、排障）见 **[`docs/MAINTAINING.md`](docs/MAINTAINING.md)**。

---

## ⚠️ 安全与合规（务必读完）

1. **一定要改默认口令。** 仓库里所有 `CHANGE_ME_*` 都是占位符。
   `RELAY_TOKEN` 为空等于不鉴权，同网段任何人都能刷爆你的积分。
   ```bash
   python -c "import secrets;print(secrets.token_urlsafe(24))"
   ```

2. **积分是你的个人资产。** 所有调用都扣你自己百度账号的积分，**没有任何配额隔离**。
   如果你把它共享给别人，请自己加额度监控（`dumate_points()` 做守卫，范例见 `examples/`）。

3. **不要把端口暴露到公网。** 用 Tailscale 组网。公网裸露 = 被扫描器刷爆积分。

4. **不要把 token 提交进 git。** `.gitignore` 已排除 `.dumate.json`、`*.pid`、`*.log`。
   如果你 fork 后改了配置文件路径，自己注意。

5. **合规风险自负。**
   把个人版积分逆向包装成 API，**违反百度相关服务条款**，存在**封号 / 清零积分**的风险。
   本项目仅用于个人技术研究与本地工具链整合，**请勿用于商业分发或对外提供服务**。
   需要稳定商用请走百度智能云官方 API。

6. **`usage` 恒为 0。** 上游拿不到真实 token 计数，OpenAI 响应里的 `prompt_tokens` 永远是 `0`。
   要做计费或上下文裁剪，得自己按字符估算。

7. **数据流向。** 仅本机回环 + 百度官方服务器（`console.bce.baidu.com`），**无任何第三方外发**。本项目不收集任何遥测。

---

## 致谢

`scripts/points_api.py` 与 `scripts/dumate_client.py` 来自开源项目 **dumate-api**（MIT License），
本项目未修改其核心逻辑，仅在其之上配套了 relay 层、客户端与启动器。
原始版权声明见 [`LICENSE`](LICENSE) 与 [`NOTICE`](NOTICE)。

---

## License

[MIT](LICENSE)

---

## 免责声明

本项目与百度公司无任何关联，未获其授权或认可。「百度」「DuMate」「百度搭子」为百度公司商标。
使用本项目产生的一切后果（包括但不限于账号封禁、积分损失）由使用者自行承担。
