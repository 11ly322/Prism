# -*- coding: utf-8 -*-
"""三语文档自检：语言切换链接、相对链接、代码块与生成标记。

检查对象：
    plugins/README{,.en,.ja}.md      插件索引（三语）
    docs/plugin-api{,.en,.ja}.md     插件 API 参考（三语）

跑法： python tools/docscheck.py
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETS = [
    ("plugins", ["README.md", "README.en.md", "README.ja.md"]),
    ("docs", ["plugin-api.md", "plugin-api.en.md", "plugin-api.ja.md"]),
]
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-42s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    print("=== 三语文档自检 ===")
    for folder, files in SETS:
        base = os.path.join(ROOT, folder)
        texts = {}
        for fn in files:
            path = os.path.join(base, fn)
            if not os.path.isfile(path):
                ok("%s/%s 存在" % (folder, fn), False, "缺文件")
                continue
            texts[fn] = io.open(path, encoding="utf-8").read()
        ok("%s 三份齐全" % folder, len(texts) == len(files),
           "%d/%d" % (len(texts), len(files)))
        if len(texts) != len(files):
            continue
        for fn, text in texts.items():
            lines = text.splitlines()
            first = next((ln.strip() for ln in lines if ln.strip()), "")
            others = [f for f in files if f != fn]
            missing = [f for f in others if "(%s)" % f not in first]
            ok("%s/%s 语言切换行" % (folder, fn), not missing,
               "缺 " + str(missing) if missing else first[:60])
            fences = text.count("```") + text.count("~~~")
            ok("%s/%s 代码块成对" % (folder, fn), fences % 2 == 0,
               "%d 个围栏" % fences)
            links = re.findall(r"\]\(([^)#]+\.md)(?:#[^)]*)?\)", text)
            broken = []
            for link in links:
                if link.startswith(("http://", "https://")):
                    continue
                target = os.path.normpath(os.path.join(base, link))
                if not os.path.isfile(target):
                    broken.append(link)
            ok("%s/%s 相对文档链接" % (folder, fn), not broken,
               "断链 " + str(broken) if broken else "%d 条" % len(links))
        if folder == "plugins":
            for fn, text in texts.items():
                for block in ("builtin", "catalog"):
                    b = "<!-- BEGIN GENERATED %s -->" % block
                    e = "<!-- END GENERATED %s -->" % block
                    ok("%s/%s 标记 %s" % (folder, fn, block),
                       text.count(b) == 1 and text.count(e) == 1,
                       "%d / %d" % (text.count(b), text.count(e)))
        # 三份文档的章节数量要一致
        heads = {fn: len(re.findall(r"^## ", text, re.M))
                 for fn, text in texts.items()}
        ok("%s 三份章节数一致" % folder, len(set(heads.values())) == 1, str(heads))

    print()
    if FAIL:
        print(">>> 文档自检失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 三语文档自检通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
