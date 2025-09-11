import os
from pathlib import Path


# App config and paths
APP_SECRET = os.environ.get("APP_SECRET", "change-this-secret")
APP_ENV = os.environ.get("APP_ENV", "v1.0")

# project root (repo root): backend/config.py -> backend -> repo_root
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "app.db"

# Exclude noisy/virtual mounts from Linux storage detail
EXCLUDED_MOUNT_PREFIXES = [
    '/snap/', '/var/snap/', '/var/lib/snapd/', '/run/snapd/',
    '/var/lib/docker/', '/var/lib/containers/', '/var/lib/containerd/',
    '/var/lib/kubelet/', '/var/lib/flatpak/', '/run/user/',
    '/var/lib/lxc/', '/var/lib/lxd/', '/var/lib/libvirt/', '/var/lib/podman/'
]

