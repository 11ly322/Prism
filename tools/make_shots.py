# -*- coding: utf-8 -*-
"""用 Prism 自己的渲染管线生成网页用的效果图（真实照片，不是色块示意）。

跑法：python tools/make_shots.py <源图>
输出到 docs/shots/shot-{original,graded,mono,frame}.jpg
"""
import importlib.machinery
import importlib.util
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
OUT = os.path.join(ROOT, "docs", "shots")
SIZE = (1000, 625)


def load_plugin(name, app):
    path = os.path.join(ROOT, "plugins", name + ".py")
    spec = importlib.util.spec_from_file_location("shot_plugin_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    defaults = {}
    for p in getattr(mod, "PARAMS", []) or []:
        defaults[p["key"]] = p.get("default")
    return mod, defaults


def main():
    if len(sys.argv) < 2:
        print("用法：python tools/make_shots.py <源图>")
        return 2
    src = sys.argv[1]
    os.makedirs(OUT, exist_ok=True)
    im = Image.open(src).convert("RGB")
    # 居中裁切到 8:5
    tw, th = SIZE
    r = max(tw / im.width, th / im.height)
    im = im.resize((int(im.width * r + 0.5), int(im.height * r + 0.5)),
                   Image.LANCZOS)
    left = (im.width - tw) // 2
    top = (im.height - th) // 2
    im = im.crop((left, top, left + tw, top + th))

    im.save(os.path.join(OUT, "shot-original.webp"), quality=76, method=6)

    mod = importlib.machinery.SourceFileLoader("shotapp", APP).load_module()
    app = mod.QPEApp()          # 只是拿它的渲染管线，窗口稍后销毁
    app.update()
    adj = app._default_adj()
    adj.update({
        "exposure": 0.18, "contrast": 14.0, "highlights": -18.0,
        "shadows": 22.0, "vibrance": 18.0, "saturation": 4.0,
        "temperature": 6.0, "clarity": 10.0,
        "vignette": 22.0,
    })
    app.adj = adj
    graded = app._apply_adjust(im, fast=False, detail=True)
    graded.save(os.path.join(OUT, "shot-graded.webp"), quality=76, method=6)

    mono_mod, mono_p = load_plugin("黑白", app)
    mono = mono_mod.run(im.copy(), **mono_p)
    mono.convert("RGB").save(os.path.join(OUT, "shot-mono.webp"), quality=76, method=6)

    frame_mod, frame_p = load_plugin("白边框", app)
    framed = frame_mod.run(im.copy(), **frame_p)
    framed.convert("RGB").save(os.path.join(OUT, "shot-frame.webp"), quality=76, method=6)

    app.destroy()
    for n in ("shot-original", "shot-graded", "shot-mono", "shot-frame"):
        p = os.path.join(OUT, n + ".jpg")
        print("   %-16s %5.0f KB" % (n + ".webp", os.path.getsize(p) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
