# -*- coding: utf-8 -*-
"""美颜模块回归测试：覆盖 50 轮迭代加的所有能力。

跑法：python tools/newcheck.py
"""
import importlib.machinery
import os
import shutil
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

APP = r"D:\pictu\src\Prism.pyw"
WORK = os.path.join(os.environ.get("TEMP", "."), "_prism_new")
FAIL = []


def ok(name, cond, detail=""):
    if cond:
        print("  PASS %-30s %s" % (name, detail))
    else:
        FAIL.append(name)
        print("  FAIL %-30s %s" % (name, detail))


def skin_face(W=600, H=800, spots=()):
    im = Image.new("RGB", (W, H), (40, 70, 120))
    d = ImageDraw.Draw(im)
    d.ellipse([W * 0.30, H * 0.15, W * 0.70, H * 0.88], fill=(226, 183, 158))
    for fx in (0.42, 0.58):
        d.ellipse([W * fx - 14, H * 0.37, W * fx + 14, H * 0.40], fill=(45, 40, 35))
        d.arc([W * fx - 16, H * 0.408, W * fx + 16, H * 0.455],
              15, 165, fill=(150, 112, 104), width=3)
    for (cx, cy) in ((200, 300), (380, 420), (260, 400), (350, 500)):
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(150, 105, 85))
    for (cx, cy) in spots:
        d.ellipse([cx - 8, cy - 8, cx + 8, cy + 8], fill=(150, 105, 85))
    arr = np.asarray(im, np.float32)
    rng = np.random.default_rng(7)
    arr = np.clip(arr + rng.normal(0, 2.2, (H, W, 1)), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK)
mod = importlib.machinery.SourceFileLoader("pic", APP).load_module()
print("=== 美颜模块回归 v%s ===" % mod.APP_VERSION)

S = os.path.join(r"D:\pictu\src", "Prism_settings.json")
if os.path.exists(S):
    os.remove(S)
app = mod.QPEApp()
for _ in range(40):
    app.update(); time.sleep(0.02)

face = skin_face(spots=((200, 300), (380, 420)))
face_path = os.path.join(WORK, "face.jpg")
face.save(face_path, quality=92)
app.open_files([face_path])
for _ in range(70):
    app.update(); time.sleep(0.02)
base = app._flatten().convert("RGB")
a0 = np.asarray(base, np.int16)


def run(**patch):
    app.adj = mod.QPEApp._default_adj()
    app.adj.update(patch)
    app.geom_key = None
    app.detail_cache.clear()
    return np.asarray(app._flatten().convert("RGB"), np.int16)


def diff(arr):
    return float(np.abs(arr - a0).mean())


print("--- 1. 各项效果单独生效 ---")
for label, patch in (("磨皮", dict(skin_smooth=60.0)),
                     ("均匀", dict(skin_even=60.0)),
                     ("提亮", dict(skin_glow=60.0)),
                     ("祛斑", dict(skin_blemish=60.0)),
                     ("眼周", dict(skin_eye_care=60.0)),
                     ("唇色", dict(skin_lip=60.0)),
                     ("瘦脸", dict(skin_slim=60.0)),
                     ("大眼", dict(skin_eyes=60.0)),
                     ("去油光", dict(skin_shine=60.0)),
                     ("冷暖", dict(skin_warm=60.0)),
                     ("柔光", dict(skin_soft=60.0))):
    d = diff(run(**patch))
    floor = 0.003 if label == "眼周" else 0.005
    ok("%s 单独生效" % label, d > floor, "平均差 %.3f" % d)

print("--- 2. 中性值不改变画面 ---")
d = diff(run())
ok("全部为 0 时不动", d == 0.0, "平均差 %.3f" % d)
d = diff(run(skin_blemish=0.0, skin_eye_care=0.0))
ok("显式给 0 也不动", d == 0.0, "平均差 %.3f" % d)

print("--- 3. 语义正确性 ---")
a1 = run(skin_smooth=100.0)
ok("磨皮只动肤色区", float(np.abs(a1[0:80, 0:80] - a0[0:80, 0:80]).mean()) < 0.05,
   "四角 %.3f" % float(np.abs(a1[0:80, 0:80] - a0[0:80, 0:80]).mean()))
a1 = run(skin_blemish=100.0)
spot_before = float(a0[292:308, 192:208].mean())
spot_after = float(a1[292:308, 192:208].mean())
ok("祛斑把暗斑提亮", spot_after > spot_before,
   "%.1f -> %.1f" % (spot_before, spot_after))
