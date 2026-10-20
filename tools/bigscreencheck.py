# -*- coding: utf-8 -*-
"""大屏版回归：模式识别、底部大按钮、无快捷键、无面板。"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-32s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    from PIL import Image
    sys.argv = ["bigscreencheck", "--bigscreen"]
    mod = importlib.machinery.SourceFileLoader(
        "big9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    tmp = tempfile.mkdtemp(prefix="prism_big_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    for _ in range(40):
        app.update(); time.sleep(0.01)
    try:
        ok("识别大屏模式", mod.BIGSCREEN is True and mod.VIEWER_ONLY is True)
        ok("面板不构建", app.panel is None)
        ok("工具栏在底部", app.bar.pack_info().get("side") == "bottom",
           str(app.bar.pack_info().get("side")))
        texts = [w.cget("text") for w in app.bar.winfo_children()
                 if isinstance(w, mod.tk.Button)]
        for label in ("打开", "文件夹", "幻灯片", "全屏", "退出"):
            ok("底栏按钮 " + label, label in texts, str(texts[:6]))
        ok("无 F5 快捷键", not app.bind("<F5>"))
        ok("无 Ctrl+O 快捷键", not app.bind("<Control-o>"))

        p = os.path.join(tmp, "a.jpg")
        Image.new("RGB", (800, 600), (90, 120, 160)).save(p)
        app.open_files([p])
        t0 = time.time()
        while time.time() - t0 < 20:
            app.update(); time.sleep(0.01)
            if app.doc is not None:
                break
        ok("大屏能打开图片", app.doc is not None and app.doc.size == (800, 600))
        app.toggle_panel(True)
        ok("大屏没有修图面板", app.panel is None)
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 大屏版回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 大屏版回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
