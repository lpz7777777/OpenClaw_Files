# OpenClaro / 澄理 - 打包与分发指南

## 📦 打包步骤

### 前置要求

1. **Node.js 环境**
   - 安装 Node.js 16+ (推荐 LTS 版本)
   - 验证安装：`node --version`

2. **Python 环境**
   - 安装 Python 3.8+
   - 验证安装：`python --version`

3. **安装依赖**
   ```bash
   # 安装 Node 依赖
   npm install

   # 安装 Python 依赖
   pip install -r requirements.txt

   # 安装 PyInstaller
   pip install pyinstaller
   ```

### 执行打包

#### Windows 系统

```bash
# 方式一：使用 npm 脚本（推荐）
npm run build:win

# 方式二：手动执行
# 1. 构建 Python 后端
npm run build:backend

# 2. 使用 electron-builder 打包
npx electron-builder --win nsis
```

#### 打包输出

打包完成后，在 `release/` 目录中会生成以下文件：

- `OpenClaw Files-Setup-1.0.0.exe` - Windows 安装程序（NSIS 格式）

### 手动打包（如遇问题）

如果自动打包失败，可以按照以下步骤手动打包：

#### 1. 构建 Python 后端

```bash
cd backend
pyinstaller --noconfirm --clean --onedir --name OpenClawBackend server.py
cd ..
```

#### 2. 准备 Electron 资源

```bash
# 确保后端构建完成
ls build/backend/dist/OpenClawBackend/
```

#### 3. 执行 Electron 打包

```bash
npx electron-builder --win nsis --x64
```

---

## 📤 分发方法

### 方式一：直接分发安装程序（推荐）

**适用场景**：小范围分发、内部测试

1. **获取安装程序**
   - 从 `release/` 目录获取 `OpenClaw Files-Setup-1.0.0.exe`

2. **分发渠道**
   - 📧 邮件发送
   - 💾 网盘分享（百度网盘、OneDrive 等）
   - 💬 即时通讯工具（微信、QQ）
   - 🖥️ 公司内部文件服务器

3. **安装说明**
   ```
   1. 双击 OpenClaw Files-Setup-1.0.0.exe
   2. 选择安装位置（默认：C:\Program Files\OpenClaw Files）
   3. 创建桌面快捷方式（可选）
   4. 点击"安装"
   5. 安装完成后运行应用
   ```

### 方式二：GitHub Releases 分发

**适用场景**：开源项目、公开分发

1. **上传到 GitHub Releases**
   ```bash
   # 访问 https://github.com/lpz7777777/OpenClaw_Files/releases
   # 创建新 Release
   # 上传 OpenClaw Files-Setup-1.0.0.exe
   ```

2. **编写 Release 说明**
   - 版本号
   - 发布日期
   - 更新内容
   - 安装说明
   - 系统要求

3. **分享 Release 链接**
   ```
   https://github.com/lpz7777777/OpenClaw_Files/releases/latest
   ```

### 方式三：绿色版打包（可选）

**适用场景**：免安装、便携使用

1. **修改 package.json**
   ```json
   "build": {
     "win": {
       "target": "dir"
     }
   }
   ```

2. **执行打包**
   ```bash
   npx electron-builder --win dir
   ```

3. **压缩分发**
   - 将生成的文件夹压缩为 ZIP
   - 分发给用户后解压即可使用

---

## 💻 系统要求

### 最低配置

- **操作系统**：Windows 10 64 位
- **处理器**：Intel Core i3 或同等性能 AMD 处理器
- **内存**：4 GB RAM
- **硬盘空间**：500 MB 可用空间
- **显示器**：1280x720 分辨率

### 推荐配置

- **操作系统**：Windows 11 64 位
- **处理器**：Intel Core i5 或同等性能 AMD 处理器
- **内存**：8 GB RAM
- **硬盘空间**：1 GB 可用空间（SSD 更佳）
- **显示器**：1920x1080 分辨率

### 外部依赖

应用需要以下外部工具（可选）：

1. **OpenClaw CLI**（用于 AI 分析）
   - 安装方式：`pip install openclaw`
   - 或使用 WSL 版本

2. **bdpan CLI**（用于百度网盘同步）
   - 安装方式：按照 bdpan 官方文档安装

---

## 🔧 常见问题

### Q1: 打包时遇到 "electron-builder 不是内部命令"

**解决方案**：
```bash
npm install electron-builder --save-dev
```

### Q2: PyInstaller 打包失败

**解决方案**：
```bash
# 清理缓存
pip uninstall pyinstaller
pip install pyinstaller

# 重新打包
npm run build:backend
```

### Q3: 安装程序无法运行

**解决方案**：
- 右键点击安装程序 → "以管理员身份运行"
- 检查 Windows Defender 是否阻止
- 确保 .NET Framework 已安装

### Q4: 应用启动后闪退

**解决方案**：
1. 检查 `.env` 文件是否正确配置
2. 查看应用日志：`%APPDATA%\OpenClaw Files\logs\`
3. 重新安装 Visual C++ Redistributable

### Q5: 缺少 Python 后端

**解决方案**：
- 确保 `build/backend/dist/OpenClawBackend/` 目录存在
- 重新运行 `npm run build:backend`
- 检查 PyInstaller 版本是否兼容

---

## 📝 用户安装指南

### 安装步骤

1. **下载安装程序**
   - 从 GitHub Releases 或分发渠道获取安装包

2. **运行安装程序**
   - 双击 `OpenClaw Files-Setup-1.0.0.exe`
   - 如果提示"智能屏幕筛选器"，点击"更多信息" → "仍要运行"

3. **选择安装位置**
   - 默认：`C:\Program Files\OpenClaw Files`
   - 或自定义到其他位置

4. **创建快捷方式**
   - ☑️ 创建桌面快捷方式
   - ☑️ 创建开始菜单快捷方式

5. **完成安装**
   - 点击"安装"
   - 等待安装完成
   - 勾选"运行 OpenClaw Files"
   - 点击"完成"

### 首次使用配置

1. **配置环境变量**
   - 应用会自动创建 `.env` 文件
   - 根据提示配置 OpenClaw Gateway 或 API Key

2. **测试连接**
   - 打开应用
   - 选择一个测试文件夹
   - 点击"分析"按钮

3. **开始使用**
   - 选择需要整理的文件夹
   - 查看 AI 生成的整理建议
   - 确认执行或逐条确认

---

## 🚀 批量部署（企业用户）

### 静默安装

```batch
OpenClaw-Files-Setup-1.0.0.exe /S
```

### 自定义安装路径

```batch
OpenClaw-Files-Setup-1.0.0.exe /S /D=C:\Program Files\OpenClaw
```

### 部署脚本示例

```batch
@echo off
echo 正在安装 OpenClaw Files...
OpenClaw-Files-Setup-1.0.0.exe /S
echo 安装完成！
pause
```

---

## 📊 版本更新

### 自动更新（未来功能）

应用将支持自动检测更新并提示用户升级。

### 手动更新

1. 下载新版本安装程序
2. 运行安装程序覆盖安装
3. 用户数据会保留

---

## 📞 技术支持

如遇到打包或分发问题，请：

1. 查看 GitHub Issues
2. 提交新的 Issue 并附上错误日志
3. 联系开发团队

---

**最后更新**：2026-03-19  
**版本**：1.0.0
