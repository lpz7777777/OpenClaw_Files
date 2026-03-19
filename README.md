# OpenClaw Files

基于 Electron + Python 的智能文件整理桌面工具，通过 OpenClaw AI 分析文件夹结构，生成可确认、可回滚的整理建议。

## 功能特性

### 核心功能

- **智能分析**：递归扫描各级子目录，构建 file_index 文件索引，依据文件名和文件类型重新规划目录结构
- **可视化工作区**：三栏布局，左侧资源树、中间文档预览、右侧分析面板
- **逐条确认**：每条建议可单独确认执行，也可一键执行全部
- **安全回滚**：支持最近一轮操作的逆序回滚
- **文档预览**：支持 Word (.docx)、Excel (.xlsx/.xls/.csv) 文件预览
- **规整化建议**：自动生成创建文件夹、重命名文件夹等规范化操作
- **启发式识别**：自动识别 Office 临时文件、重复下载文件、已解压压缩包等

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

## 支持的操作类型

| 操作类型 | 说明 | 安全机制 |
|----------|------|----------|
| move | 移动文件/文件夹到新位置 | 支持回滚 |
| rename | 重命名文件 | 支持回滚 |
| rename_folder | 重命名/合并文件夹 | 安全合并模式 |
| delete | 删除文件 | 同盘临时备份区 |
| create_folder | 创建新的分类文件夹 | 支持回滚 |

**delete 操作备份机制：**
- 删除的文件移动到同盘临时备份区：`{目标盘符}\.openclaw-delete-{随机后缀}\`
- 回滚时从备份区恢复
- 避免跨盘移动报错

**rename_folder 安全合并：**
- 目标目录不存在：直接重命名
- 目标目录已存在：检查子项冲突后合并

**启发式建议识别：**

系统会自动识别以下高置信模式并生成建议：

| 模式 | 建议类型 |
|------|----------|
| 已有同名解压目录的压缩包 | delete |
| ~$...docx/xlsx/pptx (Office 临时文件) | delete |
| 文件名 (1).docx (重复下载) | rename |
| 父目录 + 同名包装子目录 | move + delete |

## 最新改动

### 执行后自动生成根目录 README

当你点击“确认全部”并且本轮操作全部成功后，应用会在当前打开文件夹的根目录自动写入一个新的 `README.md`，内容包括：

- 当前目录概览
- 一级结构说明
- 目录树概览
- 本次整理结果

这个 README 会一并纳入回滚；如果你回滚最近一轮操作，README 也会恢复到原状态。

### 执行器稳定性增强

最近补了一轮针对真实测试目录的执行器修复，主要解决了这些常见失败：

- 父目录已重命名/已移动后，后续子路径找不到
- 目标目录已存在时的目录合并冲突
- 文件名空格数量或扩展名轻微偏差导致的路径匹配失败
- 同名目标已存在但其实是重复文件的冲突
- `rename_folder: A -> A` 这类空操作

当前执行器现在支持：

- 目录型 move 的后续路径自动重写
- rename_folder 安全合并与安全回滚
- 同内容重复文件自动去重并保留回滚能力
- 大目录执行时更稳的错误隔离与路径恢复

### 大目录分析的 Gateway 自适应压缩

为避免大目录分析时触发：

`Context overflow: prompt too large for the model`

后端现在会自动在不同 prompt profile 之间降级重试，用更紧凑的结构摘要再次请求 OpenClaw Gateway。也就是说，对于 `Test2`、`Test3` 一类目录，不再需要你手动 `/reset` 才能继续分析。

### 主题切换

顶部工具区新增了主题切换器，目前提供两套主题：

- `当前工作区`：现有浅色工作区主题
- `Mac 风格`：偏 macOS 的浅色玻璃风格主题

主题选择会保存在本地，下次打开应用会自动恢复。

## 注意事项

- 执行文件整理前，建议先备份重要数据
- 回滚只支持最近一轮操作
- 如果 Gateway 模式不可用，应用会回退到直连 Anthropic API 模式
- 如果未配置有效的 API key 且 Gateway 也不可用，后端会在分析时提示配置错误

## 许可证

MIT

## 附录：Git 推送方法

### 问题背景

如果你的全局 Git 配置中有类似以下配置：

```bash
url.https://gitclone.com/github.com/.insteadof=ssh://git@github.com/
url.https://gitclone.com/github.com/.insteadof=git@github.com:
url.https://gitclone.com/github.com/.insteadof=https://github.com/
```

这会导致所有 GitHub 请求被重写到 `gitclone.com`，当该服务不可用时会返回 502 错误。

### 解决方案

**方案一：临时移除全局重写规则（推荐）**

```bash
# 移除 gitclone 重写规则
git config --global --remove-section url."https://gitclone.com/github.com/"

# 然后正常推送
git add .
git commit -m "提交信息"
git push origin main
```

**方案二：使用 -c 参数临时覆盖**

```bash
git -c url."https://github.com/".insteadof= push origin main
```

**方案三：直接修改远程 URL**

```bash
# 查看当前远程 URL
git remote -v

# 如果显示的是 gitclone.com，修改为 GitHub
git remote set-url origin https://github.com/lpz7777777/OpenClaw_Files.git

# 推送
git push origin main
```

### 验证推送成功

访问仓库页面确认最新提交：
```
https://github.com/lpz7777777/OpenClaw_Files
```
