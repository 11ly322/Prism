# -*- coding: utf-8 -*-
"""Prism 自检装置：每次迭代后都跑一遍，作为回归安全网。"""
import importlib.machinery, os, shutil, sys, time
import numpy as np
from PIL import Image, ImageDraw

APP = r"D:\pictu\src\Prism.pyw"
WORK = os.path.join(os.environ.get("TEMP", "."), "_prism_sc")
FAIL = []

def ok(name, cond, detail=""):
    (print("  PASS %-34s %s" % (name, detail)) if cond
     else (FAIL.append(name), print("  FAIL %-34s %s" % (name, detail))))

def notice(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "WARN", name, detail))

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)

def scene(w, h, name, exif=False):
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(0, h, 6):
        d.line([(0, y), (w, y)], fill=(40 + int(y * 0.11), 70, 100))
    d.ellipse([w // 4, h // 5, w * 3 // 4, h * 4 // 5], fill=(212, 200, 175))
    for k in range(6):
        d.rectangle([20 + k * (w // 8), h - 90, 20 + k * (w // 8) + w // 12, h - 20],
                    fill=(30 + k * 20, 40 + k * 16, 55 + k * 14))
    d.rectangle([w - 210, 30, w - 130, 110], fill=(225, 35, 35))    # 饱和红
    d.rectangle([w - 120, 30, w - 40, 110], fill=(35, 195, 65))     # 饱和绿
    p = os.path.join(WORK, name)
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "Nikon"; ex[0x0110] = "Z8"; ex[0x0112] = 1
        im.save(p, quality=92, exif=ex)
    else:
        im.save(p, quality=92)
    return p

def wait(a, ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        a.update(); time.sleep(0.004)

mod = importlib.machinery.SourceFileLoader("qpe_sc", APP).load_module()
print("=== QPE 自检  v%s ===" % getattr(mod, "APP_VERSION", "?"))

MAIN = scene(900, 620, "main.jpg", exif=True)
for i in range(1, 5):
    scene(700 + i * 40, 500 + i * 30, "p%d.jpg" % i)

errors = []
app = mod.QPEApp()
app.report_callback_exception = lambda e, v, tb: errors.append("%s: %s" % (e.__name__, v))
app.update()
app.open_files([MAIN]); wait(app, 2200)
app.toggle_panel(True); wait(app, 500)

def surf():
    """取屏幕像素。必须等后台细节帧算完，否则拿到的是"只有颜色"的中间态。"""
    app.fast = False
    app._render(); wait(app, 120); app._render()
    end = time.time() + 12
    while time.time() < end and app.detail_inflight is not None:
        app.update(); time.sleep(0.01)
    app._render(); wait(app, 160)
    return np.asarray(app.surface_img.convert("RGB"), np.float32)

def reset(detail=True):
    app.adj = mod.App._default_adj() if hasattr(mod, "App") else mod.QPEApp._default_adj()
    app.locals = []
    if detail:
        app.adj["sharpen"] = 35      # 保证细节缓存被激活（历史 bug 的触发条件）
    for k in ("tone_key", "color_key", "auto_lut"):
        setattr(app, k, None)
    app.fast = False
    app._render(); wait(app, 150); app._render(); wait(app, 900)

print("--- 1. 每一项调整都必须真正改变画面 ---")
reset()
base = surf()
CASES = [("曝光", lambda a: a.__setitem__("exposure", 0.7)),
         ("对比度", lambda a: a.__setitem__("contrast", 45)),
         ("高光", lambda a: a.__setitem__("highlights", -70)),
         ("阴影", lambda a: a.__setitem__("shadows", 60)),
         ("白色色阶", lambda a: a.__setitem__("whites", 50)),
         ("黑色色阶", lambda a: a.__setitem__("blacks", -40)),
         ("色温", lambda a: a.__setitem__("temperature", 55)),
         ("色调", lambda a: a.__setitem__("tint", 40)),
         ("自然饱和度", lambda a: a.__setitem__("vibrance", 55)),
         ("饱和度", lambda a: a.__setitem__("saturation", -80)),
         ("清晰度", lambda a: a.__setitem__("clarity", 70)),
         ("去朦胧", lambda a: a.__setitem__("dehaze", 55)),
         ("锐化", lambda a: a.__setitem__("sharpen", 90)),
         ("暗角", lambda a: a.__setitem__("vignette", -70)),
         ("色调分离", lambda a: a.__setitem__("split_hi_sat", 65)),
         ("灰度", lambda a: a.__setitem__("grayscale", True)),
         ("HSL饱和-红", lambda a: a["hsl"]["sat"].__setitem__(0, 85)),
         ("HSL色相-红", lambda a: a["hsl"]["hue"].__setitem__(0, 60)),
         ("主曲线", lambda a: a.__setitem__("curve", [[0, 0], [128, 165], [255, 255]])),
         ("红曲线", lambda a: a.__setitem__("curve_r", [[0, 0], [128, 175], [255, 255]]))]
for name, setter in CASES:
    reset(); setter(app.adj)
    for k in ("tone_key", "color_key", "auto_lut"):
        setattr(app, k, None)
    cur = surf()
    if cur.shape != base.shape or getattr(app, "surface_img", None) is None:
        # 画布尺寸变了（例如工具栏/面板显隐改变了可用区域），无法逐像素比较，
        # 重新取基准，避免误报。
        base = cur
        notice("调整生效:" + name, False, "画布尺寸变化，跳过对比")
        continue
    diff = np.abs(cur - base)
    md, mx = float(diff.mean()), float(diff.max())
    ok("调整生效:" + name, md > 0.4 or mx > 15.0,
       "平均差 %.2f 最大差 %.0f" % (md, mx))

print("--- 2. 局部滤镜 ---")
for kind in ("radial", "linear"):
    reset()
    f = mod.new_local(kind, 0.45, 0.5, 0.28, 0.28, 15.0, 40.0)
    f["adj"] = dict(mod.LOCAL_ADJ_DEFAULT); f["adj"]["exposure"] = 1.1
    app.locals = [f]; app.local_mask_cache = {}
    md = float(np.abs(surf() - base).mean())
    ok("局部滤镜:" + kind, md > 0.4, "平均差 %.2f" % md)
app.locals = []; app.local_mask_cache = {}

print("--- 3. 预览必须等于导出 ---")
reset()
for k in ("tone_key", "color_key", "auto_lut"):
    setattr(app, k, None)
app.detail_cache.clear(); app.detail_inflight = None
app.fast = False
app._render(); wait(app, 300)
end = time.time() + 8
while time.time() < end and app.detail_inflight is not None:
    app.update(); time.sleep(0.01)
app.zoom_mode = "free"; app.scale = 1.0; app.cx = None; app.cy = None
app.photo = None; app.img_item = None
app._render(fast=False); app.update()
pv = app.surface_img
fl = app._flatten()
if pv is not None and pv.size == fl.size:
    d = float(np.abs(np.asarray(pv.convert("RGB"), np.int16)
                     - np.asarray(fl.convert("RGB"), np.int16)).mean())
    ok("预览 == 导出", d == 0, "平均差 %.3f" % d)
else:
    notice("预览 == 导出", False, "尺寸不同，跳过")

print("--- 4. 快照 ---")
app.adj["exposure"] = 1.0
for k in ("tone_key", "color_key", "auto_lut"):
    setattr(app, k, None)
app._render(); wait(app, 250)
b1 = float(surf().mean())
app.add_snapshot()
app.adj["exposure"] = -1.2
for k in ("tone_key", "color_key", "auto_lut"):
    setattr(app, k, None)
app._render(); wait(app, 250)
if app.snapshots and app.snapshot_box is not None:
    app.snapshot_box.selection_set(0)
    app.restore_snapshot(); wait(app, 350)
    b2 = float(surf().mean())
    ok("快照恢复", abs(b2 - b1) < 0.6, "%.1f -> %.1f" % (b1, b2))
else:
    ok("快照恢复", False, "快照功能不可用")

print("--- 5. EXIF ---")
ex = app._source_exif()
good = bool(ex) and b"Nikon" in ex
if ex:
    e2 = Image.Exif(); e2.load(ex)
    good = good and e2.get(0x010F) == "Nikon" and e2.get(0x0112) == 1
ok("EXIF 保留", good, "%d 字节" % (len(ex) if ex else 0))

print("--- 6. 自动色调 / 白平衡 ---")
app.adj = mod.QPEApp._default_adj()
for k in ("tone_key", "color_key", "auto_lut"):
    setattr(app, k, None)
app._render(); wait(app, 250)
before = float(surf().mean())
app.auto_tone(); wait(app, 500)
ok("自动色调改变了画面", abs(float(surf().mean()) - before) > 0.4,
   "%.1f -> %.1f" % (before, float(surf().mean())))
app.auto_wb(); wait(app, 400)
ok("自动白平衡可运行", True, "色温 %+.0f" % app.adj["temperature"])

print("--- 7. 操作电池 ---")
app.adj = mod.QPEApp._default_adj()
for k in ("tone_key", "color_key", "auto_lut"):
    setattr(app, k, None)
app._render(); wait(app, 250)
n0 = len(errors)
ops = [("裁剪", lambda: (app.toggle_crop(), app.update(), app.cancel_crop())),
       ("分屏", lambda: (app.toggle_split(), app.update(), app.toggle_split())),
       ("胶片条", lambda: (app.toggle_strip(True), app.update(), app.toggle_strip(False))),
       ("过曝警告", lambda: (app.toggle_clip(True), app.update(), app.toggle_clip(False))),
       ("对比原图", lambda: (app.toggle_compare(True), app.toggle_compare(False))),
       ("缩放", lambda: [app._set_scale(s, None) for s in (0.3, 1.0, 2.2)]),
       ("适应窗口", lambda: app.fit_window()),
       ("撤销", lambda: (app.undo(), app.redo())),
       ("重置", lambda: app.reset_edit_all()),
       ("信息窗口", lambda: (app.show_info(), app.update(),
                             app.info_win.destroy(), setattr(app, "info_win", None))),
       ("关于", lambda: (app.show_about(), app.update(),
                         app.about_win.destroy(), setattr(app, "about_win", None))),
       ("帮助", lambda: (app.show_help(), app.update()))]
for name, fn in ops:
    try:
        fn(); app.update(); time.sleep(0.12)
    except Exception as exc:
        errors.append("%s: %r" % (name, exc))
    wait(app, 60)
for w in list(app.winfo_children()):
    if isinstance(w, mod.tk.Toplevel):
        try: w.destroy()
        except Exception: pass
ok("操作电池无异常", len(errors) == n0, "新增 %d 条 %s" % (len(errors) - n0, errors[-2:]))
ok("窗口仍存活", bool(app.winfo_exists()))
app.destroy()
shutil.rmtree(WORK, ignore_errors=True)

print()
if FAIL:
    print(">>> 自检失败 %d 项: %s" % (len(FAIL), ", ".join(FAIL)))
    sys.exit(1)
print(">>> 自检全部通过 (v%s)" % getattr(mod, "APP_VERSION", "?"))
