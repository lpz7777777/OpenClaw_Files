# 快速开始

## 1. 安装依赖

```bash
npm install
pip install -r requirements.txt
```

## 2. 配置 `.env`

复制模板：

```bash
copy .env.example .env
```

### 方案 A：直连 Anthropic API

```env
USE_GATEWAY=false
ANTHROPIC_API_KEY=your_actual_api_key_here
```

### 方案 B：通过 OpenClaw Gateway WebSocket

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

## 3. 先验证 Gateway

```bash
python test_gateway.py
python discover_gateway.py
```

理想输出应该包含：

- WebSocket 握手成功
- `Connection probe: ok=True`
- `Chat probe: ok=True`
- 测试消息发送成功

如果第一次运行触发设备配对，当前工程会优先尝试自动在本机完成审批，并把设备状态保存在 `.openclaw-state`。

## 4. 启动应用

```bash
npm start
```

应用会自动：

1. 启动 Python 后端服务
2. 启动 Electron 桌面界面

## 5. 使用应用

1. 点击“选择文件夹”
2. 选择要整理的目录
3. 等待 AI 生成整理方案
4. 确认后执行操作
5. 如有需要，执行最近一次回滚

## 6. 常见问题

### WebSocket 连不上

- 检查 `GATEWAY_URL`
- 检查 OpenClaw Gateway 是否已启动
- 检查 `GATEWAY_TOKEN`

### 能连上但不能发消息

- 运行 `python test_gateway.py`
- 检查是否出现 `pairing required`
- 检查是否出现 `missing scope`
- 确认 `.openclaw-state/identity` 下已生成设备文件

### 想先绕过 Gateway

- 把 `USE_GATEWAY=false`
- 填入有效的 `ANTHROPIC_API_KEY`
