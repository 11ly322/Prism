# -*- coding: utf-8 -*-
"""按语言重拍网页截图：看图窗口（viewer）+ 插件窗口（plugins）。

网页中文页用 1100 宽，en/ja 页用 900 宽（看图窗口三语都用 1100 宽）；
窗口内容随语言变化，所以每种语言分开拍。之前漏了 viewer 的 en/ja 两张，
英文/日文页引用 ui-viewer-en.webp 直接 404，这次一并补上。

跑法： python tools/shots_lang.py
"""
import importlib.machinery
import os
import time

from PIL import Image, ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
SAMPLE = os.path.join(ROOT, "design", "sample.jpg")
DESIGN = os.path.join(ROOT, "design", "after")
OUT = os.path.join(ROOT, "docs", "shots")
VIEWER = {"zh": "ui-viewer.webp", "en": "ui-viewer-en.webp",
          "ja": "ui-viewer-ja.webp"}
PLUGINS = {"zh": (1100, "ui-plugins.webp"),
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


def save_webp(shot, path, width, quality=82):
    if shot.width != width:
        shot = shot.resize((width, round(shot.height * width / shot.width)),
                           Image.Resampling.LANCZOS)
    shot.convert("RGB").save(path, "WEBP", quality=quality, method=6)
    return shot.size


def main():
    mod = importlib.machinery.SourceFileLoader("shots", APP).load_module()
    mod._plugin_dir = lambda: os.path.join(ROOT, "plugins")
    settings = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(settings):
        os.remove(settings)
    app = mod.QPEApp()
    app.geometry("1280x820+80+60")
    for _ in range(50):
        app.update(); time.sleep(0.004)
    app.open_files([SAMPLE])
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 20:
        app.update()
        if getattr(app, "surface_img", None) is not None:
            break
        time.sleep(0.01)

    for lang in ("zh", "en", "ja"):
        app.lang = lang
        mod.APP_LANG = lang
        app._build_bar()
        app._apply_lang()
        app._update_title()
        app.toggle_panel(False)
        for _ in range(45):
            app.update(); time.sleep(0.01)
        shot = grab(app, app)
        design_path = os.path.join(DESIGN, "viewer-%s.png" % lang)
        shot.save(design_path)
        w, h = save_webp(shot, os.path.join(OUT, VIEWER[lang]), 1100)
        print("  %-3s %-22s %dx%d  %d KB" % (
            lang, VIEWER[lang], w, h,
            os.path.getsize(os.path.join(OUT, VIEWER[lang])) // 1024))

        app.show_plugins()
        for _ in range(40):
            app.update(); time.sleep(0.01)
        pshot = grab(app.plug_win, app)
        width, name = PLUGINS[lang]
        w, h = save_webp(pshot, os.path.join(OUT, name), width)
        print("  %-3s %-22s %dx%d  %d KB" % (
            lang, name, w, h, os.path.getsize(os.path.join(OUT, name)) // 1024))
        app.plug_win.destroy()
        app.plug_win = None
        for _ in range(10):
            app.update(); time.sleep(0.01)

    app.destroy()
    if os.path.exists(settings):
        os.remove(settings)


if __name__ == "__main__":
    main()
