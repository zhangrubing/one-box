#!/usr/bin/env bash
# build.sh — 打包“OBM 一键安装包”（/opt/obm + root + 9090 + systemd）
set -euo pipefail

VERSION="1.0.0"
SERVICE_NAME="obm"
BUILD_DIR="build"
STAGE_DIR="${BUILD_DIR}/${SERVICE_NAME}-installer-${VERSION}"
OUT_TGZ="${BUILD_DIR}/${SERVICE_NAME}-installer-${VERSION}.tar.gz"

# -------------- 工具函数 --------------
log(){ echo -e "\033[1;32m[BUILD]\033[0m $*"; }
warn(){ echo -e "\033[1;33m[WARN]\033[0m  $*"; }
die(){ echo -e "\033[1;31m[FAIL]\033[0m  $*"; exit 1; }

has_cmd(){ command -v "$1" >/dev/null 2>&1; }

copy_app() {
  # 将当前项目拷贝到 STAGE_DIR/app，排除常见无关目录
  local dst="$1"
  mkdir -p "$dst"

  local excludes=(
    "--exclude=.git" "--exclude=.github" "--exclude=.idea" "--exclude=.vscode"
    "--exclude=__pycache__" "--exclude=*.pyc" "--exclude=.venv" "--exclude=venv"
    "--exclude=node_modules" "--exclude=${BUILD_DIR}"
  )

  if has_cmd rsync; then
    log "使用 rsync 拷贝源码到 ${dst}/"
    rsync -a "${excludes[@]}" ./ "$dst/"
  else
    warn "rsync 不存在，改用 tar 拷贝（较慢）。建议 apt/yum 安装 rsync。"
    local tmp_tar
    tmp_tar="$(mktemp -u).tar"
    # shellcheck disable=SC2086
    tar -cf "$tmp_tar" $(printf " %s" "${excludes[@]/#/--exclude=}") .
    tar -xf "$tmp_tar" -C "$dst"
    rm -f "$tmp_tar"
  fi
}

detect_app_module() {
  # 自动检测 FastAPI/Flask 的 app 模块，找不到则回退 backend.app:app
  # 优先：FastAPI -> Flask
  local f
  f="$(grep -R -n --include='*.py' -E 'FastAPI\s*\(' . 2>/dev/null | cut -d: -f1 | head -n1 || true)"
  if [[ -n "${f:-}" ]] && grep -qE 'app\s*=\s*FastAPI\s*\(' "$f"; then
    f="${f#./}"; f="${f%.py}"; echo "${f//\//.}:app"; return 0
  fi
  f="$(grep -R -n --include='*.py' -E 'Flask\s*\(' . 2>/dev/null | cut -d: -f1 | head -n1 || true)"
  if [[ -n "${f:-}" ]] && grep -qE 'app\s*=\s*Flask\s*\(' "$f"; then
    f="${f#./}"; f="${f%.py}"; echo "${f//\//.}:app"; return 0
  fi
  # TODO: 如需支持 Django，可自行改成 myproj.asgi:application
  echo "backend.app:app"
}

# -------------- 开始构建 --------------
mkdir -p "$BUILD_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR"

APP_MODULE_DEFAULT="$(detect_app_module)"
log "检测到 APP_MODULE: ${APP_MODULE_DEFAULT}"

# 1) app 源码
log "拷贝项目到安装包 app/"
copy_app "${STAGE_DIR}/app"

# 2) env.example
log "生成 env.example"
cat > "${STAGE_DIR}/env.example" <<EOF
# 将在安装时复制到 /etc/${SERVICE_NAME}.env
APP_ENV=prod
APP_SECRET=change-this-secret
PORT=9090

# 应用入口模块: 对应 "模块路径:对象名"
APP_MODULE=${APP_MODULE_DEFAULT}

# Gunicorn 并发配置
WORKERS=2
TIMEOUT=120

# 可选：pip 镜像（需时取消注释）
# PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
EOF

