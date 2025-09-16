#!/usr/bin/env bash
# build.sh — 生成“OBM 一键安装包”（/opt/obm + root + 9090 + systemd + uvicorn）
# 特性：
# 1) systemd ExecStart 采用 EnvironmentFile 注入变量 + bash -lc 调用 uvicorn（避免变量提前展开的坑）
# 2) 打包时排除 data/ 下数据库文件（*.db/*.sqlite/*.sqlite3 及 wal/shm/journal）
# 3) 统一 .sh 转 LF 并加执行位，避免 203/EXEC
# 4) 可选“离线依赖”：构建阶段用 `pip download` 将 requirements 下载到 wheels/，安装时优先离线安装，失败再回退在线安装
set -euo pipefail

VERSION="1.0.4-uvicorn-opt-root"
SERVICE_NAME="obm"
BUILD_DIR="build"
STAGE_DIR="${BUILD_DIR}/${SERVICE_NAME}-installer-${VERSION}"
OUT_TGZ="${BUILD_DIR}/${SERVICE_NAME}-installer-${VERSION}.tar.gz"

log(){ echo -e "\033[1;32m[BUILD]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[WARN]\033[0m  $*"; }
has(){ command -v "$1" >/dev/null 2>&1; }

copy_app() {
  local dst="$1"; mkdir -p "$dst"
  local ex=(
    "--exclude=.git" "--exclude=.github" "--exclude=.idea" "--exclude=.vscode"
    "--exclude=__pycache__" "--exclude=*.pyc" "--exclude=.venv" "--exclude=venv"
    "--exclude=node_modules" "--exclude=${BUILD_DIR}"
    "--exclude=data/*.db" "--exclude=data/*.sqlite" "--exclude=data/*.sqlite3"
    "--exclude=data/*.db-wal" "--exclude=data/*.db-shm" "--exclude=data/*.wal" "--exclude=data/*-journal"
    "--exclude=data/**/*.db" "--exclude=data/**/*.sqlite" "--exclude=data/**/*.sqlite3"
    "--exclude=data/**/*.db-wal" "--exclude=data/**/*.db-shm" "--exclude=data/**/*.wal" "--exclude=data/**/*-journal"
  )
  if has rsync; then
    rsync -a "${ex[@]}" ./ "$dst/"
  else
    warn "未找到 rsync，用 tar 复制（建议安装 rsync）。"
    local t; t="$(mktemp -u).tar"
    # shellcheck disable=SC2086
    tar -cf "$t" \
      --exclude=.git --exclude=.github --exclude=.idea --exclude=.vscode \
      --exclude=__pycache__ --exclude='*.pyc' --exclude=.venv --exclude=venv \
      --exclude=node_modules --exclude="${BUILD_DIR}" \
      --exclude='data/*.db' --exclude='data/*.sqlite' --exclude='data/*.sqlite3' \
      --exclude='data/*.db-wal' --exclude='data/*.db-shm' --exclude='data/*.wal' --exclude='data/*-journal' \
      --exclude='data/**/*.db' --exclude='data/**/*.sqlite' --exclude='data/**/*.sqlite3' \
      --exclude='data/**/*.db-wal' --exclude='data/**/*.db-shm' --exclude='data/**/*.wal' --exclude='data/**/*-journal' \
      .
    tar -xf "$t" -C "$dst"; rm -f "$t"
  fi
}

detect_app_module() {
  local f
  f="$(grep -R -n --include='*.py' -E 'FastAPI\s*\(' . 2>/dev/null | cut -d: -f1 | head -n1 || true)"
  if [[ -n "${f:-}" ]] && grep -qE 'app\s*=\s*FastAPI\s*\(' "$f"; then
    f="${f#./}"; f="${f%.py}"; echo "${f//\//.}:app"; return
  fi
  f="$(grep -R -n --include='*.py' -E 'Flask\s*\(' . 2>/dev/null | cut -d: -f1 | head -n1 || true)"
  if [[ -n "${f:-}" ]] && grep -qE 'app\s*=\s*Flask\s*\(' "$f"; then
    f="${f#./}"; f="${f%.py}"; echo "${f//\//.}:app"; return
  fi
  echo "backend.app:app"
}

normalize_sh() {
  local base="$1"
  [[ -d "$base" ]] || return 0
  find "$base" -type f -name "*.sh" -print0 | while IFS= read -r -d '' f; do
    sed -i 's/\r$//' "$f" || true
    chmod +x "$f" || true
  done
}

build_wheels() {
  # 将依赖下载到 wheels/，包含 wheels 和 sdists，安装时优先离线
  local appdir="$1"
  [[ -f "${appdir}/requirements.txt" ]] || { warn "未找到 requirements.txt，跳过离线依赖打包"; return 0; }
  mkdir -p "${STAGE_DIR}/wheels"
  local pip_idx="${PIP_INDEX_URL:-}"
  log "下载依赖到 wheels/（pip download）…"
  if [[ -n "$pip_idx" ]]; then
    python3 -m pip download -r "${appdir}/requirements.txt" -d "${STAGE_DIR}/wheels" --index-url "$pip_idx" || warn "pip download 遇到问题，安装时将回退在线模式"
  else
    python3 -m pip download -r "${appdir}/requirements.txt" -d "${STAGE_DIR}/wheels" || warn "pip download 遇到问题，安装时将回退在线模式"
  fi
}

