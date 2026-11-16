# DuMate 额度反代 —— 完整部署与排障指南

## 一、架构

```
外部调用方 (harness / 脚本 / 外网 agent)
    ↓  Authorization: Bearer <relay token>   或   X-Relay-Token: <relay token>
[relay.py :8000]          鉴权、注入上游 token、SSE 流式转发
    ↓  Authorization: Bearer <api token>
[points_api.py :8765]     OpenAI / Anthropic 兼容翻译层，把请求转成 DuMate 会话
    ↓  127.0.0.1 本机、动态端口（从进程环境变量自动发现）
[DuMate 桌面版]           已登录的百度账号，积分在这里扣
```

三层各自独立：可以只跑 API 层（本机脚本用），也可以只套 relay（对外服务）。

## 二、文件说明

| 文件 | 来源 | 作用 |
|---|---|---|
| `scripts/points_api.py` | 上游项目（逻辑未改动） | OpenAI / Anthropic 兼容层 + 积分查询 |
| `scripts/dumate_client.py` | 上游项目（未改动） | DuMate 本地客户端封装，自动发现端口/密钥 |
| `scripts/relay.py` | 本项目 | 反代层：鉴权 + 注入 token + 流式转发 |
| `scripts/client.py` | 本项目 | 零依赖客户端，CLI + 可 import |
| `start.py` / `start.bat` | 本项目 | 一键启动两层 + 启动自检 |
| `examples/harness_example.py` | 本项目 | 4 种 harness 接入范例 |
| `LICENSE` / `NOTICE` | 本项目 + 上游 | MIT 许可证与来源声明 |

`points_api.py` 与 `dumate_client.py` 来自开源项目 dumate-api（MIT），本项目未改动其逻辑，
仅配套了 relay / client / 启动器。详细来源与版权声明见仓库根目录 `NOTICE`。

另有一处说明：`scripts/points_api.py` 第 36 行附近的注释由本项目改写。原注释记录了原作者本机的
代理端口号，对他人无参考价值且属于本机配置细节，故改为通用描述，逻辑无任何变更。

## 三、部署步骤

### 1. 装依赖

```bash
python -m pip install -r scripts/requirements.txt
```

### 2. 确认 DuMate 就绪

```bash
# 进程应该在跑
tasklist | grep -i dumate        # Windows
# 自动发现是否正常
python -c "import sys; sys.path.insert(0,r'scripts'); import dumate_client as d; print(d.discover_opencode_url())"
```

能打印出一个 `http://127.0.0.1:xxxxx` 就正常。

### 3. 启动

```bash
python start.py --api-token <强口令A> --relay-token <强口令B>
```

看到 `✓ API 层就绪` / `✓ 反代层就绪` 即可。`Ctrl+C` 同时停止两层。

### 4. 自检

```bash
python scripts/client.py --doctor
```

三项全绿即全链路可用。

## 四、排障

**`未检测到 DuMate 桌面版进程`**
→ DuMate 没启动，或启动未完成。打开客户端等 30 秒。它的端口是动态的，客户端会从进程环境变量自动读，不用手配。

**`502 upstream unreachable`**
→ `points_api.py` 没起。先单独起 API 层确认能通，再套 relay。

**`401 invalid api token`**
→ relay 的 `DUMATE_API_TOKEN` 与 `points_api` 启动时的 `--token` 不一致。

**`403 invalid relay token`**
→ 调用方带的 token 与 relay 的 `RELAY_TOKEN` 不一致。注意 OpenAI SDK 会把 `api_key` 放进 `Authorization: Bearer`，relay 两种头都认。

**调用卡住不返回**
→ DuMate 在真干活（它会执行任务），`ultra` 档可能跑几分钟。不是挂了。relay 默认超时 900 秒，可用 `DUMATE_TIMEOUT` 调。

**积分掉得比预期快**
→ 每次调用都是完整 agent 会话（带思考 + 工具），比纯文本 API 贵。日常用 `lite`。

**DuMate 自动升级后全挂**
→ 内部协议/端口/key 机制变了。先跑上面的 `discover_opencode_url()` 验证发现逻辑，失败就得等上游项目更新。

**流式输出截断**
→ 检查是否用了不支持 chunked 的中间代理。relay 的流式是标准 chunked，中间再加一层反代要确保不缓冲。

## 五、安全

| 风险 | 说明 | 处置 |
|---|---|---|
| 无鉴权暴露 | `RELAY_TOKEN` 为空时任何人都能白嫖积分 | 必须设置强口令 |
| 公网裸露 | 端口映射到公网被扫 | 用 Tailscale 组网，不映射公网 |
| token 混用 | relay token 泄露 = 积分被盗刷 | 定期换、别写进代码仓库 |
| 账号风险 | 逆向个人积分违反百度 ToS，可能封号 | 知情后自行决定；别用主账号 |

## 六、上游项目

- 项目：dumate-api（MIT）
- 原理：读取本机 DuMate 进程环境变量拿到本地 opencode 服务地址与鉴权 key；读取 `%APPDATA%\qianfan-desktop-app\` 下的加密 cookie 查百度云积分
- 数据流向：**仅本机回环 + 百度官方服务器**，无第三方外发
