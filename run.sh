#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PYPI_MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
VENV=".venv"; PYTHON=${PYTHON:-python3}
[ -d "$VENV" ] || $PYTHON -m venv "$VENV"
source "$VENV/bin/activate"
pip install -U pip || true
pip config set global.index-url $PYPI_MIRROR || true
pip install -r requirements.txt || pip install -r requirements.txt -i https://pypi.org/simple
export APP_ENV=${APP_ENV:-dev} APP_SECRET=${APP_SECRET:-"change-this-secret"} SAMPLE_INTERVAL=${SAMPLE_INTERVAL:-5}
exec uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-8000} --reload --proxy-headers