mkdir -p "$BUILD_DIR"; rm -rf "$STAGE_DIR"; mkdir -p "$STAGE_DIR"

APP_MODULE_DEFAULT="$(detect_app_module)"
log "APP_MODULE 检测为：${APP_MODULE_DEFAULT}"

log "拷贝项目源码 → app/"
copy_app "${STAGE_DIR}/app"

log "写 env.example"
cat > "${STAGE_DIR}/env.example" <<EOF
# 安装时复制为 /etc/${SERVICE_NAME}.env
APP_ENV=prod
APP_SECRET=change-this-secret
PORT=9090
APP_MODULE=${APP_MODULE_DEFAULT}
# 其他可选
WORKERS=2
TIMEOUT=120
# PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
EOF

log "写 systemd 单元模板（依赖 EnvironmentFile 的变量）"
cat > "${STAGE_DIR}/${SERVICE_NAME}.service.tpl" <<'EOF'
[Unit]
Description={{SERVICE_NAME}} Python Web Service
After=network.target

[Service]
User={{RUN_USER}}
Group={{RUN_GROUP}}
WorkingDirectory={{APP_DIR}}
EnvironmentFile=-/etc/{{SERVICE_NAME}}.env
ExecStart=/usr/bin/env bash -lc '/opt/obm/.venv/bin/uvicorn "${APP_MODULE:-backend.app:app}" --host 0.0.0.0 --port "${PORT:-9090}" --proxy-headers'
Restart=always
RestartSec=3
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

log "写 install.sh（支持离线 wheels 优先安装）"
cat > "${STAGE_DIR}/install.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
RUN_USER="${RUN_USER:-root}"
RUN_GROUP="${RUN_GROUP:-root}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${VENV_DIR:-.venv}"
APP_SRC_DIR="${APP_SRC_DIR:-app}"
ENV_SRC_FILE="${ENV_SRC_FILE:-env.example}"
UNIT_TEMPLATE="${UNIT_TEMPLATE:-obm.service.tpl}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --app-dir)      APP_DIR="$2"; shift 2 ;;
    --user)         RUN_USER="$2"; shift 2 ;;
    --group)        RUN_GROUP="$2"; shift 2 ;;
    --python)       PYTHON_BIN="$2"; shift 2 ;;
    --venv)         VENV_DIR="$2"; shift 2 ;;
    --app-src)      APP_SRC_DIR="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Please run as root"; exit 1; }

