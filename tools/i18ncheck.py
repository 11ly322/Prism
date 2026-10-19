# -*- coding: utf-8 -*-
"""词条覆盖率自检：扫描页面文本，报告哪些中文串还没进词典。

跑法：python tools/i18ncheck.py
退出码 0 表示两种语言都覆盖；1 表示有缺失（缺失项会打印）。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "docs", "index.html")
I18N = os.path.join(ROOT, "docs", "i18n.js")

# 这些不像文案，可以豁免
SKIP_PAT = (
    re.compile(r"^[\d\s.%MBKB/·:：+\-−]+$"),
    re.compile(r"^[A-Za-z0-9 _./\\:&+=()\[\]{}<>\"'%#@!?,;*|-]+$"),   # 纯 ASCII
    re.compile(r"^Prism[-.\w]*$"),
    re.compile(r"^(Windows|macOS|Linux|README\.md|plugins/|/opt/|/usr/share)"),
)


def load_dict():
    s = io.open(I18N, encoding="utf-8").read()
    m = re.search(r"window\.PRISM_I18N = (\{.*?\});\s*\nwindow\.PRISM_LANGS", s, re.S)
    return json.loads(m.group(1))


def norm(t):
    return re.sub(r"\d+\.\d+\.\d+", "{v}", t)


def page_texts():
    s = io.open(PAGE, encoding="utf-8").read()
    body = re.sub(r"<style.*?</style>", "", s, flags=re.S)
    body = re.sub(r"<script.*?</script>", "", body, flags=re.S)
    out, seen = [], set()
    for t in re.findall(r">([^<>]+)<", body):
        t = t.strip()
        if not t or len(t) < 2 or t in seen:
            continue
        if any(p.match(t) for p in SKIP_PAT):
            continue
        seen.add(t)
        out.append(t)
    return out


def main():
    data = load_dict()
    texts = page_texts()
    fail = False
    for lang in ("en", "ja"):
        d = data.get(lang, {})
        missing = [t for t in texts if t not in d and norm(t) not in d]
        pct = (len(texts) - len(missing)) * 100.0 / max(1, len(texts))
        print("  %s: %d/%d 覆盖（%.1f%%）" % (lang, len(texts) - len(missing),
                                             len(texts), pct))
        for t in missing[:12]:
            print("     缺: %s" % t[:70])
        if missing:
            fail = True
    print("  结论：%s" % ("有缺失" if fail else "全部覆盖"))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