# 3) systemd 单元模板
log "生成 ${SERVICE_NAME}.service.tpl"
cat > "${STAGE_DIR}/${SERVICE_NAME}.service.tpl" <<'EOF'
[Unit]
Description={{SERVICE_NAME}} Python Web Service
After=network.target

[Service]
User={{RUN_USER}}
Group={{RUN_GROUP}}
WorkingDirectory={{APP_DIR}}
EnvironmentFile=-/etc/{{SERVICE_NAME}}.env
ExecStart={{APP_DIR}}/bin/start.sh
Restart=always
RestartSec=3
UMask=0027

[Install]
WantedBy=multi-user.target
EOF

# 4) bin/start.sh
log "生成 bin/start.sh"
mkdir -p "${STAGE_DIR}/bin"
cat > "${STAGE_DIR}/bin/start.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
VENV_DIR="${VENV_DIR:-.venv}"

# 加载 /etc/obm.env
if [[ -f "/etc/${SERVICE_NAME}.env" ]]; then
  # shellcheck disable=SC1090
  source "/etc/${SERVICE_NAME}.env"
fi

cd "$APP_DIR"
exec "${APP_DIR}/${VENV_DIR}/bin/gunicorn" -k uvicorn.workers.UvicornWorker "${APP_MODULE:-backend.app:app}" \
  --bind "0.0.0.0:${PORT:-9090}" --workers "${WORKERS:-2}" --timeout "${TIMEOUT:-120}"
EOF
chmod +x "${STAGE_DIR}/bin/start.sh"

# 5) install.sh
log "生成 install.sh"
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

echo "==> Installing ${SERVICE_NAME} into ${APP_DIR} (user: ${RUN_USER})"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (e.g., sudo $0)"; exit 1
fi

# 基础依赖
need_pkgs=()
command -v "$PYTHON_BIN" >/dev/null 2>&1 || need_pkgs+=("python3")
"$PYTHON_BIN" -m venv --help >/dev/null 2>&1 || need_pkgs+=("python3-venv")

