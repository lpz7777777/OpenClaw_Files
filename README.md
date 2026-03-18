# OpenClaw Files

基于 Electron + Python 的智能文件整理桌面工具，通过 OpenClaw AI 分析文件夹结构，生成可确认、可回滚的整理建议。

## 功能特性

### 核心功能

- **智能分析**：递归扫描各级子目录，分析文件分布、扩展名聚类，生成详细的整理建议
- **可视化工作区**：三栏布局，左侧资源树、中间文档预览、右侧分析面板
- **逐条确认**：每条建议可单独确认执行，也可一键执行全部
- **安全回滚**：支持最近一轮操作的逆序回滚
- **文档预览**：支持 Word (.docx)、Excel (.xlsx/.xls/.csv) 文件预览

### 界面特性

- 浅色扁平主题，清晰舒适
- 文件类型图标与颜色区分
- 结构化分析摘要显示
- 多标签页文件预览

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Electron + HTML/CSS/JavaScript |
| 后端 | Python + HTTP Server |
| AI | OpenClaw Gateway (WebSocket) 或 Anthropic API |

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/lpz7777777/OpenClaw_Files.git
cd OpenClaw_Files
```

### 2. 安装依赖

```bash
npm install
pip install -r requirements.txt
```

## 配置

复制环境变量模板：

```bash
copy .env.example .env
```

### 方式一：使用 OpenClaw Gateway（推荐）

如果你的 OpenClaw Gateway 运行在 `ws://127.0.0.1:18789`：

```env
USE_GATEWAY=true
GATEWAY_URL=ws://127.0.0.1:18789
GATEWAY_TOKEN=openclaw-local-token
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

### 方式二：直连 Anthropic API

```env
USE_GATEWAY=false
ANTHROPIC_API_KEY=your_actual_api_key_here
```

## 启动

```bash
npm start
```

应用会同时启动：
- Python 后端服务（默认端口 8765）
- Electron 桌面界面

## 使用流程

1. **选择文件夹**：点击"选择文件夹"，选择需要整理的本地目录
2. **等待分析**：系统会递归扫描目录结构，通过 AI 生成整理建议
3. **查看建议**：右侧面板显示结构化分析摘要和操作建议
4. **确认执行**：
   - 逐条确认：点击每条建议的"确认这条"按钮
   - 全部执行：点击底部"确认全部"按钮
5. **回滚（可选）**：如有需要，可执行最近一轮操作的回滚

## 项目结构

```
OpenClaw_Files/
├── backend/
│   ├── file_analyzer.py    # 文件分析与 AI 调用
│   ├── gateway_client.py   # OpenClaw Gateway 客户端
│   └── server.py           # HTTP 服务
├── index.html              # 主界面
├── renderer.js             # 前端逻辑
├── main.js                 # Electron 主进程
├── styles.css              # 样式
├── test_gateway.py         # Gateway 连接测试
├── discover_gateway.py     # Gateway 能力探测
├── .env.example            # 环境变量模板
├── requirements.txt        # Python 依赖
├── package.json            # Node 依赖
├── DEV_LOG.md              # 开发日志
└── README.md               # 本文件
```

## Gateway 验证

可以使用以下脚本验证 Gateway 连接：

```bash
python test_gateway.py
python discover_gateway.py
```

验证内容：
- WebSocket 握手是否成功
- 当前 token/password 是否可用
- 当前会话键是否正确
- chat.history / chat.send 是否被 scope 限制

## 支持的文件预览

| 类型 | 扩展名 | 支持程度 |
|------|--------|----------|
| 文本文件 | .txt, .md, .json, .js, .py, .html, .css 等 | 完整预览 |
| Word 文档 | .docx | 正文段落预览 |
| Excel 表格 | .xlsx, .xls, .csv | 首个工作表预览 |
| 旧版 Word | .doc | 兼容提示 |
| 其他文件 | 二进制文件 | 占位提示 |

## 注意事项

- 执行文件整理前，建议先备份重要数据
- 回滚只支持最近一轮操作
- 如果 Gateway 模式不可用，应用会回退到直连 Anthropic API 模式
- 如果未配置有效的 API key 且 Gateway 也不可用，后端会在分析时提示配置错误

## 许可证

MIT
