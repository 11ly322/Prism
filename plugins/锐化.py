PLUGIN_NAME = "锐化"
PLUGIN_DESC = "USM 锐化。可调半径、强度与阈值"
PLUGIN_VERSION = "2.0"
PLUGIN_AUTHOR = "Prism"

PLUGIN = {"id": "sharpen", "name": PLUGIN_NAME, "version": PLUGIN_VERSION,
          "api": 2, "author": PLUGIN_AUTHOR}


from PIL import ImageFilter

PARAMS = [
    {"key": "radius", "label": "半径", "min": 0.5, "max": 5,
     "default": 1.4, "step": 0.1},
    {"key": "percent", "label": "强度 %", "min": 10, "max": 300,
     "default": 90, "step": 10},
    {"key": "threshold", "label": "阈值", "min": 0, "max": 20,
     "default": 3, "step": 1},
]


def run(img, **params):
    path = None
    p = params or {}
    return img.convert("RGB").filter(ImageFilter.UnsharpMask(
        radius=float(p.get("radius", 1.4)),
        percent=int(p.get("percent", 90)),
        threshold=int(p.get("threshold", 3))))
