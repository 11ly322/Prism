# -*- coding: utf-8 -*-
"""插件异步路径回归：点「运行插件」后主线程必须立刻返回、结果窗口必须出现。

跑法： python tools/plugincheck.py
"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    mod = importlib.machinery.SourceFileLoader("pc", APP).load_module()
    tmp = os.path.join(tempfile.gettempdir(), "_prism_plugcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    plugin = os.path.join(tmp, "gray.py")
    open(plugin, "w", encoding="utf-8").write(
        'PLUGIN = {"id": "gray", "name": "灰度", "version": "1", "api": 2,\n'
        '          "author": "test", "description": "回归用"}\n'
        'PARAMS = [{"key": "amount", "label": "强度", "type": "slider",\n'
        '           "min": 0, "max": 100, "default": 50}]\n'
        'def run(img, **params):\n'
        '    return img.convert("L").convert("RGB")\n')
    big = os.path.join(tmp, "big.jpg")
    Image.new("RGB", (4000, 3000), (170, 140, 120)).save(big, quality=80)
    mod._plugin_dir = lambda: tmp
    S = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(S):
        os.remove(S)

    import tkinter as tk
    app = mod.QPEApp()
    for _ in range(25):
        app.update(); time.sleep(0.01)
    app.open_files([big])
    for _ in range(140):
        app.update(); time.sleep(0.01)
        if app.doc is not None:
            break
    ok("打开测试图", app.doc is not None,
       str(None if app.doc is None else app.doc.img.size))

    app._scan_plugins()
    ok("扫描到插件", len(app.plugins) >= 1, "%d 个" % len(app.plugins))
    if not app.plugins:
        app.destroy()
        return 1
    item = app.plugins[0]
    spec = app._plugin_params_spec(item)
    ok("控件类型解析", [p["type"] for p in spec] == ["range"],
       str([p["type"] for p in spec]))

    before = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    t0 = time.perf_counter()
    app.run_plugin(item)
    ret_ms = (time.perf_counter() - t0) * 1000
    ok("主线程立即返回", ret_ms < 80, "%.1f ms" % ret_ms)

    found = None
    for _ in range(600):
        app.update(); time.sleep(0.01)
        tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        if len(tops) > len(before):
            found = (time.perf_counter() - t0) * 1000
            break
    ok("结果窗口出现", found is not None,
       ("%.0f ms" % found) if found else "未出现")
    ok("异步不阻塞界面", ret_ms < (found or 1e9), "返回 %.1f < 窗口 %.0f" % (ret_ms, found or 0))

    app.destroy()
    if os.path.exists(S):
        os.remove(S)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 插件异步路径回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
