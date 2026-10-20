PLUGIN_NAME = "像素化"
PLUGIN_DESC = {"zh": "马赛克。可调方块大小、取样方式与描边", "en": "Mosaic. Adjustable block size, sampling and edge drawing", "ja": "モザイク。ブロックサイズ・サンプリング・縁取りを調整"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

PLUGIN = {"id": "pixelate", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}


from PIL import Image, ImageDraw

_BOX = getattr(getattr(Image, "Resampling", Image), "BOX", 4)
_NEAREST = getattr(getattr(Image, "Resampling", Image), "NEAREST", 0)

PARAMS = [
    {"key": "block", "label": {"zh": "方块大小", "en": "Block size", "ja": "ブロックサイズ"}, "min": 4, "max": 160,
     "default": 24, "step": 1},
    {"key": "mode", "label": {"zh": "取样方式", "en": "Sampling", "ja": "サンプリング"}, "type": "choice",
     "choices": [{"value": "平均", "label": {"zh": "平均", "en": "Average", "ja": "平均"}}, {"value": "放大镜", "label": {"zh": "放大镜", "en": "Magnifier", "ja": "ルーペ"}}], "default": "平均"},
    {"key": "edge", "label": {"zh": "画方块边", "en": "Draw edges", "ja": "縁を描く"}, "type": "bool", "default": False},
]


def run(img, **params):
    path = None
    p = params or {}
    block = max(2, int(p.get("block", 24)))
    src = img.convert("RGB")
    w, h = src.size
    bw = max(1, w // block)
    bh = max(1, h // block)

    if p.get("mode") == "放大镜":
        # 最近邻取样：保留一个像素的原色，块感更"数码"
        small = src.resize((bw, bh), _NEAREST)
    else:
        small = src.resize((bw, bh), _BOX)      # 平均值，块内更平滑

    out = small.resize((w, h), _NEAREST)

    if p.get("edge"):
        draw = ImageDraw.Draw(out)
        sx = w / float(bw)
        sy = h / float(bh)
        for i in range(bw + 1):
            x = min(w - 1, int(i * sx))
            draw.line([(x, 0), (x, h - 1)], fill=(0, 0, 0))
        for j in range(bh + 1):
            y = min(h - 1, int(j * sy))
            draw.line([(0, y), (w - 1, y)], fill=(0, 0, 0))
    return out