a1 = run(skin_slim=100.0)
row = a1[int(800 * 0.80)]
cols = np.where((row[:, 0] > 150))[0]
row0 = a0[int(800 * 0.80)]
cols0 = np.where((row0[:, 0] > 150))[0]
ok("瘦脸使下巴变窄", (cols[-1] - cols[0]) < (cols0[-1] - cols0[0]),
   "%d -> %d" % (cols0[-1] - cols0[0], cols[-1] - cols[0]))

print("--- 4. 边界保护 ---")
for label, img in (("极小图", Image.new("RGB", (16, 16), (226, 183, 158))),
                   ("纯色图", Image.new("RGB", (300, 300), (120, 120, 120))),
                   ("黑白照", Image.new("RGB", (300, 400), (180, 180, 180))),
                   ("极端比例", Image.new("RGB", (2000, 100), (226, 183, 158)))):
    try:
        out = mod._beautify(img, 100, 50, 50, 50, 30, 10, 20, None, 50, 5, 50, 50, 40, 50, 30, 30)
        ok("%s 安全跳过" % label,
           np.abs(np.asarray(out, np.int16) - np.asarray(img, np.int16)).mean() == 0)
    except Exception as exc:
        ok("%s 安全跳过" % label, False, str(exc))

print("--- 5. 预设与对比 ---")
app.adj = mod.QPEApp._default_adj()
app.apply_beauty_preset("素颜")
ok("素颜预设全部归零", diff(run(**app.BEAUTY_PRESETS["素颜"])) == 0.0)
strengths = []
for nm in ("自然", "人像", "网红"):
    app.adj = mod.QPEApp._default_adj()
    app.apply_beauty_preset(nm)
    app.geom_key = None; app.detail_cache.clear()
    strengths.append(float(np.abs(np.asarray(app._flatten(), np.int16) - a0).mean()))
ok("预设强度递增", strengths[0] < strengths[1] < strengths[2],
   "%.2f < %.2f < %.2f" % tuple(strengths))
app.adj = mod.QPEApp._default_adj()
app.adj.update(skin_smooth=80.0, skin_glow=50.0)
app.geom_key = None; app.detail_cache.clear()
with_b = np.asarray(app._flatten(), np.int16)
app.beauty_off = True
without = np.asarray(app._flatten(), np.int16)
app.beauty_off = False
ok("对比开关只关美颜", float(np.abs(without - a0).mean()) == 0.0,
   "关美颜后与原图差 %.3f" % float(np.abs(without - a0).mean()))

print("--- 6. 多人合影 ---")
two = Image.new("RGB", (800, 600), (40, 70, 120))
d = ImageDraw.Draw(two)
d.ellipse([80, 150, 320, 520], fill=(226, 183, 158))
d.ellipse([470, 160, 710, 530], fill=(214, 176, 150))
skin = mod._skin_mask(two, 4)
boxes = mod._face_boxes(skin)
ok("检出两张脸", len(boxes) == 2, "%d 张" % len(boxes))
arm = Image.new("RGB", (800, 600), (40, 70, 120))
da = ImageDraw.Draw(arm)
da.ellipse([300, 120, 500, 480], fill=(226, 183, 158))
da.rectangle([0, 500, 800, 560], fill=(226, 183, 158))
ok("手臂不被当成脸", len(mod._face_boxes(mod._skin_mask(arm, 4))) == 1)

print("--- 8. 肤质、斑点和边界 ---")
quality_src = Image.fromarray(a0.astype(np.uint8), "RGB")
beauty = mod._beautify(quality_src, 55, 45, 20, 45, 0, 0, 0, None,
                       55, 6, 55, 55, 35, 55, 0, 0)
bb = np.asarray(beauty, np.int16)
b0 = np.asarray(quality_src.convert("L"), np.float32)
b1 = np.asarray(beauty.convert("L"), np.float32)
cb = (int(600 * 0.36), int(800 * 0.47), int(600 * 0.48), int(800 * 0.58))
std0 = float(b0[cb[1]:cb[3], cb[0]:cb[2]].std())
std1 = float(b1[cb[1]:cb[3], cb[0]:cb[2]].std())
ok("肤色更均匀", std1 < std0 * 0.80, "%.1f -> %.1f" % (std0, std1))