need_pkgs=()
command -v "$PYTHON_BIN" >/dev/null 2>&1 || need_pkgs+=("python3")
"$PYTHON_BIN" -m venv --help >/dev/null 2>&1 || need_pkgs+=("python3-venv")
if [[ ${#need_pkgs[@]} -gt 0 ]]; then
  if command -v apt-get >/dev/null 2>&1; then apt-get update -y && apt-get install -y "${need_pkgs[@]}";
  elif command -v dnf >/dev/null 2>&1; then dnf install -y python3 python3-virtualenv || dnf install -y python3 python3-venv || true;
  elif command -v yum >/dev/null 2>&1; then yum install -y python3 python3-virtualenv || yum install -y python3 || true;
  else echo "Install manually: ${need_pkgs[*]}"; exit 1; fi
fi

mkdir -p "$APP_DIR"
if command -v rsync >/dev/null 2>&1; then rsync -a --delete "${APP_SRC_DIR}/" "$APP_DIR/"; else
  t="$(mktemp -u).tar"; tar -C "${APP_SRC_DIR}" -cf "$t" .; tar -C "$APP_DIR" -xf "$t"; rm -f "$t"; fi
chown -R "$RUN_USER:$RUN_GROUP" "$APP_DIR"

# 兜底：规范 .sh
find "$APP_DIR" -type f -name "*.sh" -exec sed -i 's/\r$//' {} +
find "$APP_DIR" -type f -name "*.sh" -exec chmod 755 {} +

cd "$APP_DIR"
if [[ ! -d "$VENV_DIR" ]]; then "$PYTHON_BIN" -m venv "$VENV_DIR"; fi
source "$VENV_DIR/bin/activate"

ENV_FILE="/etc/${SERVICE_NAME}.env"
[[ -f "$ENV_FILE" ]] && source "$ENV_FILE"
[[ -n "${PIP_INDEX_URL:-}" ]] && pip config set global.index-url "$PIP_INDEX_URL" || true
pip install -U pip wheel || true

# 优先离线安装（如 wheels/ 存在），失败回退在线
if [[ -d "$OLDPWD/wheels" ]]; then
  pip install --no-index --find-links "$OLDPWD/wheels" -r requirements.txt || pip install -r requirements.txt
else
  [[ -f requirements.txt ]] && pip install -r requirements.txt
fi

# /etc/obm.env
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$OLDPWD/$ENV_SRC_FILE" ]]; then cp "$OLDPWD/$ENV_SRC_FILE" "$ENV_FILE"; else
    cat > "$ENV_FILE" <<EOF2
APP_ENV=prod
APP_SECRET=change-this-secret
PORT=9090
APP_MODULE=backend.app:app
WORKERS=2
TIMEOUT=120
EOF2
  fi
fi
chmod 640 "$ENV_FILE"

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
tpl="$(cat "$OLDPWD/$UNIT_TEMPLATE")"
tpl="${tpl//\{\{SERVICE_NAME\}\}/$SERVICE_NAME}"
tpl="${tpl//\{\{RUN_USER\}\}/$RUN_USER}"
tpl="${tpl//\{\{RUN_GROUP\}\}/$RUN_GROUP}"
tpl="${tpl//\{\{APP_DIR\}\}/$APP_DIR}"
echo "$tpl" > "$UNIT_PATH"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" || true
echo "Logs: journalctl -u ${SERVICE_NAME} -f"
EOF
chmod +x "${STAGE_DIR}/install.sh"

log "写 upgrade.sh / uninstall.sh"
cat > "${STAGE_DIR}/upgrade.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
APP_SRC_DIR="${APP_SRC_DIR:-app}"
[[ $EUID -eq 0 ]] || { echo "Please run as root"; exit 1; }

systemctl stop "$SERVICE_NAME" || true
ts=$(date +%Y%m%d-%H%M%S); mkdir -p "${APP_DIR}/releases"
tar -C "${APP_DIR}" -czf "${APP_DIR}/releases/app-${ts}.tar.gz" .

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude ".venv" "${APP_SRC_DIR}/" "${APP_DIR}/"
else
  t="$(mktemp -u).tar"; tar -C "${APP_SRC_DIR}" -cf "$t" .; tar -C "${APP_DIR}" -xf "$t"; rm -f "$t"
fi

find "$APP_DIR" -type f -name "*.sh" -exec sed -i 's/\r$//' {} +
find "$APP_DIR" -type f -name "*.sh" -exec chmod 755 {} +

if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  source "${APP_DIR}/.venv/bin/activate"
  # 优先使用升级包旁的 wheels/
  if [[ -d "$OLDPWD/wheels" ]]; then
    pip install --no-index --find-links "$OLDPWD/wheels" -r "${APP_DIR}/requirements.txt" || pip install -r "${APP_DIR}/requirements.txt"
  else
    pip install -r "${APP_DIR}/requirements.txt"
  fi
fi
systemctl start "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME" || true
EOF
chmod +x "${STAGE_DIR}/upgrade.sh"

cat > "${STAGE_DIR}/uninstall.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
RUN_USER="${RUN_USER:-root}"
RUN_GROUP="${RUN_GROUP:-root}"
[[ $EUID -eq 0 ]] || { echo "Please run as root"; exit 1; }

read -r -p "Stop and disable ${SERVICE_NAME}? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  systemctl stop "${SERVICE_NAME}" || true
  systemctl disable "${SERVICE_NAME}" || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
fi
read -r -p "Remove /etc/${SERVICE_NAME}.env ? [y/N] " yn
[[ "${yn,,}" == "y" ]] && rm -f "/etc/${SERVICE_NAME}.env"
read -r -p "Remove ${APP_DIR}? [y/N] " yn
[[ "${yn,,}" == "y" ]] && rm -rf "${APP_DIR}"
read -r -p "Delete user/group ${RUN_USER}/${RUN_GROUP}? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  userdel -r "${RUN_USER}" 2>/dev/null || true
  groupdel "${RUN_GROUP}" 2>/dev/null || true
fi
echo "Uninstalled."
EOF
chmod +x "${STAGE_DIR}/uninstall.sh"

log "写 README.txt"
cat > "${STAGE_DIR}/README.txt" <<EOF
OBM Installer (systemd + uvicorn) — v${VERSION}

默认：/opt/obm 安装，服务名 obm，自启，端口 9090，root 运行。
Unit 使用 EnvironmentFile 的 PORT/APP_MODULE，并通过 bash -lc 调用 uvicorn。

打包：
- 已排除 data/ 下数据库文件（*.db/*.sqlite/*.sqlite3 及 wal/shm/journal）
- 已统一 .sh 为 LF + 可执行
- 若本地存在 requirements.txt，会将依赖下载到 wheels/，安装/升级时优先离线安装（失败回退在线）

安装：
  sudo ./install.sh
日志：
  journalctl -u obm -f
升级：
  sudo ./upgrade.sh
卸载：
  sudo ./uninstall.sh
EOF

# 规范 .sh
normalize_sh "$STAGE_DIR"

# 可选：构建离线依赖
build_wheels "${STAGE_DIR}/app" || true

# 打包
mkdir -p "$BUILD_DIR"
tar -C "$BUILD_DIR" -czf "$OUT_TGZ" "$(basename "$STAGE_DIR")"
echo "DONE -> ${OUT_TGZ}"
