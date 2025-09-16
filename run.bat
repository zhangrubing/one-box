@echo off
cd /d %~dp0
set "APP_ENV=dev"
set "APP_SECRET=change-this-secret"
set "SAMPLE_INTERVAL=5"
pip install -r requirements.txt
uvicorn backend.app:app --host 0.0.0.0 --port 9090 --reload --proxy-headers
