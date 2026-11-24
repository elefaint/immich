#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Immich Web 地图定制补丁工具。

用法（在 Immich 的 www 目录上就地打补丁）：

    python3 apply.py status  /volume1/@appstore/immich/share/immich/www
    python3 apply.py apply   /volume1/@appstore/immich/share/immich/www
    python3 apply.py restore /volume1/@appstore/immich/share/immich/www
    python3 apply.py bump-version <www> v20261124_181000
    python3 apply.py clean-precompressed <www>

apply 会：
  1. 备份原产物为 <file>.wbcn-orig（只备份一次，restore 用）
  2. 按内容定位 chunk（文件名带 hash，换版本会变）
  3. 逐条替换并做 node --check 语法校验
  4. 安装 assets/*.json 到 www/
  5. 重写 index.html 里的默认视野 / hash 兜底脚本（内容来自 assets/map-default.json）

打完补丁还需要（工具不代劳，避免误重启线上服务）：
    find <www>/_app/immutable \\( -name '*.br' -o -name '*.gz' \\) -delete
    synopkg restart immich
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from patchset import MAP_PATCHES, OPTIONAL_PATCHES, TIMELINE_PATCHES, Patch  # noqa: E402

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

# 判定 chunk 身份的代码特征（未打补丁 / 已打补丁 各认一种）
MAP_SIGNATURES = ("cluster:{radius:35,maxZoom:18}", "cluster:{radius:80,")
TL_SIGNATURES = (
    "get viewId(){let{year:e,month:t}=this.yearMonth;return e+`-`+t}",
    "get viewId(){let{year:e,month:t}=this.yearMonth;return (this.__wbGen",
)

BOOT_RE = re.compile(r"<!-- wbcn:map-default -->.*?<!-- /wbcn:map-default -->", re.S)
HASH_RE = re.compile(r"<!-- wbcn:hash-strip -->.*?<!-- /wbcn:hash-strip -->", re.S)
LEGACY_BOOT_RE = re.compile(
    r"<script>\(function\(\)\{var D=.*?window\.__wbMapDefault=D.*?</script>", re.S
)
LEGACY_HASH_RE = re.compile(
    r"<script>\(function\(\)\{try\{var p=location\.pathname.*?history\.replaceState.*?</script>",
    re.S,
)
VERSION_RE = re.compile(r"(__wbv__|__wb_ver__)=v\d{8}_\d{6}")


# --------------------------------------------------------------- 基础工具
def chunk_dir(www: Path) -> Path:
    return www / "_app" / "immutable" / "chunks"


def js_chunks(www: Path) -> list[Path]:
    return sorted(
        p
        for p in chunk_dir(www).glob("*.js")
        if not any(p.name.endswith(s) for s in (".bak", "-orig"))
        and ".bak" not in p.name
        and ".wbcn" not in p.name
    )


def resolve_targets(www: Path) -> dict[str, Path]:
    """按代码特征找到 地图 chunk 和 timeline chunk，不依赖 hash 文件名。"""
    found: dict[str, Path] = {}
    for p in js_chunks(www):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "map" not in found and any(s in text for s in MAP_SIGNATURES):
            found["map"] = p
        if "timeline" not in found and any(s in text for s in TL_SIGNATURES):
            found["timeline"] = p
        if len(found) == 2:
            break
    return found


def syntax_ok(text: str) -> tuple[bool, str]:
    """用 node --check 校验；无 node 时跳过（返回 True, 'skipped'）。"""
    node = shutil.which("node")
    if not node:
        return True, "node not found, syntax check skipped"
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False, encoding="utf-8") as f:
        f.write(text)
        tmp = f.name
    try:
        r = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
        return r.returncode == 0, (r.stderr or "").strip()[:400]
    finally:
        Path(tmp).unlink(missing_ok=True)


def backup_once(path: Path) -> Path:
    bak = path.with_name(path.name + ".wbcn-orig")
    if not bak.exists():
        shutil.copy2(path, bak)
    return bak


# --------------------------------------------------------------- 补丁执行
def all_patches(with_optional: bool = False) -> list[tuple[str, Patch]]:
    items = [("map", p) for p in MAP_PATCHES] + [("timeline", p) for p in TIMELINE_PATCHES]
    if with_optional:
        items += [("map", p) for p in OPTIONAL_PATCHES]
    return items


def optional_names() -> set[str]:
    return {p.id for p in OPTIONAL_PATCHES}


def do_status(www: Path) -> int:
    targets = resolve_targets(www)
    if not targets:
        print("!! 在 %s 下没找到地图/timeline chunk" % chunk_dir(www))
        return 2
    for key, path in targets.items():
        print("%-9s %s" % (key, path.name))
    pending = 0
    for key, patch in all_patches():
        path = targets.get(key)
        if path is None:
            print("  %-20s ?? 找不到对应 chunk" % patch.id)
            pending += 1
            continue
        text = path.read_text(encoding="utf-8")
        state = "APPLIED" if patch.applied(text) else ("PARTIAL" if patch.partial(text) else "PENDING")
        if state != "APPLIED":
            pending += 1
        print("  %-20s %-8s %s" % (patch.id, state, patch.title))
    index = www / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        boot = "APPLIED" if BOOT_RE.search(html) else "PENDING"
        strip = "APPLIED" if HASH_RE.search(html) else "PENDING"
        print("  %-20s %-8s 默认视野启动脚本" % ("index.boot", boot))
        print("  %-20s %-8s 全球级 hash 抹除" % ("index.hash_strip", strip))
        if "PENDING" in (boot, strip):
            pending += 1
    for patch in OPTIONAL_PATCHES:
        path = targets.get("map")
        state = "APPLIED" if path and patch.applied(path.read_text(encoding="utf-8")) else "OPT-OFF"
        print("  %-20s %-8s %s" % (patch.id, state, patch.title))
    print("\n待处理项：%d" % pending)
    return 0 if pending == 0 else 1


def do_apply(www: Path, dry_run: bool, with_baidu: bool = False) -> int:
    targets = resolve_targets(www)
    if len(targets) != 2:
        print("!! 定位失败：%s" % {k: str(v) for k, v in targets.items()})
        return 2

    changed_files: list[Path] = []
    for key, patch in all_patches(with_baidu):
        path = targets[key]
        text = path.read_text(encoding="utf-8")
        if patch.applied(text):
            print("SKIP   %-20s 已是最新" % patch.id)
            continue
        if patch.partial(text):
            print("WARN   %-20s 检测到部分特征，可能与上游版本不符，跳过" % patch.id)
            continue
        # 全部锚点必须先命中，避免打一半留下半成品
        missing = [old for old, _ in patch.edits if text.count(old) != 1]
        if missing:
            print("FAIL   %-20s 锚点命中异常：%s" % (patch.id, [m[:60] for m in missing]))
            return 1
        for old, new in patch.edits:
            text = text.replace(old, new, 1)
        ok, err = syntax_ok(text)
        if not ok:
            print("FAIL   %-20s 语法校验失败：%s" % (patch.id, err))
            return 1
        print("APPLY  %-20s %s" % (patch.id, patch.title))
        if not dry_run:
            backup_once(path)
            path.write_text(text, encoding="utf-8", newline="\n")
            changed_files.append(path)

    # --- 资源文件 ---
    for name in ("amap-style.json", "baidu-style.json"):
        src, dst = ASSETS / name, www / name
        data = src.read_text(encoding="utf-8")
        if dst.exists() and dst.read_text(encoding="utf-8", errors="replace").strip() == data.strip():
            print("SKIP   %-20s 已存在且一致" % ("asset:" + name))
        else:
            print("APPLY  %-20s -> www/%s" % ("asset:" + name, name))
            if not dry_run:
                dst.write_text(data, encoding="utf-8", newline="\n")

    cfg = json.loads((ASSETS / "map-default.json").read_text(encoding="utf-8"))
    dst = www / "map-default.json"
    data = json.dumps(cfg, ensure_ascii=False, indent=2) + "\n"
    if dst.exists() and dst.read_text(encoding="utf-8-sig") == data:
        print("SKIP   %-20s 已存在且一致" % "asset:map-default.json")
    else:
        print("APPLY  %-20s -> www/map-default.json" % "asset:map-default.json")
        if not dry_run:
            dst.write_text(data, encoding="utf-8", newline="\n")

    # --- index.html ---
    index = www / "index.html"
    if index.exists():
        html = index.read_text(encoding="utf-8")
        new_html = patch_index(html, cfg)
        if new_html == html:
            print("SKIP   %-20s 已是最新" % "index.boot/hash_strip")
        else:
            print("APPLY  %-20s 默认视野 + hash 兜底" % "index.boot/hash_strip")
            if not dry_run:
                backup_once(index)
                index.write_text(new_html, encoding="utf-8")
    else:
        print("WARN   index.html 不存在")

    if dry_run:
        print("\n--dry-run：以上改动均未写入")
    elif changed_files:
        print("\n改动文件：")
        for p in changed_files:
            print("  " + str(p))
    print("\n下一步：删预压缩 + 重启")
    print("  find %s/\\( -name '*.br' -o -name '*.gz' \\) -delete" % (www / "_app" / "immutable"))
    print("  synopkg restart immich")
    return 0


def patch_index(html: str, cfg: dict) -> str:
    """重写 index.html 头部的默认视野脚本与 hash 兜底脚本（可重复执行）。"""
    boot_cfg = {k: v for k, v in cfg.items() if not k.startswith("_")}
    boot = (
        "<script>(function(){var D="
        + json.dumps(boot_cfg, ensure_ascii=False, separators=(",", ":"))
        + ";window.__wbMapDefault=D;"
        'try{fetch("/map-default.json",{cache:"no-store"})'
        ".then(function(r){return r.ok?r.json():null})"
        '.then(function(j){if(j&&typeof j==="object"){window.__wbMapDefault=j}})'
        ".catch(function(){})}catch(e){}})();</script>"
    )
    strip = (
        "<script>(function(){try{var p=location.pathname,s=location.search,"
        'h=location.hash,m=/#([0-9]+(?:\\.[0-9]+)?)\\//.exec(h||"");'
        'if(m&&/\\/map\\/?$/.test(p)){var th=(window.__wbMapDefault&&window.__wbMapDefault.zoomReplaceBelow)||5;'
        'if(+m[1]<th){history.replaceState(null,"",p+s)}}}catch(e){}})();</script>'
    )
    boot_block = "<!-- wbcn:map-default -->" + boot + "<!-- /wbcn:map-default -->"
    strip_block = "<!-- wbcn:hash-strip -->" + strip + "<!-- /wbcn:hash-strip -->"

    html = BOOT_RE.sub("", html)
    html = HASH_RE.sub("", html)
    html = LEGACY_BOOT_RE.sub("", html)
    html = LEGACY_HASH_RE.sub("", html)

    idx = html.find("<head>")
    if idx < 0:
        raise SystemExit("index.html 里没有 <head>")
    pos = idx + len("<head>")
    # 把 <head> 后面的空白全部归一化，保证反复 apply 得到完全相同的字节
    tail = re.sub(r"^[ \t\r\n]*", "", html[pos:])
    return html[:pos] + "\n" + boot_block + "\n" + strip_block + "\n" + tail


def do_restore(www: Path) -> int:
    n = 0
    candidates = list((www / "_app" / "immutable" / "chunks").glob("*.js.wbcn-orig"))
    if (www / "index.html.wbcn-orig").exists():
        candidates.append(www / "index.html.wbcn-orig")
    for bak in candidates:
        target = bak.with_name(bak.name[: -len(".wbcn-orig")])
        shutil.copy2(bak, target)
        print("RESTORE %s" % target.name)
        n += 1
    if not n:
        print("没有找到 .wbcn-orig 备份")
        return 1
    print("\n已还原 %d 个文件，记得删预压缩并重启。" % n)
    return 0


def do_bump(www: Path, version: str) -> int:
    if not re.fullmatch(r"v\d{8}_\d{6}", version):
        print("版本号格式应为 vYYYYMMDD_HHMMSS，例如 v20261124_181000")
        return 2
    targets = [www / "index.html"] + [
        p for p in (www / "_app").rglob("*.js") if ".bak" not in p.name and ".wbcn" not in p.name
    ]
    hits = 0
    for p in targets:
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        new, n = VERSION_RE.subn(lambda m: "%s=%s" % (m.group(1), version), text)
        if n:
            p.write_text(new, encoding="utf-8")
            hits += n
            print("%-64s %d 处" % (p.name, n))
    print("共替换 %d 处 -> %s" % (hits, version))
    return 0


def do_clean(www: Path) -> int:
    root = www / "_app" / "immutable"
    files = [p for p in root.rglob("*") if p.suffix in (".br", ".gz")]
    for p in files:
        p.unlink()
    print("删除预压缩文件 %d 个（旧 .br/.gz 会让浏览器拿到旧 chunk）" % len(files))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Immich 地图定制补丁工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "apply", "restore"):
        sp = sub.add_parser(name)
        sp.add_argument("www", type=Path)
        if name == "apply":
            sp.add_argument("--dry-run", action="store_true")
            sp.add_argument("--with-baidu", action="store_true", help="同时启用百度底图支持")
    sp = sub.add_parser("bump-version")
    sp.add_argument("www", type=Path)
    sp.add_argument("version")
    sp = sub.add_parser("clean-precompressed")
    sp.add_argument("www", type=Path)

    a = ap.parse_args()
    www: Path = a.www
    if not www.is_dir():
        print("目录不存在：%s" % www)
        return 2
    if a.cmd == "status":
        return do_status(www)
    if a.cmd == "apply":
        return do_apply(www, a.dry_run, getattr(a, "with_baidu", False))
    if a.cmd == "restore":
        return do_restore(www)
    if a.cmd == "bump-version":
        return do_bump(www, a.version)
    if a.cmd == "clean-precompressed":
        return do_clean(www)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
