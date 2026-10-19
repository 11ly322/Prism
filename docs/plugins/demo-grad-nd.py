# -*- coding: utf-8 -*-
"""示例插件：渐变减光（Graduated ND）。

这个文件有两个用途：
1. 验证「插件 → 从网址安装」的下载 + SHA-256 校验链路；
2. 当作写插件的起点 —— 三个参数、一个 run()，没有别的约定。

安装：Prism 插件窗口 →「从网址安装…」→ 点「示例：渐变减光」→ 下载并安装。
"""
import numpy as np
from PIL import Image

PLUGIN = {
    "id": "grad-nd",
    "name": "渐变减光（示例）",
    "version": "1.0",
    "api": 2,
    "author": "Prism",
    "description": "从画面一侧平滑压暗，模拟中灰渐变镜；常用来压天空",
    "network": False,
    "writes_files": False,
}

PARAMS = [
    {"key": "amount", "label": "减光强度", "type": "slider",
     "min": 0, "max": 100, "default": 45, "step": 5},
    {"key": "side", "label": "压暗一侧", "type": "select",
     "options": ["顶部", "底部"], "default": "顶部"},
    {"key": "feather", "label": "过渡宽度", "type": "slider",
     "min": 5, "max": 100, "default": 45, "step": 5},
]


def run(img, **params):
    """img -> 压暗一侧后的新图；不修改传入对象。"""
    amount = max(0.0, min(100.0, float(params.get("amount", 45)))) / 100.0
    if amount <= 0:
        return img.copy()
    feather = max(5.0, min(100.0, float(params.get("feather", 45)))) / 100.0
    side = str(params.get("side", "顶部"))

    rgb = img.convert("RGB")
    a = np.asarray(rgb, dtype=np.float32)
    h = a.shape[0]
    t = np.linspace(0.0, 1.0, h, dtype=np.float32)
    u = t if side == "底部" else (1.0 - t)      # 1 在要压暗的一侧
    start = max(0.0, 1.0 - feather)
    x = np.clip((u - start) / max(1e-3, feather), 0.0, 1.0)
    mask = x * x * (3.0 - 2.0 * x)              # smoothstep，边缘不留硬线
    gain = (1.0 - amount * mask)[:, None, None]
    out = np.clip(a * gain, 0, 255).astype(np.uint8)

    res = Image.fromarray(out, "RGB")
    if img.mode == "L":
        return res.convert("L")
    if img.mode == "RGBA":
        res = res.convert("RGBA")
        res.putalpha(img.getchannel("A"))
    return res
