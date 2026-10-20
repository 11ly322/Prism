# -*- coding: utf-8 -*-
"""Prism 插件模板（api = 2）—— 复制本文件、改名为你的插件名即可。

三步：
1. 另存为 myplugin.py（不要以下划线开头），放进 plugins/ 目录；
2. 改 PLUGIN 与 PARAMS，写 run；
3. Prism 里约 1.5 秒自动热重载，直接就能试 —— 不用重启。
"""

# ============================================================ 1. 元信息
# 前五项必填（id 唯一）。network / writes_files 是能力声明，填了会在
# 插件窗口显示，让用户知道这个插件会不会联网、会不会写文件。
PLUGIN = {
    "id": "myplugin",              # 唯一标识：小写字母数字与 -_，不能以 _ 开头
    "name": "我的插件",             # 插件窗口显示的名字（也可写 {zh,en,ja}）
    "version": "1.0",              # 你的版本号
    "api": 2,                      # 接口版本，当前必须是 2
    "author": "你的名字",
    "description": {"zh": "一句话说明这个插件做什么",
                    "en": "One line about this plugin",
                    "ja": "このプラグインの説明"},   # 也可只写字符串
    "network": False,              # 是否联网（必须如实声明）
    "writes_files": False,         # 是否会写文件
}

# ============================================================ 2. 参数
# 三种控件，key 就是 run 里的关键字参数名，label 是界面标签。
PARAMS = [
    # 数值滑杆：type 写 slider（省略 type 也默认是 slider）
    {
        "key": "amount",           # kwargs 键名
        "label": {"zh": "强度", "en": "Strength", "ja": "強さ"},  # 也可只写字符串
        "type": "slider",
        "min": 0,                  # 最小值
        "max": 100,                # 最大值
        "default": 60,             # 默认值
        "step": 5,                 # 步长
    },
    # 下拉选择：type 写 select，选项放 options（旧的 choices 也兼容）
    {
        "key": "mode",
        "label": "风格",
        "type": "select",
        "options": [{"value": "原样", "label": {"zh": "原样", "en": "As is", "ja": "そのまま"}}, {"value": "偏暖", "label": {"zh": "偏暖", "en": "Warm", "ja": "暖色"}}, {"value": "偏冷", "label": {"zh": "偏冷", "en": "Cool", "ja": "寒色"}}],
        "default": "偏暖",
    },
    # 复选框：type 写 checkbox
    {
        "key": "vignette",
        "label": "加暗角",
        "type": "checkbox",
        "default": False,
    },
    # 文本框：type 写 text，参数是字符串（可以留空）
    {
        "key": "caption",
        "label": "说明文字",
        "type": "text",
        "default": "",
    },
]


# ============================================================ 3. 实现
def run(img, **params):
    """入口函数，固定签名 run(img, **params) -> PIL.Image。

    输入
    ----
    img    : PIL.Image，可能是 RGB / RGBA / L。
             来自「当前图片 + 全部调整」的合成结果（导出级别，可能是原分辨率）。
             **不要原地修改它**，要改先 copy()。
    params : dict，键是 PARAMS 里的 key。类型已按声明转换好：
             slider -> float，select -> str，checkbox -> bool。
             没传的键用 default 补齐。

    输出
    ----
    新的 PIL.Image。尺寸、模式都可以变（裁剪、圆形头像都会变）。

    异常
    ----
    直接抛。Prism 会捕获、写 logs/plugins.log，并提示用户插件执行失败，
    主程序不会崩。不要自己吞异常返回 None，那样作者和用户都不知道出了什么事。
    """
    from PIL import Image, ImageDraw

    amount = float(params.get("amount", 60)) / 100.0
    mode = str(params.get("mode", "偏暖"))
    vignette = bool(params.get("vignette", False))
    caption = str(params.get("caption") or "").strip()

    alpha = None
    if img.mode == "RGBA":
        alpha = img.split()[3]
    rgb = img.convert("RGB")

    w, h = rgb.size
    scale = 1.0
    if max(w, h) > 2048:
        scale = 2048.0 / max(w, h)
        work = rgb.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                          Image.BILINEAR)
    else:
        work = rgb

    tint = {"原样": (1.0, 1.0, 1.0),
            "偏暖": (1.08, 1.00, 0.92),
            "偏冷": (0.94, 1.00, 1.10)}.get(mode, (1.0, 1.0, 1.0))
    r, g, b = work.split()
    r = r.point(lambda v: min(255, int(v * (1.0 + (tint[0] - 1.0) * amount))))
    g = g.point(lambda v: min(255, int(v * (1.0 + (tint[1] - 1.0) * amount))))
    b = b.point(lambda v: min(255, int(v * (1.0 + (tint[2] - 1.0) * amount))))
    out = Image.merge("RGB", (r, g, b))

    if vignette:
        ww, hh = out.size
        mask = Image.new("L", (ww, hh), 0)
        d = ImageDraw.Draw(mask)
        steps = 48
        for i in range(steps):
            k = i / float(steps)
            box = [int(ww * k * 0.5), int(hh * k * 0.5),
                   ww - int(ww * k * 0.5), hh - int(hh * k * 0.5)]
            d.ellipse(box, fill=int(255 * (0.35 + 0.65 * k)))
        out = Image.composite(out, Image.new("RGB", (ww, hh), (0, 0, 0)), mask)

    if caption:
        from PIL import ImageDraw
        d = ImageDraw.Draw(out)
        d.text((int(out.size[0] * 0.02), int(out.size[1] * 0.02)), caption,
               fill=(255, 255, 255))

    if scale != 1.0:
        out = out.resize((w, h), Image.BICUBIC)
    if alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha)
    return out
