#!/bin/bash
# 启动增强版一体机监控系统

echo "启动增强版一体机监控系统..."

# 激活虚拟环境
source .venv/bin/activate

# 设置环境变量
export SAMPLE_INTERVAL=5
export PYTHONPATH=/data/one-box

# 启动应用
echo "启动监控服务..."
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload
