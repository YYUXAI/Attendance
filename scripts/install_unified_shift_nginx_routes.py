from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


CONFIG_PATH = Path("/etc/nginx/sites-available/ux-assistant")
MARKER = "# UX_ASSISTANT_SHIFT_ROUTES"
ROUTES = """    # UX_ASSISTANT_SHIFT_ROUTES
    location = /shift-healthz {
        proxy_pass http://127.0.0.1:18084/healthz;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location = /shift-app {
        return 302 /shift-app/;
    }

    location ^~ /shift-app/ {
        proxy_pass http://127.0.0.1:18084;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    location ^~ /api/v1/shift-config {
        proxy_pass http://127.0.0.1:18084;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

"""


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("root_required")
    text = CONFIG_PATH.read_text(encoding="utf-8")
    if MARKER in text:
        print({"changed": False, "reason": "already_installed"})
        return 0
    anchor = "    location /api/ {"
    if text.count(anchor) != 1:
        raise RuntimeError("nginx_api_anchor_not_unique")

    backup = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".pre-shift-routes")
    if not backup.exists():
        shutil.copy2(CONFIG_PATH, backup)
    next_text = text.replace(anchor, ROUTES + anchor, 1)
    fd, temp_name = tempfile.mkstemp(prefix=".ux-assistant.", dir=CONFIG_PATH.parent, text=True)
    os.close(fd)
    temp = Path(temp_name)
    try:
        temp.write_text(next_text, encoding="utf-8")
        os.chmod(temp, CONFIG_PATH.stat().st_mode & 0o777)
        os.replace(temp, CONFIG_PATH)
    finally:
        if temp.exists():
            temp.unlink()
    print({"changed": True, "routes_added": 4, "backup_created": backup.exists()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
