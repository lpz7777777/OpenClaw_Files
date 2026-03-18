@echo off
echo ========================================
echo OpenClaw 文件管理系统
echo ========================================
echo.

REM 检查.env文件是否存在
if not exist .env (
    echo 错误: 未找到 .env 文件
    echo 请先复制 .env.example 为 .env 并配置您的 ANTHROPIC_API_KEY
    echo.
    pause
    exit /b 1
)

echo 正在启动应用...
echo.
npm start