if [[ ${#need_pkgs[@]} -gt 0 ]]; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y "${need_pkgs[@]}"
  elif command -v dnf >/dev/null 2>&1; then
    dnf install -y python3 python3-virtualenv || dnf install -y python3 python3-venv || true
  elif command -v yum >/dev/null 2>&1; then
    yum install -y python3 python3-virtualenv || yum install -y python3 || true
  else
    echo "Install these packages manually: ${need_pkgs[*]}"; exit 1
  fi
fi

# 系统用户/组（此版本默认 root，可按需覆盖）
if ! id -u "$RUN_USER" >/dev/null 2>&1; then
  groupadd -f "$RUN_GROUP"
  useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin --gid "$RUN_GROUP" "$RUN_USER"
fi

# 拷贝应用
mkdir -p "$APP_DIR"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${APP_SRC_DIR}/" "$APP_DIR/"
else
  echo "rsync 不存在，尝试 tar 方式拷贝"
  tmp_tar="$(mktemp -u).tar"
  tar -C "${APP_SRC_DIR}" -cf "$tmp_tar" .
  tar -C "$APP_DIR" -xf "$tmp_tar"
  rm -f "$tmp_tar"
fi
chown -R "$RUN_USER:$RUN_GROUP" "$APP_DIR"
chmod +x "$APP_DIR/bin/start.sh" || true

# venv + 依赖
cd "$APP_DIR"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

ENV_FILE="/etc/${SERVICE_NAME}.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

# 可选镜像
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
  pip config set global.index-url "$PIP_INDEX_URL" || true
fi

pip install -U pip wheel || true
if [[ -f requirements.txt ]]; then
  pip install -r requirements.txt
fi

# /etc/<service>.env
if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$OLDPWD/$ENV_SRC_FILE" ]]; then
    cp "$OLDPWD/$ENV_SRC_FILE" "$ENV_FILE"
  else
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

# 渲染 systemd 单元
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
tpl="$(cat "$OLDPWD/$UNIT_TEMPLATE")"
tpl="${tpl//\{\{SERVICE_NAME\}\}/$SERVICE_NAME}"
tpl="${tpl//\{\{RUN_USER\}\}/$RUN_USER}"
tpl="${tpl//\{\{RUN_GROUP\}\}/$RUN_GROUP}"
tpl="${tpl//\{\{APP_DIR\}\}/$APP_DIR}"
echo "$tpl" > "$UNIT_PATH"

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
sleep 1
systemctl --no-pager --full status "$SERVICE_NAME" || true
echo "==> Installed. Logs: journalctl -u ${SERVICE_NAME} -f"
EOF
chmod +x "${STAGE_DIR}/install.sh"

# 6) upgrade.sh
log "生成 upgrade.sh"
cat > "${STAGE_DIR}/upgrade.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
APP_SRC_DIR="${APP_SRC_DIR:-app}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (e.g., sudo $0)"; exit 1
fi

echo "==> Upgrading ${SERVICE_NAME} in ${APP_DIR}"
systemctl stop "${SERVICE_NAME}" || true

ts=$(date +%Y%m%d-%H%M%S)
mkdir -p "${APP_DIR}/releases"
tar -C "${APP_DIR}" -czf "${APP_DIR}/releases/app-${ts}.tar.gz" .

if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude ".venv" "${APP_SRC_DIR}/" "${APP_DIR}/"
else
  echo "rsync 不存在，尝试 tar 方式拷贝"
  tmp_tar="$(mktemp -u).tar"
  tar -C "${APP_SRC_DIR}" -cf "$tmp_tar" .
  tar -C "${APP_DIR}" -xf "$tmp_tar"
  rm -f "$tmp_tar"
fi

if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  source "${APP_DIR}/.venv/bin/activate"
  pip install -r "${APP_DIR}/requirements.txt"
fi

systemctl start "${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
echo "==> Upgrade done. Logs: journalctl -u ${SERVICE_NAME} -f"
EOF
chmod +x "${STAGE_DIR}/upgrade.sh"

# 7) uninstall.sh
log "生成 uninstall.sh"
cat > "${STAGE_DIR}/uninstall.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-obm}"
APP_DIR="${APP_DIR:-/opt/obm}"
RUN_USER="${RUN_USER:-root}"
RUN_GROUP="${RUN_GROUP:-root}"

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (e.g., sudo $0)"; exit 1
fi

read -r -p "Stop and disable service ${SERVICE_NAME}? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  systemctl stop "${SERVICE_NAME}" || true
  systemctl disable "${SERVICE_NAME}" || true
  rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
  systemctl daemon-reload
fi

read -r -p "Remove /etc/${SERVICE_NAME}.env ? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  rm -f "/etc/${SERVICE_NAME}.env"
fi

read -r -p "Remove app dir ${APP_DIR}? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  rm -rf "${APP_DIR}"
fi

read -r -p "Delete user/group ${RUN_USER}/${RUN_GROUP}? [y/N] " yn
if [[ "${yn,,}" == "y" ]]; then
  userdel -r "${RUN_USER}" 2>/dev/null || true
  groupdel "${RUN_GROUP}" 2>/dev/null || true
fi

echo "==> Uninstalled."
EOF
chmod +x "${STAGE_DIR}/uninstall.sh"

# 8) README
log "生成 README.txt"
cat > "${STAGE_DIR}/README.txt" <<EOF
OBM Installer (systemd) — v${VERSION}

默认：
- 安装目录：/opt/obm
- 服务名：obm（开机自启）
- 端口：9090
- 运行用户：root
- APP 模块（自动检测）：${APP_MODULE_DEFAULT}

快速安装：
  sudo ./install.sh

日志：
  journalctl -u obm -f

升级（替换 app/ 为新代码后执行）：
  sudo ./upgrade.sh

卸载：
  sudo ./uninstall.sh
EOF

# 9) 打包
log "打包 ${OUT_TGZ}"
tar -C "$BUILD_DIR" -czf "$OUT_TGZ" "$(basename "$STAGE_DIR")"

log "完成：${OUT_TGZ}"
