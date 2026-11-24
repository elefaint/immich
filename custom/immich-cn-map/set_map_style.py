#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把地图样式写进 Immich 的 system-config（map.lightStyle / map.darkStyle）。

Immich 的地图样式是运行时配置，不在前端产物里，所以换底图不需要重新打包。
样式值可以是 data: URL（自包含，推荐）或前端可访问的相对路径（如 /amap-style.json）。

    python3 set_map_style.py --base-url http://127.0.0.1:2283 --api-key <KEY>
    python3 set_map_style.py ... --style assets/baidu-style.json --as-url /baidu-style.json
    python3 set_map_style.py ... --show          # 只打印当前配置

API key 在 Immich「账户设置 -> API 密钥」里创建，需要 system config 权限。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def call(url: str, key: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"x-api-key": key, "Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body) if body.strip() else {}


def style_value(path: Path, as_url: str | None) -> str:
    if as_url:
        return as_url
    obj = json.loads(path.read_text(encoding="utf-8"))
    compact = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return "data:application/json;charset=utf-8," + urllib.parse.quote(compact, safe="")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:2283")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--style", default=str(HERE / "assets" / "amap-style.json"))
    ap.add_argument("--dark", default="same", help="same | <path> | <url>")
    ap.add_argument("--as-url", default=None, help="写相对路径而不是 data: URL")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()

    url = a.base_url.rstrip("/") + "/api/system-config"
    cfg = call(url, a.api_key)
    if a.show:
        print(json.dumps(cfg.get("map", {}), ensure_ascii=False, indent=2)[:1200])
        return 0

    light = style_value(Path(a.style), a.as_url)
    if a.dark == "same":
        dark = light
    elif str(a.dark).startswith(("http", "data:", "/")):
        dark = a.dark
    else:
        dark = style_value(Path(a.dark), a.as_url)

    backup = Path.cwd() / "system-config-before-map-style.json"
    backup.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("原配置已备份 -> %s" % backup)

    cfg.setdefault("map", {})
    cfg["map"]["lightStyle"] = light
    cfg["map"]["darkStyle"] = dark
    call(url, a.api_key, "PUT", cfg)

    after = call(url, a.api_key).get("map", {})
    ok = after.get("lightStyle") == light and after.get("darkStyle") == dark
    print("lightStyle len=%d darkStyle len=%d -> %s" % (len(light), len(dark), "OK" if ok else "MISMATCH"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
