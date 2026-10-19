# -*- coding: utf-8 -*-
"""打包环境预检：按 requirements-build.txt 核对版本，缺了直接给安装命令。

跑法： python tools/buildenvcheck.py
"""
import importlib
import importlib.metadata as md
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQ = os.path.join(ROOT, "requirements-build.txt")
MODULE = {"pyinstaller": "PyInstaller", "pillow": "PIL", "numpy": "numpy"}


def main():
    if not os.path.isfile(REQ):
        print("找不到 requirements-build.txt")
        return 1
    bad = []
    for line in io.open(REQ, encoding="utf-8").read().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            continue
        pkg, want = line.split("==", 1)
        pkg, want = pkg.strip(), want.strip()
        mod = MODULE.get(pkg, pkg)
        try:
            importlib.import_module(mod)
            have = md.version(pkg)
        except Exception:
            bad.append("%s 未安装（需要 %s）" % (pkg, want))
            continue
        if have != want:
            bad.append("%s 版本 %s，需要 %s" % (pkg, have, want))
        else:
            print("  PASS %-12s %s" % (pkg, have))
    if bad:
        print()
        for b in bad:
            print("  FAIL " + b)
        print()
        print("修复：%s -m pip install -r requirements-build.txt" % sys.executable)
        return 1
    print(">>> 打包环境就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
