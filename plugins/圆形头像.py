PLUGIN_NAME = "圆形头像"
PLUGIN_DESC = {"zh": "圆形蒙版头像。可调留白、背景色与输出尺寸", "en": "Round-mask avatar. Adjustable padding, background color and output size", "ja": "円形マスクのアバター。余白・背景色・出力サイズを調整"}
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

PLUGIN = {"id": "avatar", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}


from PIL import Image, ImageDraw

_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)

PARAMS = [
    {"key": "size", "label": {"zh": "输出边长", "en": "Output size", "ja": "出力サイズ"}, "min": 128, "max": 1024,
     "default": 512, "step": 64},
    {"key": "margin", "label": {"zh": "留白比例", "en": "Padding", "ja": "余白"}, "min": 0, "max": 30,
     "default": 0, "step": 1},
    {"key": "bg", "label": {"zh": "背景", "en": "Background", "ja": "背景"}, "type": "choice",
     "choices": ["透明", "白色", "黑色"], "default": "透明"},
]


def run(img, **params):
    path = None
    p = params or {}
    side = int(p.get("size", 512))
    margin = int(p.get("margin", 0)) / 100.0

    rgb = img.convert("RGB")
    w, h = rgb.size
    s = min(w, h)
    left = (w - s) // 2
    top = (h - s) // 2
    square = rgb.crop((left, top, left + s, top + s)).resize(
        (side, side), _LANCZOS)

    inner = max(1, int(side * (1.0 - margin * 2)))
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    if p.get("bg") == "白色":
        canvas.paste((255, 255, 255, 255), (0, 0, side, side))
    elif p.get("bg") == "黑色":
        canvas.paste((0, 0, 0, 255), (0, 0, side, side))

    ss = 4
    big = square.resize((inner * ss, inner * ss), _LANCZOS)
    mask = Image.new("L", big.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, big.size[0] - 1, big.size[1] - 1],
                                 fill=255)
    mask = mask.resize((inner, inner), _LANCZOS)
    circle = square.resize((inner, inner), _LANCZOS).convert("RGBA")
    circle.putalpha(mask)
    off = (side - inner) // 2
    canvas.alpha_composite(circle, (off, off))
    return canvas