spot_before = []
spot_after = []
for (sx, sy) in ((260, 400), (350, 500)):
    r = 10
    ring = float(np.concatenate([
        b0[sy - 30:sy - 10, sx - 30:sx + 30].ravel(),
        b0[sy + 10:sy + 30, sx - 30:sx + 30].ravel()]).mean())
    spot_before.append(ring - float(b0[sy - r:sy + r, sx - r:sx + r].mean()))
    spot_after.append(ring - float(b1[sy - r:sy + r, sx - r:sx + r].mean()))
ok("斑点对比度下降", (sum(spot_after) / 2.0) < (sum(spot_before) / 2.0) * 0.60,
   "%.1f -> %.1f" % (sum(spot_before) / 2.0, sum(spot_after) / 2.0))
ok("斑点不被修成亮斑", min(spot_after) > -1.5,
   "min %.1f" % min(spot_after))

hp0 = b0[cb[1]:cb[3], cb[0]:cb[2]] - np.asarray(
    quality_src.convert("L").crop(cb).filter(ImageFilter.GaussianBlur(1.5)),
    np.float32)
hp1 = b1[cb[1]:cb[3], cb[0]:cb[2]] - np.asarray(
    beauty.convert("L").crop(cb).filter(ImageFilter.GaussianBlur(1.5)),
    np.float32)
tex = float(hp1.std() / max(1e-6, hp0.std()))
ok("保留高频皮肤纹理", 0.45 <= tex <= 1.10, "纹理比 %.2f" % tex)

outside = float(np.abs(bb[0:60, 0:60] - a0[0:60, 0:60]).mean())
ok("脸外像素不被误改", outside < 0.05, "背景差 %.3f" % outside)

hair = Image.new("RGB", (300, 300), (226, 183, 158))
ImageDraw.Draw(hair).rectangle([0, 0, 300, 80], fill=(42, 32, 28))
ok("深棕头发不算肤色", mod._skin_mask(hair, 3).getpixel((150, 40)) < 96)

body = Image.new("RGB", (600, 800), (40, 70, 120))
db = ImageDraw.Draw(body)
db.ellipse([180, 100, 420, 650], fill=(226, 183, 158))
db.rectangle([80, 650, 520, 800], fill=(226, 183, 158))
boxes = mod._face_boxes(mod._skin_mask(body, 4))
ok("脸框不吞并肩膀", len(boxes) == 1 and boxes[0][3] < 800 * 0.85,
   "%s" % (boxes,))

mouth = Image.new("RGB", (400, 500), (226, 183, 158))
ImageDraw.Draw(mouth).ellipse([150, 300, 250, 360], fill=(168, 86, 82))
mr = mod._mouth_region(mouth, (100, 100, 200, 300))
ok("嘴部区域可定位", mr is not None and 100 < (mr[1] + mr[3]) / 2 < 500,
   "%s" % (mr,))

print("--- 9. 预设强度与联动 ---")
app.adj = mod.QPEApp._default_adj()
app.apply_beauty_preset("自然")
tight = dict(app.adj)
app.adj = mod.QPEApp._default_adj()
app.apply_beauty_preset("网红")
strong = dict(app.adj)
ok("网红比自然更强", strong["skin_smooth"] > tight["skin_smooth"]
   and strong["skin_blemish"] > tight["skin_blemish"]
   and strong["skin_slim"] > tight["skin_slim"])
ok("新预设保留分区", all(app.adj.get(k, 0) > 0 for k in
                         ("zone_forehead", "zone_cheek", "zone_chin")))

print("--- 10. 预览与导出一致 ---")
app.adj = mod.QPEApp._default_adj()
app.adj.update(skin_smooth=60.0, skin_blemish=50.0, skin_eye_care=40.0,
               skin_slim=30.0, skin_eyes=30.0)
app.geom_key = None
for k in ("tone_key", "color_key"):
    setattr(app, k, None)
app.detail_cache.clear(); app.detail_inflight = None
app.photo = None; app.img_item = None
for _ in range(30):
    app.update(); time.sleep(0.02)
app._render(fast=False)
for _ in range(20):
    app.update(); time.sleep(0.02)
pv, fl = app.surface_img, app._flatten()
if pv is not None and pv.size == fl.size:
    d = float(np.abs(np.asarray(pv.convert("RGB"), np.int16)
                     - np.asarray(fl.convert("RGB"), np.int16)).mean())
    ok("预览 == 导出", d < 0.01, "平均差 %.3f" % d)
else:
    ok("预览 == 导出", False, "尺寸不同")

app.destroy()
if os.path.exists(S):
    os.remove(S)
shutil.rmtree(WORK, ignore_errors=True)
print()
if FAIL:
    print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
    raise SystemExit(1)
print(">>> 美颜回归全部通过")
