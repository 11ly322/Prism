# -*- coding: utf-8 -*-
"""校验仓库里所有版本号是否与 src/Prism.pyw 的 APP_VERSION 一致。

用法：python check_versions.py
发现问题时以非零码退出，可直接挂在发版脚本后面。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
PAT = re.compile(r"\b9\.\d+\.\d+\b")
SKIP_DIRS = {".git", "_build", "_build2", "_viewer_build", "_mac_stage",
             "_lin_stage", "__pycache__", "_internal", "shots", "design",
             "tools"}
# 这些行是在讲历史，不是当前版本号
SKIP_LINE_HINTS = ("已于", "历史", "之前", "8.3.2 /", "round",
                   "（9.", "(9.", "从 9.", "since 9.", "Since 9.", "9.4.0 起")


def app_version():
    with io.open(os.path.join(ROOT, "src", "Prism.pyw"), encoding="utf-8") as fh:
        m = re.search(r'APP_VERSION = "([^"]+)"', fh.read())
    return m.group(1)


def main():
    ver = app_version()
    print("基准版本（src/Prism.pyw）= %s" % ver)
    bad = {}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith((".py", ".pyw", ".md", ".html", ".txt", ".ps1")):
                continue
            # 变更记录里本来就会提到历史版本号，不算不一致
            if fn.startswith("CHANGELOG"):
                continue
            fp = os.path.join(base, fn)
            rel = os.path.relpath(fp, ROOT)
            if rel == os.path.join("src", "Prism.pyw") or fn == "check_versions.py":
                continue
            try:
                text = io.open(fp, encoding="utf-8").read()
            except Exception:
                continue
            for line in text.splitlines():
                if line.lstrip().startswith("#"):
                    continue          # 注释里的历史分节号不算当前版本
                if any(h in line for h in SKIP_LINE_HINTS):
                    continue
                for m in PAT.finditer(line):
                    found = m.group(0)
                    if found != ver:
                        bad.setdefault(rel, set()).add(found)
    if bad:
        print("发现版本号不一致：")
        for rel, vers in sorted(bad.items()):
            print("   %-28s %s" % (rel, ", ".join(sorted(vers))))
        return 1
    print("全部一致，未发现旧版本号")
    return 0


if __name__ == "__main__":
    sys.exit(main())
