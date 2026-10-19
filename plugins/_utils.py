# -*- coding: utf-8 -*-
"""插件小工具（文件名以下划线开头，不会被当成插件加载）。

不是框架，只是几段复制粘贴也能用的函数。按需 import：

    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _utils import downscale_if_needed, preserve_alpha

为什么要先 sys.path.insert：Prism 按文件路径加载插件，插件目录不在
sys.path 里，直接 import 会失败。
"""


def downscale_if_needed(img, max_side=2048, resample=None):
    """长边超过 max_side 就先缩小，返回 (图, 缩放比)。

    缩放比为 1.0 表示没动过，处理完用 upscale_back 还原尺寸。
    大图不降采样会让滑杆每动一下都算几千万像素，界面直接卡住。
    """
    from PIL import Image
    if resample is None:
        resample = Image.BILINEAR
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img, 1.0
    scale = max_side / float(longest)
    small = img.resize((max(1, int(round(w * scale))),
                        max(1, int(round(h * scale)))), resample)
    return small, scale


def upscale_back(img, size, resample=None):
    """把处理完的小图放大回原尺寸。size 是 (宽, 高)。"""
    from PIL import Image
    if resample is None:
        resample = Image.BICUBIC
    if tuple(img.size) == tuple(size):
        return img
    return img.resize(size, resample)


def to_rgb(img):
    """统一转 RGB；RGBA / P / L 都能进。"""
    return img.convert("RGB") if img.mode != "RGB" else img


def split_alpha(img):
    """返回 (RGB 图, alpha 或 None)。"""
    if img.mode == "RGBA":
        r, g, b, a = img.split()
        return img.convert("RGB"), a
    return img.convert("RGB"), None


def preserve_alpha(img, func):
    """对 RGBA 图保持透明通道：func(rgb) 只处理颜色，alpha 原样贴回。

    用法： return preserve_alpha(img, lambda rgb: rgb.filter(...))
    """
    rgb, alpha = split_alpha(img)
    out = func(rgb)
    if alpha is None:
        return out
    out = out.convert("RGB")
    out.putalpha(alpha)
    return out


def clamp_params(params, spec):
    """按 PARAMS 把传入值夹到合法范围，防止手工调用时越界。

    spec 就是插件自己的 PARAMS 列表；直接：
        p = clamp_params(params, PARAMS)
    """
    out = dict(params or {})
    for p in spec or []:
        key = p.get("key")
        if not key:
            continue
        kind = str(p.get("type", "slider")).lower()
        val = out.get(key, p.get("default"))
        try:
            if kind in ("checkbox", "bool", "switch", "toggle"):
                out[key] = bool(val)
            elif kind in ("select", "choice", "dropdown"):
                opts = list(p.get("choices") or p.get("options") or [])
                out[key] = val if val in opts else (opts[0] if opts else val)
            else:
                v = float(val)
                lo = float(p.get("min", 0))
                hi = float(p.get("max", 100))
                out[key] = max(lo, min(hi, v))
        except Exception:
            out[key] = p.get("default")
    return out


def preview_then_export(func, img, max_side=2048):
    """一条龙：先降采样跑 func，再放大回原尺寸，alpha 自动贴回。

    适合「预览要快、导出要与预览一致」的插件。用法：

        def run(img, **params):
            def work(small):
                return small.convert("L").convert("RGB")
            return preview_then_export(work, img)

    func 只接收一张（可能缩小的）RGB 图，返回同尺寸的图。
    """
    rgb, alpha = split_alpha(img)
    size = rgb.size
    small, scale = downscale_if_needed(rgb, max_side)
    out = func(small)
    if out is None:
        return img
    if scale != 1.0:
        out = upscale_back(out, size)
    if alpha is not None:
        out = out.convert("RGB")
        out.putalpha(alpha)
    return out
