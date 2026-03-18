# OpenClaw 文件管理系统

一个基于 Electron + Python 的桌面文件整理工具。应用会分析目标文件夹结构，并生成可确认、可回滚的整理计划。

当前工程支持两种 AI 调用方式：

1. 直接调用 Anthropic API
2. 通过本地 OpenClaw Gateway 的 WebSocket 网关调用

## 功能

- 选择任意本地文件夹进行分析
- 生成文件分类与重命名建议
- 用户确认后执行移动或重命名
- 支持最近一次操作回滚
- 支持 Anthropic API 和 OpenClaw Gateway 双模式

## 技术栈

- 前端: Electron + HTML/CSS/JavaScript
- 后端: Python + HTTP Server
- AI: Anthropic Claude API 或 OpenClaw Gateway WebSocket

## 安装

```bash
npm install
pip install -r requirements.txt
```

## 配置

先复制环境变量模板：

```bash
copy .env.example .env
```

### 方式 1：直连 Anthropic API

```env
USE_GATEWAY=false
ANTHROPIC_API_KEY=your_actual_api_key_here
```

### 方式 2：使用 OpenClaw Gateway WebSocket

如果你的 Gateway 运行在 `ws://127.0.0.1:18789`，并使用本地 token `openclaw-local-token`，可以这样配置：

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
```

说明：

- `GATEWAY_URL`：Gateway 的 WebSocket 地址。
- `GATEWAY_TOKEN`：当前本地 Gateway token。
- `GATEWAY_PASSWORD`：如果你的实例还要求 shared/system password，可在这里填写。
- `GATEWAY_SESSION_KEY`：当前默认主会话键可设置为 `agent:main:main`。
- `GATEWAY_SCOPES`：默认请求 `operator.read,operator.write`，如果当前 token 权限不足，测试脚本会直接提示缺少 scope。

## Gateway 接入方式

本工程现在使用的 Gateway 接口为 WebSocket：

- WebSocket URL：`ws://127.0.0.1:18789`
- 认证：token 或 password
- 当前客户端标识：`gateway-client`
- 当前模式：`backend`

后端会通过 WebSocket RPC 调用以下能力：

- `connect`
- `chat.send`
- `chat.history`

## 启动

```bash
npm start
```

应用会启动：

1. Python 后端服务，默认端口 `8765`
2. Electron 桌面界面

## 使用流程

1. 点击“选择文件夹”
2. 选择需要整理的本地目录
3. 等待系统生成整理方案
4. 确认后执行文件操作
5. 如有需要，可执行最近一次回滚

## Gateway 验证脚本

可以用下面两个脚本做本地检查：

```bash
python test_gateway.py
python discover_gateway.py
```

它们会检查：

- WebSocket 握手是否成功
- 当前 token/password 是否可用
- 当前会话键是否正确
- `chat.history` / `chat.send` 是否被 scope 限制

## 当前已验证的本地事实

在你这台机器上，当前 OpenClaw 实例已经确认：

- 控制台页面可访问
- 健康检查正常
- 实际接入方式是 WebSocket，不是 `/v1/responses`
- `openclaw-control-ui` 这类浏览器控制台客户端会要求设备身份
- `gateway-client` 这类普通 WebSocket 客户端可以直接用 token 建立连接

如果握手成功但聊天请求仍失败，并提示 `missing scope: operator.read` 或 `missing scope: operator.write`，那说明：

- 当前 token 能连上 Gateway
- 但它没有授予当前请求所需的操作权限

这时需要调整：

1. Gateway token 本身的权限
2. 或者补充 `GATEWAY_PASSWORD`
3. 或者在 OpenClaw 侧放宽当前客户端可请求的 scope

## 项目结构

```text
OpenClaw_Files/
├── backend/
│   ├── file_analyzer.py
│   ├── gateway_client.py
│   └── server.py
├── discover_gateway.py
├── test_gateway.py
├── index.html
├── renderer.js
├── main.js
├── styles.css
├── README.md
├── QUICKSTART.md
├── OPENCLAW_GATEWAY.md
├── .env.example
└── requirements.txt
```

## 注意事项

- 执行文件整理前，建议先备份重要数据
- 回滚只支持最近一次操作
- 如果 Gateway 模式不可用，应用会回退到直连 Anthropic API 模式
- 如果未配置有效的 Anthropic API key，且 Gateway 也不可用，后端会在分析时提示配置错误

## 许可证

MIT
