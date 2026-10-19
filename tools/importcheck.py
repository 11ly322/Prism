# -*- coding: utf-8 -*-
"""导入与启动冒烟：防止「py_compile 通过、类却没了」的改动混进发版。

跑法： python tools/importcheck.py
"""
import importlib.machinery
import os
import sys
import tempfile
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-32s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    mod = importlib.machinery.SourceFileLoader("ic", APP).load_module()
    ok("模块可导入", True)
    for attr in ("QPEApp", "ImageDoc", "Loader", "APP_VERSION", "PERF_PROFILE",
                 "DRAFT_SLACK", "REDUCE_MAX_K"):
        ok("存在属性 %s" % attr, hasattr(mod, attr))
    ok("版本号格式", isinstance(getattr(mod, "APP_VERSION", ""), str)
       and mod.APP_VERSION.count(".") == 2, getattr(mod, "APP_VERSION", "?"))

    S = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(S):
        os.remove(S)
    app = mod.QPEApp()
    ok("QPEApp 可实例化", True)
    for _ in range(40):
        app.update(); time.sleep(0.004)
    ok("窗口已映射", bool(app.winfo_ismapped()))

    tmp = os.path.join(tempfile.gettempdir(), "_prism_importchk")
    os.makedirs(tmp, exist_ok=True)
    p = os.path.join(tmp, "a.png")
    Image.new("RGB", (640, 480), (120, 140, 160)).save(p)
    app.open_files([p])
    t0 = time.perf_counter()
    got = None
    while time.perf_counter() - t0 < 15:
        app.update()
        if getattr(app, "surface_img", None) is not None:
            got = True
            break
        time.sleep(0.005)
    ok("能打开并出图", bool(got))
    ok("文档已装载", app.doc is not None,
       str(None if app.doc is None else app.doc.img.size))

    app.on_close()
    ok("可正常关闭", True)
    for _ in range(10):
        try:
            app.update()
        except Exception:
            break
    if os.path.exists(S):
        os.remove(S)
    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 导入与启动冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
