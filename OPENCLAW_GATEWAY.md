# OpenClaw Gateway 集成说明

本项目现在通过 OpenClaw Gateway 的 WebSocket 接口接入本地 OpenClaw 实例，而不是旧的 HTTP `POST /v1/responses`。

当前确认可用的本地配置是：

- Gateway URL: `ws://127.0.0.1:18789`
- Gateway token: `openclaw-local-token`
- 默认会话 key: `agent:main:main`

## 为什么改成 WebSocket

实际探测结果表明：

- `http://127.0.0.1:18789/health` 可用
- 控制台页面可访问
- `POST /v1/responses` 返回 `404`

这说明当前 OpenClaw 实例暴露的是 Gateway WebSocket 协议，不是 OpenResponses HTTP API。

## 当前工程的连接方式

后端客户端位于 [backend/gateway_client.py](/d:/Coding%20Demo/202603_OpenClaw_Files/OpenClaw_Files/backend/gateway_client.py)，它现在会执行下面这条完整链路：

1. 连接 Gateway WebSocket。
2. 等待 `connect.challenge`。
3. 用本地持久化的 Ed25519 设备身份对 `v3` 载荷签名。
4. 使用 `gateway-client` / `backend` 作为客户端标识连接。
5. 首次遇到 `pairing required` 时，自动通过本地 OpenClaw CLI 审批当前工作区设备。
6. 连接成功后保存 Gateway 返回的 `deviceToken`。
7. 使用 `chat.history` / `chat.send` 与 OpenClaw 对话。

## 新增的本地状态目录

为了避免直接污染用户主目录，本项目默认把设备身份和设备 token 存在工程目录：

- 状态目录：`.openclaw-state`
- 设备身份文件：`.openclaw-state/identity/device.json`
- 设备 token 文件：`.openclaw-state/identity/device-auth.json`

这两个文件是 Gateway 配对成功后持续可复用的关键状态。

## 推荐 `.env` 配置

```env
USE_GATEWAY=true
GATEWAY_URL=ws://127.0.0.1:18789
GATEWAY_TOKEN=openclaw-local-token
GATEWAY_PASSWORD=
GATEWAY_AGENT_ID=main
GATEWAY_USER=main
GATEWAY_SESSION_KEY=agent:main:main
GATEWAY_MODEL=openclaw
GATEWAY_CLIENT_ID=gateway-client
GATEWAY_CLIENT_MODE=backend
GATEWAY_SCOPES=operator.read,operator.write
GATEWAY_TIMEOUT=60
GATEWAY_STATE_DIR=.openclaw-state
GATEWAY_AUTO_APPROVE_LOCAL_PAIRING=true
```

## 如何验证

运行：

```bash
python test_gateway.py
python discover_gateway.py
```

期望看到：

- `Connection probe: ok=True`
- `Chat probe: ok=True`
- 测试消息发送成功
- `discover_gateway.py` 中的 `chat.history` RPC 成功

## 如果仍然失败

优先看报错类型：

- `device signature invalid`
说明设备签名载荷和 Gateway 预期不一致，需要检查客户端签名逻辑。

- `pairing required`
说明网络和 token 已经基本正确，但设备还没被批准。当前工程默认会自动尝试本地审批。

- `missing scope: operator.read` 或 `missing scope: operator.write`
说明当前设备或认证方式还没有拿到对应权限，需要检查 Gateway 侧授予的 scope。

## 相关文件

- WebSocket 客户端：[backend/gateway_client.py](/d:/Coding%20Demo/202603_OpenClaw_Files/OpenClaw_Files/backend/gateway_client.py)
- 文件分析器：[backend/file_analyzer.py](/d:/Coding%20Demo/202603_OpenClaw_Files/OpenClaw_Files/backend/file_analyzer.py)
- 连通性测试：[test_gateway.py](/d:/Coding%20Demo/202603_OpenClaw_Files/OpenClaw_Files/test_gateway.py)
- 发现脚本：[discover_gateway.py](/d:/Coding%20Demo/202603_OpenClaw_Files/OpenClaw_Files/discover_gateway.py)
