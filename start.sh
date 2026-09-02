#!/usr/bin/env bash
# ============================================================
# 短信转发程序启动脚本
# 用法: ./start.sh
# 以后台方式运行 main.py，PID 写入 run.pid
# ============================================================
set -euo pipefail

# 切换到脚本所在目录，保证相对路径正确
cd "$(dirname "$0")"

# 选择 Python 解释器：优先使用项目虚拟环境，否则使用系统 python3
PYTHON="${PYTHON:-python3}"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

mkdir -p logs

# 配置检查
if [ ! -f "config.json" ]; then
    echo "[错误] 未找到 config.json，请先执行："
    echo "  cp config.json.example config.json"
    echo "然后编辑 config.json 填写 SMTP 信息（服务器、账号、授权码、收件人）。"
    exit 1
fi

# 已在运行则退出
if [ -f "run.pid" ] && kill -0 "$(cat run.pid)" 2>/dev/null; then
    echo "程序已在运行 (PID $(cat run.pid))。如需重启请先执行 ./stop.sh"
    exit 1
fi

# 后台启动
nohup "$PYTHON" main.py >> logs/console.log 2>&1 &
PID=$!
echo "$PID" > run.pid

echo "短信转发程序已启动 (PID $PID)"
echo "日志文件: logs/app.log（控制台输出: logs/console.log）"
echo "停止: ./stop.sh"
