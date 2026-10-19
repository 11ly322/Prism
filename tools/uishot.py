# -*- coding: utf-8 -*-
"""外观回归截图与像素比对。

跑法：
    python tools/uishot.py                 只比对（首次自动建基线）
    python tools/uishot.py --update-baseline   有意改版后更新基线

为什么需要：截图存着没人看等于没做。这里把主界面/插件/设置三个窗口分别与
基线比较，逐像素判断「任一通道差异 > 8」，给出变化比例，超过 2% 提醒。
"""
import importlib.machinery
import os
import sys
import tempfile
import time

from PIL import Image, ImageDraw, ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
OUT = os.path.join(ROOT, "design", "after")
BASE = os.path.join(ROOT, "design", "baseline")
THRESHOLD = 0.02          # 2% 像素变化即提醒
UPDATE = "--update-baseline" in sys.argv


def sample_image():
    big = os.path.join(tempfile.gettempdir(), "_benchimg", "real40mp.jpg")
    if os.path.exists(big):
        return big
    tmp = os.path.join(tempfile.gettempdir(), "_prism_shot.png")
    im = Image.new("RGB", (1200, 800))
    d = ImageDraw.Draw(im)
    for y in range(800):
        d.line([(0, y), (1200, y)], fill=(30 + y // 8, 60 + y // 12, 110 + y // 10))
    d.ellipse([700, 120, 1060, 480], fill=(240, 200, 120))
    im.save(tmp)
    return tmp


def grab(win, app):
    try:
        win.lift()
        win.attributes("-topmost", True)
        win.focus_force()
    except Exception:
        pass
    for _ in range(18):
        app.update(); time.sleep(0.02)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass
    return shot


def compare(name, shot):
    bp = os.path.join(BASE, name + ".png")
    os.makedirs(BASE, exist_ok=True)
    if UPDATE or not os.path.exists(bp):
        shot.save(bp)
        print("   %-9s 已%s基线" % (name, "更新" if UPDATE else "建立"))
        return None
    try:
        base = Image.open(bp).convert("RGB")
        cur = shot.convert("RGB")
        if base.size != cur.size:
            print("   %-9s !! 尺寸 %s -> %s" % (name, base.size, cur.size))
            return 1.0
        import numpy as np
        a = np.asarray(base, dtype=np.int16)
        b = np.asarray(cur, dtype=np.int16)
        ratio = float((np.abs(a - b).max(axis=2) > 8).mean())
        flag = "   << 超过 2%%，请确认是否符合预期" if ratio > THRESHOLD else ""
        print("   %-9s 与基线差异 %.2f%%%s" % (name, ratio * 100.0, flag))
        return ratio
    except Exception as exc:
        print("   %-9s 比对失败：%s" % (name, exc))
        return None


def main():
    os.makedirs(OUT, exist_ok=True)
    mod = importlib.machinery.SourceFileLoader("uishot", APP).load_module()
    mod._plugin_dir = lambda: os.path.join(ROOT, "plugins")
    settings = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(settings):
        os.remove(settings)
    app = mod.QPEApp()
    app.geometry("1280x820+80+60")
    for _ in range(50):
        app.update(); time.sleep(0.004)
    app.open_files([sample_image()])
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < 20:
        app.update()
        if getattr(app, "surface_img", None) is not None:
            break
        time.sleep(0.01)
    app.toggle_panel(True)
    for _ in range(60):
        app.update(); time.sleep(0.005)

    shots = {}
    shots["main"] = grab(app, app)

    try:
        app.show_plugins()
        for _ in range(40):
            app.update(); time.sleep(0.005)
        shots["plugins"] = grab(app.plug_win, app)
    except Exception as exc:
        print("   插件窗口截图失败：%s" % exc)
    try:
        app.show_settings()
        for _ in range(40):
            app.update(); time.sleep(0.005)
        shots["settings"] = grab(app.set_win, app)
    except Exception as exc:
        print("   设置窗口截图失败：%s" % exc)

    worst = 0.0
    for name, shot in shots.items():
        shot.save(os.path.join(OUT, name + ".png"))
        r = compare(name, shot)
        if r:
            worst = max(worst, r)
    print("   截图输出 -> %s" % OUT)
    app.on_close()
    if os.path.exists(settings):
        os.remove(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
