# -*- coding: utf-8 -*-
"""插件清单投稿校验（不依赖 Tk，供 CI 的 PR 检查用）。

检查：schema、id 规则、重复 id、内置 id 冲突、URL、SHA-256、三语字段、
docs/plugins/index.json 是否与 plugins/index.json 一致。
"""
import ast
import hashlib
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
FAIL = []


def bad(msg):
    FAIL.append(msg)
    print("  FAIL " + msg)


def load_json(path):
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def builtin_ids():
    ids = set()
    for name in os.listdir(os.path.join(ROOT, "plugins")):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        path = os.path.join(ROOT, "plugins", name)
        try:
            tree = ast.parse(io.open(path, encoding="utf-8").read())
        except Exception:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(t, ast.Name) and t.id == "PLUGIN"
                       for t in node.targets):
                continue
            try:
                meta = ast.literal_eval(node.value)
            except Exception:
                continue
            if isinstance(meta, dict) and meta.get("id"):
                ids.add(str(meta["id"]))
    return ids


def main():
    idx = load_json(os.path.join(ROOT, "plugins", "index.json"))
    if not isinstance(idx, dict) or idx.get("schema") != 1:
        bad("plugins/index.json schema 必须是 1")
        return 1
    entries = idx.get("plugins")
    if not isinstance(entries, list) or not entries:
        bad("plugins/index.json 的 plugins 必须是非空数组")
        return 1
    builtin = builtin_ids()
    seen = set()
    for i, e in enumerate(entries):
        tag = "第 %d 项" % (i + 1)
        if not isinstance(e, dict):
            bad(tag + " 不是对象")
            continue
        eid = str(e.get("id") or "")
        tag = eid or tag
        if not ID_RE.match(eid):
            bad("%s：id 只能用小写字母数字与 -_，且不能以 _ 开头" % tag)
        if eid in seen:
            bad("%s：id 重复" % tag)
        seen.add(eid)
        if eid in builtin:
            bad("%s：id 与内置插件冲突" % tag)
        try:
            if int(e.get("api")) != 2:
                bad("%s：api 必须是 2" % tag)
        except Exception:
            bad("%s：api 必须是 2" % tag)
        for key in ("name", "description"):
            val = e.get(key)
            if isinstance(val, dict):
                if not str(val.get("zh") or "").strip():
                    bad("%s：%s.zh 不能为空" % (tag, key))
            elif not str(val or "").strip():
                bad("%s：%s 不能为空" % (tag, key))
        for key in ("network", "writes_files"):
            if not isinstance(e.get(key), bool):
                bad("%s：%s 必须是 true/false" % (tag, key))
        url = str(e.get("url") or "")
        if not url.startswith(("https://", "http://")):
            bad("%s：url 必须是 http(s) 直链" % tag)
        sha = str(e.get("sha256") or "").lower()
        if not SHA_RE.match(sha):
            bad("%s：sha256 必须是 64 位十六进制" % tag)
        src = str(e.get("source") or "")
        path = os.path.join(ROOT, src)
        if not src or not os.path.isfile(path):
            bad("%s：source 文件不存在：%s" % (tag, src))
            continue
        actual = hashlib.sha256(open(path, "rb").read()).hexdigest()
        if actual != sha:
            bad("%s：sha256 与 source 不一致（%s != %s）"
                % (tag, sha[:12], actual[:12]))

    docs_idx = os.path.join(ROOT, "docs", "plugins", "index.json")
    if not os.path.isfile(docs_idx):
        bad("docs/plugins/index.json 不存在")
    elif open(docs_idx, "rb").read() != open(
            os.path.join(ROOT, "plugins", "index.json"), "rb").read():
        bad("docs/plugins/index.json 与 plugins/index.json 不一致")

    print()
    if FAIL:
        print(">>> 插件清单校验失败 %d 项" % len(FAIL))
        return 1
    print(">>> 插件清单校验通过（%d 个）" % len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
