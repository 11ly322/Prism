# -*- coding: utf-8 -*-
"""从 plugins/index.json + 各插件源码生成 README 索引，并同步到 docs/。

单一数据源：
  plugins/index.json          官方可安装清单（应用内「插件市场」读它）
  plugins/*.py                自带插件（README 的「自带」表由源码元信息生成）
  plugins/README.md           两块表格由本脚本生成，别手改表格内容
  docs/plugins/index.json     发布到网页的副本，应用从 Pages 拉取

跑法：
    python tools/make_plugin_index.py           生成 / 更新
    python tools/make_plugin_index.py --check   只检查是否最新（发布门禁用）
"""
import importlib.util
import io
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_DIR = os.path.join(ROOT, "plugins")
DOCS_PLUGINS = os.path.join(ROOT, "docs", "plugins")
README = os.path.join(PLUGIN_DIR, "README.md")
INDEX = os.path.join(PLUGIN_DIR, "index.json")
DOC_INDEX = os.path.join(DOCS_PLUGINS, "index.json")
BEGIN = "<!-- BEGIN GENERATED %s -->"
END = "<!-- END GENERATED %s -->"

BUILTIN_HEAD = (
    "| id | 名称 / 版本 | 参数（控件 · 范围 · 默认） | 说明 | 联网 | 写文件 | 源码 |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n")
CATALOG_HEAD = (
    "| id | 名称 / 版本 | 参数摘要 | 说明 | SHA-256（前 12 位） | 安装文件 |\n"
    "| --- | --- | --- | --- | --- | --- |\n")


