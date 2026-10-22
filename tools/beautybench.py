# -*- coding: utf-8 -*-
"""美颜质量台架：用可复现的合成人像量化 50 轮优化。

指标不是“越平滑越好”：
  * 肤色区域内的不均匀度要下降；
  * 高频纹理要保留，不能磨成塑料；
  * 人脸外像素不能被误改；
  * 高光不能新增裁切，暗部要能提亮；
  * 不同肤色 / 色偏 / 光照下都要有人脸与肤色覆盖。

跑法：
  python tools/beautybench.py            # 打印当前指标
  python tools/beautybench.py --json     # 机器可读，供迭代对比
  python tools/beautybench.py --save design/beauty-bench.json
"""
import argparse
import importlib.machinery
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.environ.get("PRISM_APP") or os.path.join(ROOT, "src", "Prism.pyw")


def _load():
    src = os.path.join(ROOT, "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    return importlib.machinery.SourceFileLoader("pic", APP).load_module()


def _noise(W, H, amp, seed):
    rng = np.random.default_rng(seed)
    n = rng.normal(0.0, amp, (H, W, 1))
    return n


def portrait(tone="medium", cast=(0, 0, 0), W=720, H=960, seed=7,
             blemishes=True, lowlight=False):
    """合成一张有皮肤纹理、瑕疵、眼周与高光的人像。"""
    palettes = {
        "fair": (236, 196, 174),
        "medium": (202, 151, 118),
        "olive": (184, 150, 112),
        "deep": (124, 86, 66),
    }
    skin = palettes[tone]
    # 背景保持中性，避免用大面积肤色块把“人脸检测”变成不可能任务；
    # 单独的 skin_out 指标仍会检查背景是否被误判成皮肤。
    bg = Image.new("RGB", (W, H), (42, 64, 82))
    d = ImageDraw.Draw(bg)
    d.rectangle([0, 0, int(W * 0.12), H], fill=(30, 46, 58))
    d.rectangle([int(W * 0.88), 0, W, H], fill=(35, 52, 64))
    # 肩颈
    d.rounded_rectangle([W * 0.18, H * 0.80, W * 0.82, H * 1.05],
                        radius=int(W * 0.12), fill=skin)
    d.rectangle([W * 0.43, H * 0.76, W * 0.57, H * 0.92], fill=skin)
    # 头发外轮廓与脸
    d.ellipse([W * 0.24, H * 0.07, W * 0.76, H * 0.90], fill=(38, 28, 24))
    d.ellipse([W * 0.31, H * 0.15, W * 0.69, H * 0.86], fill=skin)
    # 耳朵
    for ex in (0.305, 0.695):
        d.ellipse([W * ex - W * 0.025, H * 0.38, W * ex + W * 0.025, H * 0.51],
                  fill=skin)
    # 眉、眼白、虹膜、睫毛
    for fx in (0.415, 0.585):
        ex, ey = W * fx, H * 0.385
        d.arc([ex - W * 0.062, ey - H * 0.030, ex + W * 0.062, ey + H * 0.026],
              200, 340, fill=(58, 42, 34), width=max(2, W // 180))
        d.ellipse([ex - W * 0.055, ey - H * 0.018, ex + W * 0.055, ey + H * 0.018],
                  fill=(238, 232, 224))
        d.ellipse([ex - W * 0.025, ey - H * 0.016, ex + W * 0.025, ey + H * 0.016],
                  fill=(74, 58, 40))
        d.ellipse([ex - W * 0.011, ey - H * 0.012, ex + W * 0.011, ey + H * 0.012],
                  fill=(26, 22, 18))
        d.ellipse([ex - W * 0.006, ey - H * 0.008, ex + W * 0.006, ey + H * 0.006],
                  fill=(245, 245, 242))
        # 下眼睑暗圈
        d.arc([ex - W * 0.055, ey + H * 0.006, ex + W * 0.055, ey + H * 0.050],
              20, 160, fill=(150, 112, 104), width=max(2, W // 220))
    # 鼻子与嘴
    d.polygon([(W * 0.50, H * 0.40), (W * 0.475, H * 0.56), (W * 0.525, H * 0.56)],
              fill=(int(skin[0] * 0.93), int(skin[1] * 0.88), int(skin[2] * 0.86)))
    d.ellipse([W * 0.455, H * 0.62, W * 0.545, H * 0.68], fill=(168, 86, 82))
    d.ellipse([W * 0.470, H * 0.640, W * 0.530, H * 0.665], fill=(238, 230, 218))
    d.line([(W * 0.455, H * 0.650), (W * 0.545, H * 0.650)],
           fill=(142, 70, 68), width=max(1, W // 300))
    # 高光：额头与鼻梁
    gl = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(gl)
    gd.ellipse([W * 0.40, H * 0.22, W * 0.60, H * 0.34], fill=70)
    gd.ellipse([W * 0.47, H * 0.46, W * 0.53, H * 0.58], fill=52)
    gl = gl.filter(ImageFilter.GaussianBlur(W / 35.0))
    bg = Image.composite(Image.new("RGB", (W, H), (255, 250, 242)), bg, gl)
    # 瑕疵：固定位置，指标才能稳定比较；再补几颗随机小点模拟真实皮肤
    if blemishes:
        d = ImageDraw.Draw(bg)
        for (fx, fy) in ((0.385, 0.575), (0.605, 0.515)):
            cx, cy = W * fx, H * fy
            r = W * 0.010
            d.ellipse([cx - r, cy - r, cx + r, cy + r],
                      fill=(int(skin[0] * 0.66), int(skin[1] * 0.58),
                            int(skin[2] * 0.58)))
        rng = np.random.default_rng(seed + 11)
        for _ in range(7):
            cx = rng.uniform(W * 0.34, W * 0.66)
            cy = rng.uniform(H * 0.24, H * 0.80)
            if abs(cx - W * 0.5) < W * 0.08 and H * 0.37 < cy < H * 0.68:
                continue
            r = rng.uniform(W * 0.005, W * 0.011)
            d.ellipse([cx - r, cy - r, cx + r, cy + r],
                      fill=(int(skin[0] * 0.70), int(skin[1] * 0.64),
                            int(skin[2] * 0.64)))
    # 纹理噪声
    arr = np.asarray(bg, dtype=np.float32)
    n = _noise(W, H, 2.4, seed)
    arr = np.clip(arr + n, 0, 255)
    # 光照与色偏
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    xx = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
    light = (1.03 - 0.12 * yy + 0.035 * (xx - 0.5))
    if lowlight:
        light *= 0.62
    arr = np.clip(arr * light + np.array(cast, dtype=np.float32), 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGB")


def _face_mask(W, H, pad=0.0):
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse(
        [W * (0.31 - pad), H * (0.15 - pad), W * (0.69 + pad), H * (0.86 + pad)],
        fill=255)
    return m


def _cheek_boxes(W, H):
    return ((int(W * 0.35), int(H * 0.48), int(W * 0.45), int(H * 0.62)),
            (int(W * 0.55), int(H * 0.48), int(W * 0.65), int(H * 0.62)))


def _cheek_box(W, H):
    return _cheek_boxes(W, H)[0]


def _spot_boxes(W, H):
    return [(int(W * 0.385), int(H * 0.575)), (int(W * 0.605), int(H * 0.515))]


def _background_mask(W, H):
    """人像之外的区域：左右背景与顶部头发，美颜不应改到这些像素。"""
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rectangle([0, 0, int(W * 0.17), H], fill=255)
    d.rectangle([int(W * 0.83), 0, W, H], fill=255)
    d.rectangle([0, 0, W, int(H * 0.10)], fill=255)
    return m


def _luma(img):
    return np.asarray(img.convert("L"), np.float32)


def _hf_energy(img, box):
    g = img.convert("L").crop(box)
    hp = np.asarray(g, np.float32) - np.asarray(
        g.filter(ImageFilter.GaussianBlur(1.6)), np.float32)
    return float(hp.std())


def _skin_stats(mod, img):
    W, H = img.size
    skin = mod._skin_mask(img, 3)
    a = np.asarray(skin, np.uint8) > 96
    face = np.asarray(_face_mask(W, H), np.uint8) > 96
    return {
        "skin_face": float(a[face].mean()) if face.any() else 0.0,
        "skin_out": float(a[~face].mean()) if (~face).any() else 0.0,
    }


def run():
    mod = _load()
    rows = {}
    tones = ("fair", "medium", "olive", "deep")
    for tone in tones:
        img = portrait(tone, seed=3)
        W, H = img.size
        base = np.asarray(img, np.float32)
        st = _skin_stats(mod, img)
        boxes = mod._face_boxes(mod._skin_mask(img, 4))
        out = mod._beautify(img, 55, 45, 20, 45, 0, 0, 0, None,
                            55, 6, 55, 55, 35, 55, 0, 0)
        arr = np.asarray(out, np.float32)
        face = np.asarray(_face_mask(W, H), np.uint8) > 96
        bg = np.asarray(_background_mask(W, H), np.uint8) > 96
        delta = np.abs(arr - base).mean(axis=2)
        b0 = _luma(img)
        b1 = _luma(out)
        # 只统计颊部纯皮肤，避免眼睛/嘴唇的固定边缘掩盖肤色均匀度的变化
        cheek_std = []
        for cb in _cheek_boxes(W, H):
            cheek_std.append((float(b0[cb[1]:cb[3], cb[0]:cb[2]].std()),
                              float(b1[cb[1]:cb[3], cb[0]:cb[2]].std())))
        tone_std0 = float(np.mean([x[0] for x in cheek_std]))
        tone_std1 = float(np.mean([x[1] for x in cheek_std]))
        # 只统计五官外、纯皮肤颊部的高频纹理
        cheek = _cheek_boxes(W, H)[0]
        tex0 = _hf_energy(img, cheek)
        tex1 = _hf_energy(out, cheek)
        spots = []
        for (sx, sy) in _spot_boxes(W, H):
            r = 12
            before = float(b0[sy - r:sy + r, sx - r:sx + r].mean())
            after = float(b1[sy - r:sy + r, sx - r:sx + r].mean())
            ring = float(np.concatenate([
                b0[sy - 3 * r:sy - r, sx - 3 * r:sx + 3 * r].ravel(),
                b0[sy + r:sy + 3 * r, sx - 3 * r:sx + 3 * r].ravel()]).mean())
            spots.append((ring - before, ring - after))
        spot0 = float(np.mean([x[0] for x in spots]))
        spot1 = float(np.mean([x[1] for x in spots]))
        clip0 = int((base.max(axis=2) >= 250).sum())
        clip1 = int((arr.max(axis=2) >= 250).sum())
        rows[tone] = {
            "skin_face": round(st["skin_face"], 4),
            "skin_out": round(st["skin_out"], 4),
            "faces": len(boxes),
            "inside_delta": round(float(delta[face].mean()), 3),
            "outside_delta": round(float(delta[bg].mean()), 3),
            "tone_std": [round(tone_std0, 2), round(tone_std1, 2)],
            "texture_ratio": round(tex1 / tex0, 3) if tex0 else 0.0,
            "spot_contrast": [round(spot0, 2), round(spot1, 2)],
            "clip_added": clip1 - clip0,
        }
    # 低光 + 暖色偏：检测与提亮稳定性
    low = portrait("medium", cast=(18, 8, -4), lowlight=True, seed=9)
    st = _skin_stats(mod, low)
    boxes = mod._face_boxes(mod._skin_mask(low, 4))
    out = mod._beautify(low, 0, 40, 65, 0, 0, 15, 0, None, 0, 5, 0, 50, 0, 0, 0, 0)
    b0, b1 = _luma(low), _luma(out)
    fm = np.asarray(_face_mask(*low.size), np.uint8) > 96
    rows["lowlight"] = {
        "skin_face": round(st["skin_face"], 4),
        "faces": len(boxes),
        "face_luma": [round(float(b0[fm].mean()), 2), round(float(b1[fm].mean()), 2)],
        "clip_added": int((np.asarray(out, np.float32).max(axis=2) >= 250).sum()
                          - (np.asarray(low, np.float32).max(axis=2) >= 250).sum()),
    }
    # 大图路径与耗时
    big = portrait("medium", W=3000, H=4000, seed=5)
    t0 = time.perf_counter()
    big_out = mod._beautify(big, 55, 45, 20, 45, 0, 0, 0, None,
                            55, 6, 55, 55, 35, 55, 25, 25)
    elapsed = time.perf_counter() - t0
    rows["perf"] = {
        "mp": round(big.size[0] * big.size[1] / 1e6, 1),
        "seconds": round(elapsed, 2),
        "changed": bool(np.asarray(big_out).any()),
    }
    rows["version"] = mod.APP_VERSION
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save")
    args = ap.parse_args()
    data = run()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.save:
        with open(args.save, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    if args.json:
        print(text)
        return
    print("=== Prism beauty bench v%s ===" % data["version"])
    for tone in ("fair", "medium", "olive", "deep", "lowlight", "perf"):
        row = data[tone]
        print("%-8s %s" % (tone, json.dumps(row, ensure_ascii=False)))
    # 简单总览：越高越好，仅用于同版本前后对比
    keys = ("fair", "medium", "olive", "deep")
    print("faces=%d/4  skin_face=%.3f  texture=%.3f  spot=%.2f->%.2f  clip=%+d" % (
        sum(data[k]["faces"] > 0 for k in keys),
        float(np.mean([data[k]["skin_face"] for k in keys])),
        float(np.mean([data[k]["texture_ratio"] for k in keys])),
        float(np.mean([data[k]["spot_contrast"][0] for k in keys])),
        float(np.mean([data[k]["spot_contrast"][1] for k in keys])),
        sum(data[k]["clip_added"] for k in keys)))


if __name__ == "__main__":
    main()
