PLUGIN_NAME = "复古胶片"
PLUGIN_DESC = {"zh": "暖褐色调。可调强度、对比与暗角", "en": "Warm sepia. Adjustable strength, contrast and vignette", "ja": "暖かいセピア調。強さ・コントラスト・周辺減光を調整"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

PLUGIN = {"id": "sepia", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}


from PIL import Image, ImageEnhance

PARAMS = [
    {"key": "strength", "label": {"zh": "褐色强度", "en": "Sepia strength", "ja": "セピア強度"}, "min": 0, "max": 100,
     "default": 70, "step": 5},
    {"key": "contrast", "label": {"zh": "对比度", "en": "Contrast", "ja": "コントラスト"}, "min": 50, "max": 150,
     "default": 96, "step": 2},
    {"key": "vignette", "label": {"zh": "暗角", "en": "Vignette", "ja": "周辺減光"}, "min": 0, "max": 100,
     "default": 35, "step": 5},
]


def _sepia(gray, amount):
    """amount=0 保持原色，100 完全褐色。"""
    r = gray.point([min(255, int(v * 1.10 + 18)) for v in range(256)])
    g = gray.point([min(255, int(v * 1.02 + 10)) for v in range(256)])
    b = gray.point([min(255, int(v * 0.88)) for v in range(256)])
    if amount <= 0:
        return gray.convert("RGB")
    if amount >= 100:
        return Image.merge("RGB", (r, g, b))
    rgb = gray.convert("RGB")
    k = amount / 100.0
    return Image.blend(rgb, Image.merge("RGB", (r, g, b)), k)


def run(img, **params):
    path = None
    p = params or {}
    amount = float(p.get("strength", 70))
    out = _sepia(img.convert("L"), amount)
    out = ImageEnhance.Contrast(out).enhance(float(p.get("contrast", 96)) / 100.0)

    vig = float(p.get("vignette", 35))
    if vig > 0:
        w, h = out.size
        small = out.resize((120, max(1, int(120 * h / max(1, w)))))
        sw, sh = small.size
        mask = Image.new("L", (sw, sh), 0)
        px_ = mask.load()
        cx, cy = sw / 2.0, sh / 2.0
        maxd = (cx * cx + cy * cy) ** 0.5
        for y in range(sh):
            for x in range(sw):
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
                v = 1.0 - (d ** 2) * (vig / 100.0)
                px_[x, y] = int(max(0.0, min(1.0, v)) * 255)
        mask = mask.resize((w, h), Image.Resampling.BILINEAR)
        dark = Image.new("RGB", (w, h), (0, 0, 0))
        out = Image.composite(out, dark, mask)
    return out
