PLUGIN_NAME = "白边框"
PLUGIN_DESC = "四周加边框。可调宽度、颜色与内侧细线"
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

PLUGIN = {"id": "border", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}


from PIL import ImageDraw

PARAMS = [
    {"key": "ratio", "label": "边框宽度", "min": 1, "max": 20,
     "default": 4, "step": 1},
    {"key": "color", "label": "颜色", "type": "choice",
     "choices": ["白色", "黑色", "米白"], "default": "白色"},
    {"key": "line", "label": "内侧细线", "type": "bool", "default": False},
]

_COLORS = {"白色": (255, 255, 255), "黑色": (0, 0, 0), "米白": (246, 243, 236)}


def run(img, **params):
    path = None
    p = params or {}
    out = img.convert("RGB").copy()
    w, h = out.size
    ratio = float(p.get("ratio", 4)) / 100.0
    pad = max(4, int(min(w, h) * ratio))
    col = _COLORS.get(p.get("color"), (255, 255, 255))
    draw = ImageDraw.Draw(out)
    for i in range(pad):
        draw.rectangle([i, i, w - 1 - i, h - 1 - i], outline=col)
    if p.get("line"):
        # 内侧再画一条 1px 的深灰细线，像相框的压边
        draw.rectangle([pad, pad, w - 1 - pad, h - 1 - pad],
                       outline=(90, 90, 90))
    return out
