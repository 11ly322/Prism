# -*- coding: utf-8 -*-
"""外观回归截图：每次发版自动截一张主界面，存到 design/after/。

跑法： python tools/uishot.py
用途：让排版问题在 diff 里能被看见，而不是等用户发现。
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


def sample_image():
    """优先用 bench 的真实大图；没有就现造一张渐变图。"""
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


def main():
    os.makedirs(OUT, exist_ok=True)
    mod = importlib.machinery.SourceFileLoader("uishot", APP).load_module()
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
    # 必须先置顶：ImageGrab 抓的是屏幕像素，窗口被浏览器挡住就会截错东西
    try:
        app.lift()
        app.attributes("-topmost", True)
        app.focus_force()
    except Exception:
        pass
    for _ in range(20):
        app.update(); time.sleep(0.02)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    try:
        app.attributes("-topmost", False)
    except Exception:
        pass
    # ---- 像素比对：与基线比较，超过阈值就提示（防止排版被悄悄改坏）----
    base_path = os.path.join(ROOT, "design", "baseline", "main.png")
    os.makedirs(os.path.dirname(base_path), exist_ok=True)
    diff_ratio = None
    if os.path.exists(base_path):
        try:
            base = Image.open(base_path).convert("RGB")
            cur = shot.convert("RGB")
            if base.size == cur.size:
                import numpy as np
                a = np.asarray(base, dtype=np.int16)
                b = np.asarray(cur, dtype=np.int16)
                # 任一通道差异 > 8 才算变了：抗锯齿与字体渲染抖动不算
                changed = (np.abs(a - b).max(axis=2) > 8)
                diff_ratio = float(changed.mean())
            else:
                print("   !! 基线尺寸 %s 与当前 %s 不同" % (base.size, cur.size))
                diff_ratio = 1.0
        except Exception as exc:
            print("   基线比对失败：%s" % exc)
    else:
        shot.save(base_path)
        print("   已建立外观基线 -> %s" % base_path)

    path = os.path.join(OUT, "main.png")
    shot.save(path)
    print("   外观截图 -> %s (%dx%d)" % (path, w, h))
    if diff_ratio is not None:
        print("   与基线差异 %.2f%%%s" % (
            diff_ratio * 100.0,
            "   << 超过 2%%，请确认排版改动是否符合预期"
            if diff_ratio > 0.02 else ""))
    app.on_close()
    if os.path.exists(settings):
        os.remove(settings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