def load_plugin(path):
    spec = importlib.util.spec_from_file_location(
        "idx_" + os.path.splitext(os.path.basename(path))[0], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fmt_num(v):
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def fmt_params(params):
    parts = []
    for p in params or []:
        kind = str(p.get("type", "slider")).lower()
        label = p.get("label", p.get("key", "?"))
        if kind in ("select", "choice", "dropdown"):
            opts = p.get("options") or p.get("choices") or []
            parts.append("select %s（%s）" % (label, " / ".join(map(str, opts))))
        elif kind in ("checkbox", "bool"):
            parts.append("checkbox %s" % label)
        elif kind in ("text", "string"):
            parts.append("text %s" % label)
        else:
            lo = fmt_num(p.get("min", 0))
            hi = fmt_num(p.get("max", 100))
            parts.append("slider %s %s–%s（%s）" % (
                label, lo, hi, fmt_num(p.get("default", p.get("min", 0)))))
    return " · ".join(parts) or "—"


def yes_no(flag):
    return "是" if flag else "否"


def scan_builtin():
    rows, seen = [], set()
    for fn in sorted(os.listdir(PLUGIN_DIR)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(PLUGIN_DIR, fn)
        mod = load_plugin(path)
        meta = getattr(mod, "PLUGIN", None) or {}
        pid = str(meta.get("id") or os.path.splitext(fn)[0])
        if pid in seen:
            raise SystemExit("自带插件 id 重复：%s" % pid)
        seen.add(pid)
        name = str(meta.get("name") or pid)
        ver = str(meta.get("version") or "")
        desc = str(meta.get("description")
                   or getattr(mod, "PLUGIN_DESC", "") or "—")
        rows.append("| %s | %s %s | %s | %s | %s | %s | `%s` |" % (
            pid, name, ver, fmt_params(getattr(mod, "PARAMS", [])), desc,
            yes_no(meta.get("network")), yes_no(meta.get("writes_files")), fn))
    return rows


def validate_catalog(data):
    if not isinstance(data, dict):
        raise SystemExit("index.json 顶层必须是对象")
    if data.get("schema") != 1:
        raise SystemExit("index.json schema 必须是 1")
    entries = data.get("plugins")
    if not isinstance(entries, list) or not entries:
        raise SystemExit("index.json 里没有 plugins")
    seen = set()
    for e in entries:
        if not isinstance(e, dict):
            raise SystemExit("plugins 里每一项都必须是对象")
        pid = str(e.get("id") or "").strip()
        if not pid or pid in seen:
            raise SystemExit("插件 id 缺失或重复：%r" % pid)
        seen.add(pid)
        try:
            api = int(e.get("api", 1))
        except Exception:
            raise SystemExit("%s 的 api 不是数字" % pid)
        if api not in (1, 2):
            raise SystemExit("%s 的 api=%s 不支持" % (pid, api))
        url = str(e.get("url") or "")
        if not url.startswith("https://"):
            raise SystemExit("%s 的 url 必须是 https" % pid)
        sha = str(e.get("sha256") or "").lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise SystemExit("%s 的 sha256 格式不对" % pid)
        for field in ("name", "description"):
            loc = e.get(field)
            if not isinstance(loc, dict):
                raise SystemExit("%s 的 %s 必须是 {zh,en,ja}" % (pid, field))
            for lang in ("zh", "en", "ja"):
                if not str(loc.get(lang) or "").strip():
                    raise SystemExit("%s 的 %s 缺 %s" % (pid, field, lang))
        src = e.get("source")
        if not src:
            raise SystemExit("%s 缺 source（仓库内源码路径）" % pid)
        src_path = os.path.join(ROOT, src)
        if not os.path.isfile(src_path):
            raise SystemExit("%s 的 source 不存在：%s" % (pid, src))
        import hashlib
        got = hashlib.sha256(open(src_path, "rb").read()).hexdigest()
        if got != sha:
            raise SystemExit("%s 的 sha256 与 %s 不一致：%s != %s"
                             % (pid, src, sha, got))
        if os.path.basename(url) != os.path.basename(src):
            raise SystemExit("%s 的 url 文件名与 source 不一致" % pid)
    return entries


def scan_catalog(entries):
    rows = []
    for e in entries:
        mod = load_plugin(os.path.join(ROOT, e["source"]))
        name = str(e["name"].get("zh") or e["id"])
        ver = str(e.get("version") or "")
        rows.append("| %s | %s %s | %s | %s | `%s…` | `%s` |" % (
            e["id"], name, ver, fmt_params(getattr(mod, "PARAMS", [])),
            str(e["description"].get("zh") or "—"), e["sha256"][:12],
            os.path.basename(e["url"])))
    return rows


def replace_block(text, name, rows, head):
    b, e = BEGIN % name, END % name
    if b not in text or e not in text:
        raise SystemExit("README 里缺少标记 %s / %s" % (b, e))
    start = text.index(b) + len(b)
    end = text.index(e)
    block = "\n" + head + "\n".join(rows) + "\n"
    return text[:start] + block + text[end:]


def main():
    check = "--check" in sys.argv
    data = json.load(io.open(INDEX, encoding="utf-8"))
    entries = validate_catalog(data)
    builtin_rows = scan_builtin()
    catalog_rows = scan_catalog(entries)

    src = io.open(README, encoding="utf-8").read()
    out = replace_block(src, "builtin", builtin_rows, BUILTIN_HEAD)
    out = replace_block(out, "catalog", catalog_rows, CATALOG_HEAD)

    changed = []
    if out != src:
        changed.append("plugins/README.md")
    doc_bytes = io.open(INDEX, "rb").read()
    os.makedirs(DOCS_PLUGINS, exist_ok=True)
    old_doc = open(DOC_INDEX, "rb").read() if os.path.exists(DOC_INDEX) else b""
    if doc_bytes != old_doc:
        changed.append("docs/plugins/index.json")

    if check:
        if changed:
            print("索引不是最新：%s" % ", ".join(changed))
            return 1
        print("索引最新：自带 %d 个 / 官方清单 %d 个" % (
            len(builtin_rows), len(catalog_rows)))
        return 0

    if "plugins/README.md" in changed:
        io.open(README, "w", encoding="utf-8", newline="\n").write(out)
    if "docs/plugins/index.json" in changed:
        shutil.copyfile(INDEX, DOC_INDEX)
    print("已生成：自带 %d 个 / 官方清单 %d 个%s" % (
        len(builtin_rows), len(catalog_rows),
        ("（更新 " + ", ".join(changed) + "）") if changed else "（无变化）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
