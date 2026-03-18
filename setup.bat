@echo off
echo ========================================
echo OpenClaw 文件管理系统 - 安装脚本
echo ========================================
echo.

echo [1/3] 检查依赖...
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误: 未找到 Node.js，请先安装 Node.js
    pause
    exit /b 1
)

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo 错误: 未找到 Python，请先安装 Python
    pause
    exit /b 1
)

echo [2/3] 安装 Node.js 依赖...
call npm install
if %errorlevel% neq 0 (
    echo 错误: Node.js 依赖安装失败
    pause
    exit /b 1
)

echo [3/3] 安装 Python 依赖...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo 错误: Python 依赖安装失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo 安装完成！
echo ========================================
echo.
echo 下一步:
echo 1. 复制 .env.example 为 .env
echo 2. 在 .env 文件中填入您的 ANTHROPIC_API_KEY
echo 3. 运行 start.bat 启动应用
echo.
pause
