# -*- coding: utf-8 -*-
"""按语言重拍插件窗口截图（对齐网页里的三语配图）。

网页中文页用 1100 宽，en/ja 页用 900 宽；窗口内容随语言变化，所以三张分开拍。
跑法： python tools/shots_lang.py
"""
import importlib.machinery
import os
import time

from PIL import Image, ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
OUT = os.path.join(ROOT, "docs", "shots")
SIZES = {"zh": (1100, "ui-plugins.webp"),
         "en": (900, "ui-plugins-en.webp"),
         "ja": (900, "ui-plugins-ja.webp")}


def grab(win, app):
    try:
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
    except Exception:
        pass
    for _ in range(20):
        app.update(); time.sleep(0.02)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass
    return shot


def main():
    mod = importlib.machinery.SourceFileLoader("shots", APP).load_module()
    mod._plugin_dir = lambda: os.path.join(ROOT, "plugins")
    settings = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(settings):
        os.remove(settings)
    app = mod.QPEApp()
    for _ in range(40):
        app.update(); time.sleep(0.01)

    for lang in ("zh", "en", "ja"):
        app.lang = lang
        mod.APP_LANG = lang
        app._build_bar()
        app._apply_lang()
        for _ in range(30):
            app.update(); time.sleep(0.01)
        app.show_plugins()
        for _ in range(40):
            app.update(); time.sleep(0.01)
        shot = grab(app.plug_win, app)
        width, name = SIZES[lang]
        if shot.width != width:
            shot = shot.resize((width, round(shot.height * width / shot.width)),
                               Image.Resampling.LANCZOS)
        path = os.path.join(OUT, name)
        shot.convert("RGB").save(path, "WEBP", quality=82, method=6)
        print("  %-3s %s  %dx%d  %d KB" % (lang, name, shot.width, shot.height,
                                           os.path.getsize(path) // 1024))
        app.plug_win.destroy()
        app.plug_win = None
        for _ in range(10):
            app.update(); time.sleep(0.01)

    app.destroy()
    if os.path.exists(settings):
        os.remove(settings)


if __name__ == "__main__":
    main()
