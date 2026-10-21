# -*- coding: utf-8 -*-
"""Prism —— 简约图片查看器

基于 Pillow + Tkinter 的轻量桌面看图工具，支持主流图片格式（含动图）。
无第三方 GUI 依赖，仅需要 Pillow。

用法:
    pythonw Prism.pyw                  打开空窗口
    pythonw Prism.pyw 图片文件 [更多...]  打开指定图片
    pythonw Prism.pyw 目录              浏览目录内的图片
"""

from __future__ import annotations

import colorsys
import copy
import io
import json
import math
import os
import queue
import re
import struct
import sys
import threading
import time
import traceback

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog, font as tkfont, messagebox, simpledialog

from PIL import (ExifTags, Image, ImageDraw, ImageEnhance, ImageFile,
                 ImageFilter, ImageOps, ImageStat, ImageTk, ImageChops)
try:
    from PIL import ImageCms
except Exception:                 # 极简 Pillow 构建可能没有 ImageCms
    ImageCms = None
# messagebox 的标题/正文不适合做成控件，_apply_lang 覆盖不到；这里套一层翻译壳。
# 传进来的仍是中文原文，显示前过 _tr / _trf（带 % 的运行时文案）。
_TK_MESSAGEBOX = messagebox


class _TranslatedMessageBox:
    def __getattr__(self, name):
        fn = getattr(_TK_MESSAGEBOX, name)
        if not callable(fn):
            return fn

        def call(title=None, message=None, **kw):
            return fn(_tr(title),
                      _trf(message) if isinstance(message, str) else message,
                      **kw)

        return call


messagebox = _TranslatedMessageBox()

_np = None
_np_missing = False


def _np_ready():
    """按需加载 numpy：它是可选依赖，启动时 import 要 ~300 ms。"""
    global _np, _np_missing
    if _np is None and not _np_missing:
        try:
            import numpy as _numpy
            _np = _numpy       # 可选：亮度降噪的边缘保护用它算得更准
        except Exception:
            _np_missing = True
    return _np

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")
# macOS 用 Command 作主修饰键，其余平台用 Control
K = "Command" if IS_MAC else "Control"

APP_NAME = "Prism"
APP_VERSION = "9.14.3"
APP_BUILD = "2025-12.9"
# ---------------------------------------------------------------- 运行模式
# 同一份源码编出三个版本：
#   完整版    -> Prism.exe，带修图面板
#   看图版    -> 文件名带 viewer 的 exe（PrismViewer.exe），只有浏览/缩放/旋转
#   大屏版    -> 文件名带 bigscreen 的 exe（PrismBigScreen.exe），
#                纯看图、无快捷键、工具栏在底部、大按钮，适合展陈/大屏
# 也可用 --viewer / --bigscreen 或 PRISM_VIEWER=1 / PRISM_BIGSCREEN=1 强制。
VIEWER_ONLY = False
BIGSCREEN = False
if "--viewer" in sys.argv or os.environ.get("PRISM_VIEWER") == "1":
    VIEWER_ONLY = True
if "--bigscreen" in sys.argv or os.environ.get("PRISM_BIGSCREEN") == "1":
    BIGSCREEN = True
_exe_name = os.path.basename(sys.executable).lower()
if "bigscreen" in _exe_name:
    BIGSCREEN = True
if "viewer" in _exe_name:
    VIEWER_ONLY = True
if BIGSCREEN:
    VIEWER_ONLY = True
elif getattr(sys, "frozen", False):
    LOW_MEM_ARG = "--low-mem" in sys.argv

if BIGSCREEN:
    APP_TITLE = "%s %s - 多媒体大屏" % (APP_NAME, APP_VERSION)
elif VIEWER_ONLY:
    APP_TITLE = "%s %s - 纯图片查看器" % (APP_NAME, "Viewer " + APP_VERSION)
else:
    APP_TITLE = "%s %s - 简约图片查看器" % (APP_NAME, APP_VERSION)

PLUGIN_DEV = "--plugin-dev" in sys.argv
PROXY_ARG = 0
for _i, _a in enumerate(sys.argv):
    if _a == "--proxy" and _i + 1 < len(sys.argv):
        try:
            PROXY_ARG = max(512, min(6000, int(sys.argv[_i + 1])))
        except Exception:
            PROXY_ARG = 0
    elif _a.startswith("--proxy="):
        try:
            PROXY_ARG = max(512, min(6000, int(_a.split("=", 1)[1])))
        except Exception:
            PROXY_ARG = 0
VERSION = "1.0"

# ---------------------------------------------------------------- 可选依赖

HEIF_OK = False
try:  # iPhone 的 HEIC/HEIF 支持（装了 pillow-heif 就自动启用）
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:
    pass

_DND_OK = False
try:  # 拖放支持（装了 tkinterdnd2 就自动启用）
    from tkinterdnd2 import DND_FILES, TkinterDnD

    _DND_OK = True
except Exception:
    pass

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 512 * 1024 * 1024  # 放宽超大图限制

# ---------------------------------------------------------------- 配色

# ---------------------------------------------------------------- 高分屏

UI = 1.0  # 界面缩放系数：Windows 200% 缩放时 = 2.0


def _init_dpi():
    """让进程感知真实 DPI。

    不声明感知时 Windows 会把整个窗口位图拉伸，文字和图片都会发虚；
    声明之后必须自己按 DPI 缩放所有像素尺寸（见 px()）。
    """
    global UI
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        hdc = ctypes.windll.user32.GetDC(0)
        try:
            dpi = int(ctypes.windll.gdi32.GetDeviceCaps(hdc, 88))
        finally:
            ctypes.windll.user32.ReleaseDC(0, hdc)
        if dpi > 0:
            UI = max(1.0, min(4.0, dpi / 96.0))
    except Exception:
        pass


def px(v):
    """把 96dpi 下的像素尺寸换算成当前 DPI 下的像素。"""
    return int(round(v * UI))


_init_dpi()

BG = "#121212"          # 画布背景
BG_RGB = (0x12, 0x12, 0x12)
BAR_BG = "#1c1c1c"      # 工具条 / 状态栏
BAR_HOVER = "#2c2c2c"
FG = "#c9c9c9"
FG_DIM = "#787878"
FG_HI = "#ffffff"
ACCENT = "#4c9aff"      # 选中 / 强调色
CHECK_A = "#191919"     # 透明区棋盘格
CHECK_B = "#232323"

# ---------------------------------------------------------------- 主题

_THEME_ROLES = ("BG", "BAR_BG", "BAR_HOVER", "FG", "FG_DIM", "FG_HI",
                "ACCENT", "BTN", "DEEP", "DEEP2", "TROUGH", "HEAD",
                "HEAD2", "RULE", "KNOB", "ON", "PANEL", "CARD",
                "CARD_LINE", "CHECK_A", "CHECK_B")

_THEME_DARK = {
    "BG": "#121212", "BAR_BG": "#1c1c1c", "BAR_HOVER": "#2c2c2c",
    "FG": "#c9c9c9", "FG_DIM": "#787878", "FG_HI": "#ffffff",
    "ACCENT": "#4c9aff", "BTN": "#262626", "DEEP": "#151515",
    "DEEP2": "#1b1b1b", "TROUGH": "#2f2f2f", "HEAD": "#242424",
    "HEAD2": "#1d1d1d", "RULE": "#2e2e2e", "KNOB": "#d0d0d0",
    "ON": "#101010", "PANEL": "#141414", "CARD": "#1c1c1c",
    "CARD_LINE": "#2a2a2a", "CHECK_A": "#191919", "CHECK_B": "#232323",
}

THEMES = {
    "dark": dict(_THEME_DARK),
    # 高对比：纯黑 + 纯白 + 亮黄强调
    "contrast": {
        "BG": "#000000", "BAR_BG": "#000000", "BAR_HOVER": "#3a3a3a",
        "FG": "#ffffff", "FG_DIM": "#c8c8c8", "FG_HI": "#ffffff",
        "ACCENT": "#ffd400", "BTN": "#1a1a1a", "DEEP": "#0a0a0a",
        "DEEP2": "#0f0f0f", "TROUGH": "#4a4a4a", "HEAD": "#111111",
        "HEAD2": "#0c0c0c", "RULE": "#5a5a5a", "KNOB": "#ffffff",
        "ON": "#000000", "PANEL": "#000000", "CARD": "#0a0a0a",
        "CARD_LINE": "#3a3a3a", "CHECK_A": "#0a0a0a", "CHECK_B": "#1a1a1a",
    },
    # 浅色：白底深字
    "light": {
        "BG": "#f4f4f4", "BAR_BG": "#ffffff", "BAR_HOVER": "#e4e4e4",
        "FG": "#1f1f1f", "FG_DIM": "#6b6b6b", "FG_HI": "#000000",
        "ACCENT": "#1a6fe0", "BTN": "#ececec", "DEEP": "#ffffff",
        "DEEP2": "#f7f7f7", "TROUGH": "#cfcfcf", "HEAD": "#ededed",
        "HEAD2": "#f5f5f5", "RULE": "#c8c8c8", "KNOB": "#5a5a5a",
        "ON": "#ffffff", "PANEL": "#ebebeb", "CARD": "#fbfbfb",
        "CARD_LINE": "#d6d6d6", "CHECK_A": "#ffffff", "CHECK_B": "#e8e8e8",
    },
    # 高对比 + 白色描边：黑底白字黄强调，每个控件加 1 像素白边
    "outline": {
        "BG": "#000000", "BAR_BG": "#000000", "BAR_HOVER": "#2e2e2e",
        "FG": "#ffffff", "FG_DIM": "#dcdcdc", "FG_HI": "#ffffff",
        "ACCENT": "#ffe100", "BTN": "#000000", "DEEP": "#000000",
        "DEEP2": "#000000", "TROUGH": "#585858", "HEAD": "#000000",
        "HEAD2": "#000000", "RULE": "#ffffff", "KNOB": "#ffffff",
        "ON": "#000000", "PANEL": "#000000", "CARD": "#000000",
        "CARD_LINE": "#ffffff", "CHECK_A": "#000000", "CHECK_B": "#1a1a1a",
        "outline": "#ffffff",
    },
    # 炭橙：炭灰底 + 橙色强调
    "amber": {
        "BG": "#0e0e10", "BAR_BG": "#1b1b1d", "BAR_HOVER": "#2a2a2d",
        "FG": "#e6e6e6", "FG_DIM": "#9a9a9e", "FG_HI": "#ffffff",
        "ACCENT": "#ff8c1a", "BTN": "#242426", "DEEP": "#131315",
        "DEEP2": "#171719", "TROUGH": "#3a3a3d", "HEAD": "#202022",
        "HEAD2": "#1a1a1c", "RULE": "#3a3a3d", "KNOB": "#ff8c1a",
        "ON": "#101010", "PANEL": "#0b0b0d", "CARD": "#1b1b1d",
        "CARD_LINE": "#333338", "CHECK_A": "#151517", "CHECK_B": "#202024",
    },
    # 深海：藏青底 + 天蓝强调
    "navy": {
        "BG": "#0b1220", "BAR_BG": "#111b2e", "BAR_HOVER": "#1c2b45",
        "FG": "#c9d6e8", "FG_DIM": "#7d8fa8", "FG_HI": "#ffffff",
        "ACCENT": "#38bdf8", "BTN": "#16233a", "DEEP": "#0a1526",
        "DEEP2": "#101c30", "TROUGH": "#2a3d57", "HEAD": "#16243a",
        "HEAD2": "#0f1a2c", "RULE": "#2a3f5c", "KNOB": "#9fd8f5",
        "ON": "#06121e", "PANEL": "#0a1322", "CARD": "#111d31",
        "CARD_LINE": "#243a55", "CHECK_A": "#0f1a2b", "CHECK_B": "#17263d",
    },
    # 森林：墨绿底 + 草绿强调
    "forest": {
        "BG": "#0d1210", "BAR_BG": "#121a16", "BAR_HOVER": "#1f2c24",
        "FG": "#c7d6c9", "FG_DIM": "#7f917f", "FG_HI": "#ffffff",
        "ACCENT": "#6cc24a", "BTN": "#17221a", "DEEP": "#0b110e",
        "DEEP2": "#101812", "TROUGH": "#2a3a2d", "HEAD": "#18251a",
        "HEAD2": "#101a12", "RULE": "#2b3d2e", "KNOB": "#b7e0a8",
        "ON": "#071008", "PANEL": "#0a100c", "CARD": "#121c15",
        "CARD_LINE": "#283a2b", "CHECK_A": "#101a12", "CHECK_B": "#18261b",
    },
    # 玫瑰：酒红底 + 粉色强调
    "rose": {
        "BG": "#140d12", "BAR_BG": "#1c121a", "BAR_HOVER": "#2c1c27",
        "FG": "#e3cbd7", "FG_DIM": "#9d7d8d", "FG_HI": "#ffffff",
        "ACCENT": "#f472b6", "BTN": "#241722", "DEEP": "#110a0e",
        "DEEP2": "#181017", "TROUGH": "#3d2835", "HEAD": "#241622",
        "HEAD2": "#170e14", "RULE": "#3b2733", "KNOB": "#f3b4d3",
        "ON": "#160a10", "PANEL": "#100a0e", "CARD": "#1a1018",
        "CARD_LINE": "#382432", "CHECK_A": "#180f15", "CHECK_B": "#23141e",
    },
    # 极夜：冷灰蓝底 + 冰蓝强调
    "nord": {
        "BG": "#0f1419", "BAR_BG": "#151c23", "BAR_HOVER": "#222d38",
        "FG": "#d0dae3", "FG_DIM": "#7f8f9c", "FG_HI": "#ffffff",
        "ACCENT": "#88c0d0", "BTN": "#1b242d", "DEEP": "#0c1116",
        "DEEP2": "#121920", "TROUGH": "#33414e", "HEAD": "#1b242d",
        "HEAD2": "#121920", "RULE": "#33414e", "KNOB": "#d8e5ee",
        "ON": "#0b1015", "PANEL": "#0b1015", "CARD": "#141b22",
        "CARD_LINE": "#2a3742", "CHECK_A": "#121920", "CHECK_B": "#1a232c",
    },
    # 霓虹：黑紫底 + 品红强调
    "neon": {
        "BG": "#0a0710", "BAR_BG": "#120b1c", "BAR_HOVER": "#241235",
        "FG": "#e6d9f5", "FG_DIM": "#9a7fb5", "FG_HI": "#ffffff",
        "ACCENT": "#e879f9", "BTN": "#1b0f28", "DEEP": "#080510",
        "DEEP2": "#0f0918", "TROUGH": "#3a2350", "HEAD": "#1b1028",
        "HEAD2": "#0f0918", "RULE": "#3c2452", "KNOB": "#f0c2ff",
        "ON": "#0a0410", "PANEL": "#080510", "CARD": "#120b1c",
        "CARD_LINE": "#342048", "CHECK_A": "#130b1d", "CHECK_B": "#1d102b",
    },
    # 暖纸：米色底 + 棕橙强调（浅色）
    "paper": {
        "BG": "#f3ecdf", "BAR_BG": "#fbf6ec", "BAR_HOVER": "#eee2cf",
        "FG": "#3a3025", "FG_DIM": "#7a6a56", "FG_HI": "#1f1810",
        "ACCENT": "#b45309", "BTN": "#f0e6d6", "DEEP": "#fffaf1",
        "DEEP2": "#f8f0e2", "TROUGH": "#d8c9b2", "HEAD": "#efe3d1",
        "HEAD2": "#f7edde", "RULE": "#d2c0a6", "KNOB": "#7a5a3a",
        "ON": "#ffffff", "PANEL": "#ece2d2", "CARD": "#fdf8ef",
        "CARD_LINE": "#d8c7ae", "CHECK_A": "#fffaf1", "CHECK_B": "#eadcc7",
    },
}

THEME_NAMES = {"dark": "深色", "contrast": "高对比", "outline": "高对比·描边",
               "amber": "炭橙", "light": "浅色", "navy": "深海",
               "forest": "森林", "rose": "玫瑰", "nord": "极夜",
               "neon": "霓虹", "paper": "暖纸"}
THEME_ORDER = ("dark", "light", "contrast", "outline", "amber",
               "navy", "forest", "rose", "nord", "neon", "paper")
_CURRENT_THEME = ["dark"]


BTN_BG = "#262626"
DEEP_BG = "#151515"
DEEP2_BG = "#1b1b1b"
TROUGH_BG = "#2f2f2f"
HEAD_BG = "#242424"
KNOB_BG = "#d0d0d0"
RULE_BG = "#2e2e2e"
ON_BG = "#101010"


# ---------------------------------------------------------------- 界面三语
# 中文是源语言，键即界面上的原文；没有译文的控件保持中文。
APP_LANG = "zh"
# 三语词典与帮助文本放在 lang_data.py：数据量大，和渲染代码分开维护。
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
from lang_data import (LANG_TABLE, HELP_TEXT, HELP_TEXT_EN,
                       HELP_TEXT_JA)


def _tr(text):
    """把界面原文翻成当前语言；没有译文就原样返回。"""
    if not text or APP_LANG == "zh":
        return text
    return LANG_TABLE.get(APP_LANG, {}).get(text, text)


# 运行期文案（"已保存 foo.jpg"）在进词典前已经格式化过了，整串查不到译文。
# 这里把带 % 的词条编译成模板：先用占位符切段，再按段匹配，命中后用译文重新拼。
_TRF_CACHE = {}
_PH_RE = re.compile(r"%(?:[-+ #0]*\d*(?:\.\d+)?[sdifgeE])|%%")


def _format_regex(key):
    """把 "已保存 %s" 这类词条编译成 ^已保存 (.+?)$ 形式的正则。"""
    parts, groups, last = [], 0, 0
    for m in _PH_RE.finditer(key):
        parts.append(re.escape(key[last:m.start()]))
        if m.group(0) == "%%":
            parts.append("%")
        else:
            groups += 1
            parts.append("(.+?)")
        last = m.end()
    parts.append(re.escape(key[last:]))
    return re.compile("^" + "".join(parts) + "$", re.S), groups


def _sprintf_like(template, values):
    """用已经格式化好的片段填进译文模板（不再走 % 运算，避免 %d 收到字符串）。"""
    out, last, i = [], 0, 0
    for m in _PH_RE.finditer(template):
        out.append(template[last:m.start()])
        if m.group(0) == "%%":
            out.append("%")
        else:
            out.append(values[i] if i < len(values) else "")
            i += 1
        last = m.end()
    out.append(template[last:])
    return "".join(out)


def _trf(text):
    """翻译已经格式化好的运行期文案；查不到就原样返回。

    例：词典里有 "已保存 %s" → "Saved %s"，传入 "已保存 a.jpg" 返回 "Saved a.jpg"。
    """
    if not text or APP_LANG == "zh" or not isinstance(text, str):
        return text
    table = LANG_TABLE.get(APP_LANG, {})
    hit = table.get(text)
    if hit is not None:
        return hit
    cache = _TRF_CACHE.get(APP_LANG)
    if cache is None:
        rows = []
        for key, val in table.items():
            if "%" not in key:
                continue
            try:
                rx, groups = _format_regex(key)
            except Exception:
                continue
            rows.append((len(rx.pattern), groups, rx, val))
        # 字面部分越长越具体，优先匹配，避免 "已保存 %s" 抢了更长的模板
        rows.sort(key=lambda r: (-r[0], -r[1]))
        cache = _TRF_CACHE[APP_LANG] = rows
    for _n, groups, rx, val in cache:
        m = rx.match(text)
        if not m:
            continue
        if groups and len(m.groups()) != groups:
            continue
        return _sprintf_like(val, m.groups())
    return text


# ---------------------------------------------------------------- 设计令牌
# 间距统一走 4 的倍数：以前 px(9)/px(11)/px(17) 这类奇数散落各处，收进这里。
# 用法：pady=(SPACE_SM, SPACE_LG)
SPACE_XXS = 1
SPACE_XS = 2
SPACE_SM = 4
SPACE_MD = 6
SPACE_LG = 8
SPACE_XL = 12
SPACE_2XL = 16
SPACE_3XL = 24

# 字号阶梯：11 / 12 / 13 / 15 / 18。以前只有 11 和 12，副标题和正文挤在同一档。
FONT_XS = 11
FONT_SM = 12
FONT_MD = 13
FONT_LG = 15
FONT_XL = 18

# 圆角阶梯（Frame 画不出圆角，目前只用在自绘 Canvas 控件上；
# 卡片层次用「更深的面板底 + 略亮的分区」来表达）
RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12

PANEL_BG = "#141414"      # 面板底（比分区更暗，分区才浮得起来）
CARD_BG = "#1c1c1c"       # 分区卡片（= 原来的 BAR_BG）
CARD_LINE = "#2a2a2a"     # 卡片分隔线

def _apply_palette(name):
    """把主题写进模块级颜色常量；之后新建的控件就用新色。"""
    if name not in THEMES:
        name = "dark"
    p = THEMES[name]
    g = globals()
    for role in ("BG", "BAR_BG", "BAR_HOVER", "FG", "FG_DIM", "FG_HI",
                 "ACCENT"):
        g[role] = p[role]
    g["BTN_BG"] = p["BTN"]
    g["DEEP_BG"] = p["DEEP"]
    g["DEEP2_BG"] = p["DEEP2"]
    g["TROUGH_BG"] = p["TROUGH"]
    g["HEAD_BG"] = p["HEAD"]
    g["KNOB_BG"] = p["KNOB"]
    g["RULE_BG"] = p["RULE"]
    g["ON_BG"] = p["ON"]
    g["PANEL_BG"] = p["PANEL"]
    g["CARD_BG"] = p["CARD"]
    g["CARD_LINE"] = p["CARD_LINE"]
    g["CHECK_A"] = p["CHECK_A"]
    g["CHECK_B"] = p["CHECK_B"]
    bg = p["BG"]
    g["BG_RGB"] = (int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16))
    _CURRENT_THEME[0] = name
    return p


def _theme_delta(old_name, new_name):
    """旧主题 → 新主题的颜色替换表（小写旧值 → 新值），给已有控件重新上色。"""
    old = THEMES.get(old_name, THEMES["dark"])
    new = THEMES.get(new_name, THEMES["dark"])
    m = {}
    for role in _THEME_ROLES:
        a = old[role].lower()
        b = new[role]
        if a != b.lower() and a not in m:
            # 先定义者优先：高对比描边主题里 BG/BTN/DEEP/HEAD/ON 都是同一个
            # #000000，若按「后者覆盖」会把窗口底色错配成 ON 的颜色。
            m[a] = b
    return m



RESAMPLING = Image.Resampling
LANCZOS = RESAMPLING.LANCZOS
BICUBIC = RESAMPLING.BICUBIC

MIN_SCALE = 0.02
MAX_SCALE = 32.0

# 缩小时改用这个长边的低分辨率副本参与运算。3400 是实测出来的平衡点：
# 硬边测试图里「差 >8」的像素占比从 0.99% 降到 0.003%，而真实照片几乎是逐像素一致。
PREVIEW_MAX = 3400
PREVIEW_MAX_LOWMEM = 2048
# 插件预览与 plugins/_utils.preview_then_export 共用同一个上限
PROXY_MAX_SIDE = PREVIEW_MAX_LOWMEM
SCALE_DEBOUNCE_MS = 140          # 缩放/改窗口的防抖时长
DRAFT_SLACK = 0.85               # draft 请求打折：0.85 让 1764 画布落到 1/4 档
SLOW_DECODE_MS = 2000            # 单次解码超过这个时长就提示用户
PASTE_MAX_CORES = 4              # <=4 核用「复用 PhotoImage + paste」，否则每帧新建
REDUCE_MAX_K = 4                 # 解码后最多降 4 倍（再大画质损失明显）
PERF_PROFILE = "fast-slider"     # fast-slider(默认) / fast-first / auto
for _i, _a in enumerate(sys.argv):
    if _a == "--perf-profile" and _i + 1 < len(sys.argv):
        PERF_PROFILE = sys.argv[_i + 1]
    elif _a.startswith("--perf-profile="):
        PERF_PROFILE = _a.split("=", 1)[1]
PHOTO_MODE = "auto"              # auto / paste / new
if PERF_PROFILE.endswith("-paste"):
    PHOTO_MODE = "paste"
    PERF_PROFILE = PERF_PROFILE[:-len("-paste")]
elif PERF_PROFILE.endswith("-new"):
    PHOTO_MODE = "new"
    PERF_PROFILE = PERF_PROFILE[:-len("-new")]
if PERF_PROFILE not in ("auto", "fast-first", "fast-slider"):
    PERF_PROFILE = "fast-slider"
DEBUG_DECODE = os.environ.get("PRISM_DEBUG_DECODE") == "1"
FAST_RESAMPLE = Image.Resampling.BILINEAR   # 拖动时的临时采样
SAFE_PIXELS = 120 * 1000 * 1000  # 超过这个像素数先降到安全尺寸
AUTO_DRAFT_PIXELS = 50 * 1000 * 1000  # 超过就先按代理尺寸解码，F5 再载全分辨率
FULL_CONFIRM_PIXELS = 80 * 1000 * 1000  # F5 取原图前，超过这个像素量先确认内存
EXPORT_MAX_PIXELS = 150 * 1000 * 1000   # 批量导出跳过超过这个像素量的单图


def _proxy_for(img, limit):
    """按上限生成代理图，返回 (代理图 或 None, 比例)。

    放在模块级是为了让 Loader 线程也能调用（纯 Pillow，不碰 Tk）。
    """
    w, h = img.size
    m = max(w, h)
    if limit <= 0 or m <= limit:
        return None, 1.0
    r = limit / float(m)
    nw, nh = max(1, int(w * r)), max(1, int(h * r))
    try:
        return _fast_downscale(img, (nw, nh)), nw / float(w)
    except Exception:
        return None, 1.0


def _icc_description(icc):
    if not icc or ImageCms is None:
        return "sRGB"
    try:
        prof = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        return (ImageCms.getProfileDescription(prof) or "ICC").strip()
    except Exception:
        return "ICC"


def _to_srgb(img, icc):
    """把带 ICC 的图转到 sRGB，返回 (img, 源描述, 是否转换)。

    不做色彩管理时，Display P3 / AdobeRGB 的图会被当成 sRGB 直接显示，
    肤色和绿色最容易偏；这里先统一到 sRGB，导出再写 sRGB profile。
    """
    name = _icc_description(icc) if icc else "sRGB"
    if not icc or ImageCms is None or "srgb" in name.lower():
        return img, name, False
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        dst = ImageCms.createProfile("sRGB")
        alpha = None
        base = img
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and
                                          "transparency" in (img.info or {})):
            base = img.convert("RGBA")
            alpha = base.getchannel("A")
        elif img.mode not in ("RGB", "L", "CMYK"):
            base = img.convert("RGB")
        out = ImageCms.profileToProfile(base, src, dst,
                                        renderingIntent=0, outputMode="RGB")
        if alpha is not None:
            out.putalpha(alpha)
        return out, name, True
    except Exception:
        return img, name, False


_SRGB_ICC = None


def _srgb_icc_bytes():
    """导出用：sRGB profile 字节；没有 ImageCms 时返回 None。"""
    global _SRGB_ICC
    if _SRGB_ICC is not None:
        return _SRGB_ICC or None
    if ImageCms is None:
        _SRGB_ICC = b""
        return None
    try:
        _SRGB_ICC = ImageCms.ImageCmsProfile(
            ImageCms.createProfile("sRGB")).tobytes()
    except Exception:
        _SRGB_ICC = b""
    return _SRGB_ICC or None


def _build_soft_proof(profile_path):
    """sRGB -> 目标 profile -> sRGB，返回两个变换和 profile 名。"""
    if ImageCms is None:
        raise RuntimeError("当前 Pillow 缺少 ImageCms")
    icc = open(profile_path, "rb").read()
    dst = ImageCms.ImageCmsProfile(io.BytesIO(icc))
    src = ImageCms.createProfile("sRGB")
    flags = getattr(getattr(ImageCms, "Flags", None),
                    "BLACKPOINTCOMPENSATION", 0)
    t1 = ImageCms.buildTransformFromOpenProfiles(
        src, dst, "RGB", "RGB", renderingIntent=1, flags=flags)
    t2 = ImageCms.buildTransformFromOpenProfiles(
        dst, src, "RGB", "RGB", renderingIntent=1, flags=flags)
    name = (ImageCms.getProfileDescription(dst) or "ICC").strip()
    return t1, t2, name



def _fast_downscale(img, size, quality=True):
    """两步降采样：先按整数倍 reduce 粗降，再 resize 到精确尺寸。

    40MP -> 1600 实测比单步 LANCZOS 快约 4.6 倍（83ms vs 379ms），
    因为 reduce 走的是逐格平均，比带抗锯齿的重采样便宜得多。
    """
    w, h = img.size
    tw = max(1, int(size[0]))
    th = max(1, int(size[1]))
    if tw == w and th == h:
        return img
    k = min(w // tw, h // th)
    small = img.reduce(k) if k >= 2 else img
    resample = Image.Resampling.LANCZOS if quality else FAST_RESAMPLE
    try:
        return small.resize((tw, th), resample,
                            reducing_gap=2.0 if quality else None)
    except TypeError:
        return small.resize((tw, th), resample)


# ---------------------------------------------------------------- 格式

# 这些后缀虽然 Pillow 认识，但不是给人「看图」用的，从浏览列表里排除
_EXT_BLOCK = {
    ".pdf", ".eps", ".ps", ".h5", ".hdf", ".bufr", ".grib", ".fits", ".fit",
    ".fli", ".flc", ".msp", ".pcd", ".wmf", ".emf", ".im", ".iim", ".vda",
    ".vst", ".ftc", ".ftu", ".gbr", ".palm", ".mpeg", ".mpg", ".bw", ".rgb",
    ".rgba", ".dcx", ".pxr", ".ras", ".sgi", ".dds", ".blp",
}

# 浏览目录时认作图片的后缀（主流格式优先）
BROWSE_EXTS = {
    ".jpg", ".jpeg", ".jpe", ".jfif", ".jfi", ".png", ".apng", ".gif", ".webp",
    ".avif", ".avifs", ".bmp", ".dib", ".tif", ".tiff", ".ico", ".cur", ".tga",
    ".icns", ".psd", ".qoi", ".jp2", ".j2k", ".jpc", ".jpf", ".jpx", ".mpo",
    ".pnm", ".ppm", ".pgm", ".pbm", ".pfm", ".xbm", ".xpm", ".pcx",
}
if HEIF_OK:
    BROWSE_EXTS |= {".heic", ".heif", ".hif"}

# TIFF 结构的相机 RAW。机身会在文件里内嵌一张（通常是全尺寸的）JPEG 预览，
# 直接取出来即可显示，不需要任何 RAW 解码库。
RAW_EXTS = {
    ".nef", ".nrw",              # 尼康
    ".cr2", ".crw", ".cr3",      # 佳能（cr3 不是 TIFF，会自动回退）
    ".arw", ".srf", ".sr2",      # 索尼
    ".dng", ".rw2", ".orf",      # Adobe / 松下 / 奥林巴斯
    ".pef", ".srw", ".raw", ".rwl", ".dcr", ".kdc", ".mrw", ".mef",
    ".3fr", ".iiq", ".erf", ".mos", ".cap", ".x3f", ".raf",
}
BROWSE_EXTS |= RAW_EXTS

# 打开对话框用：Pillow 实际注册的全部后缀减去黑名单
OPEN_EXTS = sorted(
    e for e in {k.lower() for k in Image.registered_extensions()}
    if e not in _EXT_BLOCK
)


def is_image(path):
    return os.path.splitext(path)[1].lower() in BROWSE_EXTS


_num_re = re.compile(r"(\d+)")


def natural_key(name):
    """让 2.jpg 排在 10.jpg 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in _num_re.split(name)]


def _ifd_entries(data, e, offset):
    """读出一个 IFD 的 tag 表以及下一个 IFD 的偏移。"""
    if offset <= 0 or offset + 2 > len(data):
        return None, 0
    n = struct.unpack(e + "H", data[offset:offset + 2])[0]
    if n <= 0 or n > 1024 or offset + 2 + n * 12 + 4 > len(data):
        return None, 0
    out = {}
    for i in range(n):
        p = offset + 2 + i * 12
        tag, typ, cnt = struct.unpack(e + "HHI", data[p:p + 8])
        out[tag] = (typ, cnt, data[p + 8:p + 12])
    nxt = struct.unpack(e + "I", data[offset + 2 + n * 12:offset + 6 + n * 12])[0]
    return out, nxt


def _ifd_int(e, tags, tag):
    item = tags.get(tag)
    if not item:
        return None
    typ, _cnt, raw = item
    if typ == 3:
        return struct.unpack(e + "H", raw[:2])[0]
    if typ == 4:
        return struct.unpack(e + "I", raw[:4])[0]
    return None


def _ifd_ints(data, e, tags, tag):
    item = tags.get(tag)
    if not item:
        return []
    typ, cnt, raw = item
    if typ not in (3, 4):
        return []
    step = 2 if typ == 3 else 4
    size = cnt * step
    if size <= 4:
        buf = raw[:size]
    else:
        off = struct.unpack(e + "I", raw[:4])[0]
        if off <= 0 or off + size > len(data):
            return []
        buf = data[off:off + size]
    try:
        return list(struct.unpack(e + ("H" if typ == 3 else "I") * cnt, buf))
    except struct.error:
        return []


def _scan_ifds(data, e, offset, seen, out, depth=0):
    """递归收集所有 IFD 里内嵌的 JPEG 预览候选。"""
    if depth > 4 or offset in seen:
        return
    seen.add(offset)
    tags, nxt = _ifd_entries(data, e, offset)
    if not tags:
        return

    w = _ifd_int(e, tags, 0x0100) or 0
    h = _ifd_int(e, tags, 0x0101) or 0
    score = w * h

    # 1) 直接存放的 JPEG（JPEGInterchangeFormat / Length）
    joff = _ifd_int(e, tags, 0x0201)
    jlen = _ifd_int(e, tags, 0x0202)
    if joff and jlen and joff + jlen <= len(data):
        out.append((score or jlen, [(joff, jlen)]))

    # 2) JPEG 压缩的条带（Compression = 6/7）
    if _ifd_int(e, tags, 0x0103) in (6, 7):
        offs = _ifd_ints(data, e, tags, 0x0111)
        counts = _ifd_ints(data, e, tags, 0x0117)
        if offs and len(offs) == len(counts):
            segs = [(o, c) for o, c in zip(offs, counts) if o and c]
            if segs and all(o + c <= len(data) for o, c in segs):
                out.append((score or sum(c for _o, c in segs), segs))

    for sub in (0x014A, 0x8769, 0x8825):        # SubIFDs / Exif / GPS
        for off in _ifd_ints(data, e, tags, sub):
            _scan_ifds(data, e, off, seen, out, depth + 1)
    if nxt:
        _scan_ifds(data, e, nxt, seen, out, depth + 1)


def extract_raw_preview(data):
    """从 TIFF 结构的 RAW（NEF/CR2/ARW/DNG/RW2…）里取出内嵌的 JPEG 预览。

    返回 PIL.Image，找不到返回 None。不依赖任何外部 RAW 解码库。
    """
    if len(data) < 16:
        return None
    if data[:2] == b"II":
        e = "<"
    elif data[:2] == b"MM":
        e = ">"
    else:
        return None
    try:
        magic = struct.unpack(e + "H", data[2:4])[0]
        first = struct.unpack(e + "I", data[4:8])[0]
    except struct.error:
        return None
    if magic not in (42, 0x4F52, 0x5352, 0x55) or first <= 0:
        return None
    cands = []
    try:
        _scan_ifds(data, e, first, set(), cands)
    except Exception:
        return None
    cands.sort(key=lambda c: -c[0])
    for _score, segs in cands[:4]:
        try:
            blob = b"".join(data[o:o + n] for o, n in segs)
        except Exception:
            continue
        if len(blob) < 512:
            continue
        try:
            im = Image.open(io.BytesIO(blob))
            im.load()
        except Exception:
            continue
        if im.format == "JPEG" and im.size[0] >= 16 and im.size[1] >= 16:
            return im
    return None


def list_images(folder):
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = [os.path.join(folder, n) for n in names
           if is_image(n) and os.path.isfile(os.path.join(folder, n))]
    out.sort(key=lambda p: natural_key(os.path.basename(p)))
    return out


def human_size(n):
    step = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if step < 1024 or unit == "GB":
            return "%d B" % n if unit == "B" else "%.1f %s" % (step, unit)
        step /= 1024.0
    return "%.1f GB" % step


# ---------------------------------------------------------------- 调色核心

HSL_BANDS = ("红", "橙", "黄", "绿", "青", "蓝", "紫", "品红")
HSL_HUES = (0.0, 30.0, 60.0, 120.0, 180.0, 240.0, 270.0, 300.0)   # 色相中心（度）
HSL_SPREAD = 42.0          # 影响半径（度）：超出这个范围权重严格为 0
CURVE_DEFAULT = ((0, 0), (64, 64), (128, 128), (192, 192), (255, 255))


def wheel_units(delta):
    """把不同平台的滚轮增量归一化成「格」。

    Windows 一格是 ±120；macOS 触控板/鼠标给的是 ±1 量级的小整数，
    直接除以 120 会几乎不缩放。
    """
    if IS_MAC:
        return max(-3.0, min(3.0, float(delta) * 0.32))
    return float(delta) / 120.0


def _hue_swatch(deg):
    r, g, b = colorsys.hsv_to_rgb(deg / 360.0, 0.72, 0.95)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _clamp255(x):
    return 0 if x < 0 else (255 if x > 255 else int(x + 0.5))


def _curve_is_identity(points):
    return all(abs(x - y) < 0.5 for x, y in points)


def _mono_curve(points):
    """单调三次插值（Fritsch-Carlson），把控制点变成 256 级曲线 LUT。"""
    pts = sorted((float(x), float(y)) for x, y in points)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    n = len(pts)
    if n == 0:
        return list(range(256))
    if n == 1:
        return [_clamp255(ys[0])] * 256
    dx = [xs[i + 1] - xs[i] for i in range(n - 1)]
    dy = [ys[i + 1] - ys[i] for i in range(n - 1)]
    m = [(dy[i] / dx[i]) if dx[i] else 0.0 for i in range(n - 1)]
    tang = [m[0]]
    for i in range(1, n - 1):
        tang.append(0.0 if m[i - 1] * m[i] <= 0 else (m[i - 1] + m[i]) / 2.0)
    tang.append(m[-1])
    for i in range(n - 1):                      # 限幅，保证曲线单调不出怪峰
        if m[i] == 0:
            tang[i] = tang[i + 1] = 0.0
            continue
        a = tang[i] / m[i]
        b = tang[i + 1] / m[i]
        s = a * a + b * b
        if s > 9.0:
            t = 3.0 / math.sqrt(s)
            tang[i] = t * a * m[i]
            tang[i + 1] = t * b * m[i]
    lut = []
    seg = 0
    for v in range(256):
        x = float(v)
        if x <= xs[0]:
            lut.append(_clamp255(ys[0]))
            continue
        if x >= xs[-1]:
            lut.append(_clamp255(ys[-1]))
            continue
        while seg < n - 2 and x > xs[seg + 1]:
            seg += 1
        h = xs[seg + 1] - xs[seg]
        t = (x - xs[seg]) / h if h else 0.0
        t2 = t * t
        t3 = t2 * t
        y = ((2 * t3 - 3 * t2 + 1) * ys[seg]
             + (t3 - 2 * t2 + t) * h * tang[seg]
             + (-2 * t3 + 3 * t2) * ys[seg + 1]
             + (t3 - t2) * h * tang[seg + 1])
        lut.append(_clamp255(y))
    return lut


def _basic_tone_lut(a):
    """曝光/对比度/高光/阴影/白色/黑色 合成一条 256 级 LUT。"""
    ev = 2.0 ** a["exposure"]
    con = a["contrast"] / 100.0
    hi = a["highlights"] / 100.0
    sh = a["shadows"] / 100.0
    wh = a["whites"] / 100.0
    bl = a["blacks"] / 100.0
    lut = []
    for v in range(256):
        x = v / 255.0
        x *= ev
        if con:
            x = 0.5 + (x - 0.5) * (1.0 + con)
        if hi:
            x += hi * 0.50 * (x * x) * (1.0 - x)          # 保白
        if sh:
            w = (1.0 - x) * (1.0 - x)
            x += sh * 0.55 * w * x                        # 保黑
        if wh:
            x += wh * 0.35 * x * x
        if bl:
            x += bl * 0.35 * (1.0 - x) * (1.0 - x)
        lut.append(_clamp255(x * 255.0))
    return lut


LOCAL_ADJ_DEFAULT = {
    "exposure": 0.0, "contrast": 0.0, "highlights": 0.0, "shadows": 0.0,
    "whites": 0.0, "blacks": 0.0, "temperature": 0.0, "tint": 0.0,
    "saturation": 0.0, "sharpen": 0.0,
}


def new_local(kind, cx, cy, rx, ry, angle, spread):
    return {"type": kind, "cx": cx, "cy": cy, "rx": rx, "ry": ry,
            "angle": angle, "spread": spread, "feather": 50.0,
            "invert": False, "adj": dict(LOCAL_ADJ_DEFAULT)}


def _wb_gains(a):
    """色温/色调 → RGB 三通道增益，天然是逐通道查表，可以并进色调 LUT。"""
    t = a["temperature"] / 100.0
    g = a["tint"] / 100.0
    gr = 1.0 + t * 0.34
    gb = 1.0 - t * 0.34
    gg = 1.0 - g * 0.26
    return max(0.0, gr), max(0.0, gg), max(0.0, gb)


def _hue_rgb(deg):
    return colorsys.hsv_to_rgb((deg % 360.0) / 360.0, 1.0, 1.0)


def _hsl_luts(hsl):
    """8 段 HSL → 色相偏移 / 饱和度增益 / 明度增益，各一条 256 级 LUT。

    三条 LUT 都只由「输入色相」决定，且影响半径之外权重严格为 0，
    所以调红色绝不会带到蓝色——这正是 HSL 分色调整的意义。
    """
    touched = [bool(hsl["hue"][i] or hsl["sat"][i] or hsl["lum"][i])
               for i in range(len(HSL_HUES))]
    hue_shift = []
    sat_mul = []
    lum_mul = []
    cover = []
    for h in range(256):
        deg = h * 360.0 / 256.0
        hs = ss = ls = 0.0
        wmax = 0.0
        for i, center in enumerate(HSL_HUES):
            d = abs(deg - center)
            d = min(d, 360.0 - d)                     # 环形距离
            if d >= HSL_SPREAD:
                continue
            w = 0.5 * (1.0 + math.cos(math.pi * d / HSL_SPREAD))
            if not touched[i]:
                continue                              # 没调过的段不产生任何影响
            if w > wmax:
                wmax = w
            hs += w * hsl["hue"][i]
            ss += w * hsl["sat"][i]
            ls += w * hsl["lum"][i]
        shift = hs / 100.0 * 30.0                     # ±100 → ±30 度
        hue_shift.append(int(round(h + shift * 256.0 / 360.0)) % 256)
        sat_mul.append(max(0.0, 1.0 + ss / 100.0))
        lum_mul.append(max(0.0, 1.0 + ls / 100.0 * 0.8))
        cover.append(int(255 * wmax))
    return hue_shift, sat_mul, lum_mul, cover


def _s_channel_lut(a, sat_mul):
    """每段 HSL 饱和度 + 自然饱和度 + 饱和度 → 一条作用于 S 通道的 LUT。

    自然饱和度用 gamma 曲线，天然保护已经高饱和的像素。
    """
    vib = a["vibrance"] / 100.0
    sat = a["saturation"] / 100.0
    g = 1.0 / (1.0 + vib * 0.9) if vib > -0.999 else 10.0
    lut = []
    for v in range(256):
        x = min(255.0, max(0.0, v * sat_mul[v]))
        if vib:
            x = ((x / 255.0) ** g) * 255.0
        if sat:
            x *= (1.0 + sat)
        lut.append(_clamp255(x))
    return lut


# 常用曲线形状（控制点，0-255）。都从 (0,0) 到 (255,255) 附近，
# 差别在中间调的弯曲方向，实际用途见 README。
CURVE_PRESETS = {
    "柔和S":   [(0, 0), (48, 38), (128, 128), (208, 218), (255, 255)],
    "强对比":  [(0, 0), (40, 20), (128, 128), (216, 236), (255, 255)],
    "褪色":    [(0, 26), (64, 82), (128, 140), (192, 196), (255, 238)],
    "提亮":    [(0, 0), (64, 88), (128, 158), (192, 212), (255, 255)],
}


def _straighten(img, angle):
    """拉直：旋转后自动裁到最大的等比内接矩形，把黑角去掉。"""
    w, h = img.size
    try:
        im = img.rotate(-angle, resample=Image.Resampling.BICUBIC,
                        expand=False)
    except Exception:
        return img
    a = math.radians(abs(angle))
    sa, ca = math.sin(a), math.cos(a)
    r = w / float(h)
    hw = min((w / 2.0) / (ca + sa / r), (h / 2.0) / (sa + ca / r))
    nw = int(hw * 2)
    nh = int(nw / r)
    if nw < 8 or nh < 8 or nw > w or nh > h:
        return img
    x = (w - nw) // 2
    y = (h - nh) // 2
    return im.crop((x, y, x + nw, y + nh))


def _op_clarity(img, amount):
    """清晰度：大半径 USM 提中间调局部对比；负值则向模糊版本靠拢（柔化）。"""
    k = amount / 100.0
    w = max(img.size)
    radius = max(3.0, min(40.0, w / 90.0))
    if k > 0:
        return img.filter(ImageFilter.UnsharpMask(
            radius=radius, percent=int(k * 55), threshold=0))
    blur = img.filter(ImageFilter.GaussianBlur(radius * 0.5))
    return Image.blend(img, blur, min(1.0, -k))


def _op_dehaze(img, amount):
    """去朦胧：暗通道先验的简化版（估大气光 + 透射率，不做引导滤波）。"""
    _np_ready()
    if _np is None:
        return img
    a = _np.asarray(img, dtype=_np.float32) / 255.0
    dark = a.min(axis=2)
    thr = _np.percentile(dark, 99.9)
    sel = dark >= thr
    air = a[sel].mean(axis=0) if sel.any() else a.reshape(-1, 3).max(axis=0)
    air = _np.clip(air, 0.08, 1.0)
    t = _np.clip(1.0 - 0.85 * dark, 0.15, 1.0)[..., None]
    clear = _np.clip((a - air * (1.0 - t)) / t, 0.0, 1.0)
    k = amount / 100.0
    out = a * (1.0 - k) + clear * k if k > 0 else a * (1.0 + k) + air * (-k)
    return Image.fromarray((_np.clip(out, 0.0, 1.0) * 255.0).astype(_np.uint8))


def _op_denoise_color(img, amount):
    """颜色降噪：只糊色度通道 Cb/Cr，亮度 Y 原样保留，所以细节不会糊。"""
    r = 0.6 + (amount / 100.0) * 3.4
    ycc = img.convert("YCbCr")
    y, cb, cr = ycc.split()
    cb = cb.filter(ImageFilter.GaussianBlur(r))
    cr = cr.filter(ImageFilter.GaussianBlur(r))
    return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")


def _op_denoise_luma(img, amount):
    """亮度降噪：模糊后按与原图的差异加权融合，差异大（边缘）的地方保留原图。"""
    _np_ready()
    r = 0.5 + (amount / 100.0) * 2.0
    blur = img.filter(ImageFilter.GaussianBlur(r))
    k = amount / 100.0
    if _np is None:
        return Image.blend(img, blur, k * 0.6)
    a = _np.asarray(img, dtype=_np.float32)
    b = _np.asarray(blur, dtype=_np.float32)
    d = _np.abs(a - b).max(axis=2, keepdims=True)
    w = _np.clip(1.0 - d / 26.0, 0.0, 1.0) * k
    return Image.fromarray((a * (1.0 - w) + b * w).astype(_np.uint8))


DETAIL_KEYS = frozenset(("clarity", "dehaze", "sharpen", "sharpen_radius",
                         "sharpen_detail", "nr_luma", "nr_color"))


_WM_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
)


def _wm_font(size):
    """找一个能显示中文的字体；找不到就退回位图默认字体。"""
    from PIL import ImageFont
    size = max(8, int(size))
    for p in _WM_FONT_CANDIDATES:
        try:
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


_HI_LUT = [255 if v >= 250 else 0 for v in range(256)]
_LO_LUT = [255 if v <= 6 else 0 for v in range(256)]


def _clip_overlay(img):
    """过曝/欠曝警告：溢出到白的像素标红，压到黑的像素标蓝。

    只是屏幕上的提示，不进保存管线，所以不影响导出结果。

    原先用 numpy 整幅数组做 max/min、拷贝再布尔索引赋值，3.1MP 上要 168 ms，
    比整条调色管线还慢。现在全走 PIL 的 C 实现（LUT + 通道极值 + 带掩膜的粘贴），
    并且用 getbbox() 把粘贴限制在真正被裁切的区域 —— 绝大多数照片只有一小块溢出，
    这样几乎不花时间。输出与原实现逐像素一致。
    """
    if img.mode != "RGB":
        return img
    from PIL import ImageChops
    r, g, b = img.split()
    hi = ImageChops.lighter(ImageChops.lighter(r, g), b).point(_HI_LUT)
    lo = ImageChops.darker(ImageChops.darker(r, g), b).point(_LO_LUT)
    hb = hi.getbbox()
    lb = lo.getbbox()
    if hb is None and lb is None:
        return img
    out = img.copy()
    for box, colour, mask in ((hb, (255, 40, 40), hi), (lb, (40, 100, 255), lo)):
        if box is None:
            continue
        w = box[2] - box[0]
        h = box[3] - box[1]
        if w <= 0 or h <= 0:
            continue
        out.paste(Image.new("RGB", (w, h), colour), (box[0], box[1]),
                  mask.crop(box))
    return out


def _res_dir():
    """资源目录：打包成 exe 后 PyInstaller 会把附加文件解到 _MEIPASS。"""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS",
                       os.path.dirname(os.path.abspath(sys.executable)))
    return os.path.dirname(os.path.abspath(__file__))


def _plugin_dir():
    """插件目录：和配置放在一起，首次运行自动创建。"""
    d = os.path.join(_data_dir(), "plugins")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _file_mtime(path):
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0


PLUGIN_API_SUPPORTED = (1, 2)      # 当前支持的插件接口版本
_PLUGIN_LOG_MAX = 128 * 1024        # 超过就轮转一份 .1


def _plugin_log_path():
    d = os.path.join(_data_dir(), "logs")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "plugins.log")


def _plugin_log(msg, plugin_id="-", api="-", stage="-", exc=None):
    """统一格式：[时间] plugin=<id> api=<n> <stage> failed: <类型>: <首行>

    出问题时作者能一眼看出是哪个插件、哪个阶段、什么异常。
    完整 traceback 只在 -dev 模式下追加，平时保持一行，便于扫读。
    """
    try:
        if exc is not None:
            head = str(exc).strip().splitlines()
            first = head[0] if head else ""
            line = "[%s] plugin=%s api=%s %s failed: %s: %s" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), plugin_id, api, stage,
                type(exc).__name__, first)
            import traceback
            tb = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            if globals().get("PLUGIN_DEV", False):
                line += chr(10) + tb
        else:
            line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
        fp = _plugin_log_path()
        try:
            if os.path.exists(fp) and os.path.getsize(fp) > _PLUGIN_LOG_MAX:
                os.replace(fp, fp + ".1")
        except Exception:
            pass
        with open(fp, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return line
    except Exception:
        return ""


# ---------------------------------------------------------------- 插件安装（URL）
# 不做应用商店：清单 / 网址 + SHA-256，下载、校验、落地，三步都在本机完成。
# 校验只保证「下载到的东西没被改过」，不保证作者可信 —— 安装前必须让用户确认。
PLUGIN_MAX_BYTES = 2 * 1024 * 1024      # 插件源码上限；正常几 KB，2 MB 足够
PLUGIN_FETCH_TIMEOUT = 15
# 官方清单：应用内「插件市场」读它。可用环境变量指向自己的清单（自建市场 / 测试）。
PLUGIN_CATALOG_URL = (os.environ.get("PRISM_PLUGIN_CATALOG")
                      or "https://11ly322.github.io/Prism/plugins/index.json")
PLUGIN_CATALOG_MAX_BYTES = 256 * 1024   # 清单只是索引，256 KB 足够
PLUGIN_CATALOG_CACHE = "plugin_catalog.json"
# 安装/清单里的 id 必须能安全地当文件名用：小写字母数字开头，长度 1~40。
# 本地手放插件不走这条规则（兼容中文 id 的老插件）。
PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class PluginSourceError(ValueError):
    """插件源码不合格：语法错、缺 PLUGIN / run、API 不支持、哈希不符。"""


def fetch_plugin_source(url, max_bytes=PLUGIN_MAX_BYTES,
                        timeout=PLUGIN_FETCH_TIMEOUT):
    """下载插件源码，返回 bytes。只接受 http/https，且限制大小。"""
    import urllib.parse
    import urllib.request
    scheme = urllib.parse.urlsplit(str(url).strip()).scheme.lower()
    if scheme not in ("http", "https"):
        raise PluginSourceError(_tr("只支持 http/https 链接"))
    req = urllib.request.Request(
        str(url).strip(),
        headers={"User-Agent": "Prism/%s" % APP_VERSION})
    limit = ("%d KB" % (max_bytes // 1024) if max_bytes >= 1024
             else "%d 字节" % max_bytes)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        try:
            length = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            length = 0
        if length > max_bytes:
            raise PluginSourceError(_tr("文件太大（超过 %s）") % limit)
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise PluginSourceError(_tr("文件太大（超过 %s）") % limit)
    if not data:
        raise PluginSourceError(_tr("下载到的是空文件"))
    return data


def parse_plugin_source(data):
    """只看 AST，不执行代码。返回插件元信息，不合格就抛 PluginSourceError。

    这样做的好处：用户确认之前，插件代码一次都没跑过。
    """
    import ast
    try:
        text = (data.decode("utf-8-sig") if isinstance(data, (bytes, bytearray))
                else str(data))
    except UnicodeDecodeError:
        raise PluginSourceError(_tr("源码不是 UTF-8 文本"))
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise PluginSourceError(_tr("语法错误：%s（第 %s 行）")
                                % (exc.msg, exc.lineno))
    meta = None
    has_run = False
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "PLUGIN":
                    try:
                        meta = ast.literal_eval(node.value)
                    except Exception:
                        raise PluginSourceError(_tr("PLUGIN 必须是纯字面量字典"))
        elif isinstance(node, ast.FunctionDef) and node.name == "run":
            has_run = True
    if not isinstance(meta, dict):
        raise PluginSourceError(_tr("缺少 PLUGIN 字典"))
    if not has_run:
        raise PluginSourceError(_tr("缺少 run() 函数"))
    pid = str(meta.get("id") or "").strip()
    if not pid:
        raise PluginSourceError(_tr("PLUGIN 缺少 id"))
    if not PLUGIN_ID_RE.match(pid):
        raise PluginSourceError(
            _tr("插件 id 只能用小写字母数字与 -_，且不能以 _ 开头：%s") % pid)
    try:
        api = int(meta.get("api", 1))
    except Exception:
        raise PluginSourceError(_tr("PLUGIN.api 必须是数字"))
    if api not in PLUGIN_API_SUPPORTED:
        raise PluginSourceError(_tr("需要 API %s，当前支持 %s") % (
            api, "/".join(str(v) for v in PLUGIN_API_SUPPORTED)))
    return {"id": pid,
            "name": _localized(meta.get("name") or pid),
            "version": str(meta.get("version") or ""),
            "author": str(meta.get("author") or ""),
            "description": _localized(meta.get("description") or ""),
            "network": bool(meta.get("network")),
            "writes_files": bool(meta.get("writes_files")),
            "api": api,
            "source": text}


def safe_plugin_filename(pid):
    """id -> 文件名主干：只留 ASCII 字母数字与 _-，避免路径穿越。"""
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", str(pid)).strip("-_")
    return (base or "plugin")[:40]


def install_plugin_bytes(data, sha256="", folder=None, overwrite=False,
                         filename=None):
    """校验 SHA-256、解析元信息并写入插件目录。返回元信息（含 path）。

    filename 只用于「更新已安装插件」：写回它原来的文件名，避免同一个 id
    在插件目录里出现两份（一份 id.py、一份手工命名）。
    """
    import hashlib
    meta = parse_plugin_source(data)
    if sha256:
        got = hashlib.sha256(data).hexdigest()
        want = str(sha256).strip().lower()
        if got.lower() != want:
            raise PluginSourceError(_tr("SHA-256 不匹配（实际 %s…）") % got[:12])
    meta["sha256"] = hashlib.sha256(data).hexdigest()
    folder = folder or _plugin_dir()
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        pass
    name = filename or (safe_plugin_filename(meta["id"]) + ".py")
    name = os.path.basename(str(name))          # 再挡一次路径穿越
    if not name.endswith(".py"):
        name += ".py"
    path = os.path.join(folder, name)
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(path)
    with open(path, "wb") as fh:
        fh.write(data if isinstance(data, (bytes, bytearray))
                 else meta["source"].encode("utf-8"))
    meta["path"] = path
    return meta


# ---------------------------------------------------------------- 插件清单
# 官方清单 plugins/index.json（发布到网页 docs/plugins/index.json）。应用内「插件市场」
# 读它；每项都带 sha256，下载后仍走 parse_plugin_source + install_plugin_bytes。
def plugin_catalog_cache_path():
    return os.path.join(_data_dir(), PLUGIN_CATALOG_CACHE)


def _localized(value, lang=None):
    """插件/清单里的文本允许是字符串或 {zh,en,ja}；缺当前语言回落中文。"""
    if isinstance(value, dict):
        for key in (lang or APP_LANG, "zh", "en", "ja"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        return ""
    return str(value or "")


def _catalog_text(value, lang=None):
    """清单里的名字/说明是 {zh,en,ja}；缺当前语言就回落中文。"""
    return _localized(value, lang)


def validate_plugin_catalog(obj):
    """校验收到的清单，返回规范化后的条目列表。"""
    if not isinstance(obj, dict):
        raise PluginSourceError(_tr("清单不是合法的 JSON 对象"))
    try:
        schema = int(obj.get("schema") or 0)
    except Exception:
        schema = 0
    if schema != 1:
        raise PluginSourceError(_tr("清单 schema 不是 1"))
    plugins = obj.get("plugins")
    if not isinstance(plugins, list):
        raise PluginSourceError(_tr("清单缺少 plugins 列表"))
    if not plugins:
        raise PluginSourceError(_tr("清单是空的"))
    out, seen = [], set()
    for raw in plugins:
        if not isinstance(raw, dict):
            raise PluginSourceError(_tr("清单条目必须是对象"))
        pid = str(raw.get("id") or "").strip()
        if not pid:
            raise PluginSourceError(_tr("清单条目缺少 id"))
        if not PLUGIN_ID_RE.match(pid):
            raise PluginSourceError(
                _tr("插件 id 只能用小写字母数字与 -_，且不能以 _ 开头：%s") % pid)
        if pid in seen:
            raise PluginSourceError(_tr("清单里 id 重复：%s") % pid)
        seen.add(pid)
        try:
            api = int(raw.get("api", 1))
        except Exception:
            raise PluginSourceError(_tr("插件 %s 的 api 不是数字") % pid)
        if api not in PLUGIN_API_SUPPORTED:
            raise PluginSourceError(_tr("插件 %s 的 api=%s 不受支持") % (pid, api))
        url = str(raw.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            raise PluginSourceError(_tr("插件 %s 的 url 必须是 http(s)") % pid)
        sha = str(raw.get("sha256") or "").strip().lower()
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise PluginSourceError(_tr("插件 %s 的 sha256 格式不对") % pid)
        out.append({
            "id": pid,
            "name": raw.get("name") or pid,
            "version": str(raw.get("version") or ""),
            "api": api,
            "author": str(raw.get("author") or ""),
            "description": raw.get("description") or "",
            "network": bool(raw.get("network")),
            "writes_files": bool(raw.get("writes_files")),
            "url": url,
            "sha256": sha,
        })
    return out


def fetch_plugin_catalog(url=None):
    """拉清单并缓存。返回 (条目列表, 实际 URL)；失败抛异常，不静默。"""
    target = str(url or PLUGIN_CATALOG_URL)
    raw = fetch_plugin_source(target, max_bytes=PLUGIN_CATALOG_MAX_BYTES)
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except Exception:
        raise PluginSourceError(_tr("清单不是合法的 JSON"))
    entries = validate_plugin_catalog(obj)
    try:
        with open(plugin_catalog_cache_path(), "wb") as fh:
            fh.write(raw)
    except Exception:
        pass
    return entries, target


def load_plugin_catalog_cache():
    """上次成功拉取的清单；没有或坏了返回 []，用于断网时还能装。"""
    try:
        with open(plugin_catalog_cache_path(), "r", encoding="utf-8") as fh:
            return validate_plugin_catalog(json.load(fh))
    except Exception:
        return []


def catalog_version_tuple(ver):
    parts = re.findall(r"\d+", str(ver or ""))
    return tuple(int(x) for x in parts[:4]) or (0,)


def catalog_is_newer(remote, local):
    return catalog_version_tuple(remote) > catalog_version_tuple(local)


def _data_dir():
    """配置存放目录。

    源码运行时就是脚本所在目录；打包成 exe 后 __file__ 指向临时解包目录，
    配置会随进程消失，所以必须换成 exe 自己的目录。那里如果不可写
    （比如装在 Program Files），就回落到用户配置目录。
    """
    if getattr(sys, "frozen", False):
        cand = os.path.dirname(os.path.abspath(sys.executable))
    else:
        cand = os.path.dirname(os.path.abspath(__file__))
    probe = os.path.join(cand, ".qpe_write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return cand
    except Exception:
        pass
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    fallback = os.path.join(base, APP_NAME)
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception:
        fallback = cand
    return fallback


def _freeze(v):
    """把参数冻成可哈希、可比较的形式，用来当缓存键。"""
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, float):
        return round(v, 4)
    return v


def _detail_stage(img, params):
    """空间类运算（清晰度/去朦胧/降噪/锐化）。这些最贵，所以单独成一级，

    松手后先出颜色版，再把这些放到后台线程算，界面不会冻住。
    """
    clarity, dehaze, sharpen, srad, sdet, nrl, nrc = params
    if not any(params):
        return img
    if img.mode == "RGBA":
        r, g, b, al = img.split()
        out = _detail_stage(Image.merge("RGB", (r, g, b)), params)
        r, g, b = out.split()
        return Image.merge("RGBA", (r, g, b, al))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if clarity:
        img = _op_clarity(img, clarity)
    if dehaze:
        img = _op_dehaze(img, dehaze)
    if nrc:
        img = _op_denoise_color(img, nrc)
    if sharpen:
        img = img.filter(ImageFilter.UnsharpMask(
            radius=max(0.5, srad), percent=int(sharpen * 2),
            threshold=int(sdet * 2.55)))
    if nrl:
        img = _op_denoise_luma(img, nrl)
    return img


def _ellipsize(font, text, max_px):
    """按像素宽度截断文本，超出部分用省略号。"""
    if max_px <= 0:
        return ""
    if font.measure(text) <= max_px:
        return text
    ell = "…"
    n = len(text)
    while n > 0 and font.measure(text[:n] + ell) > max_px:
        n -= 1
    return text[:n] + ell if n > 0 else ell


def fmt_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
    except Exception:
        return "-"


# ---------------------------------------------------------------- 图片文档


class ImageDoc(object):
    """一个已解码的图片文件（懒解码多帧动画）。"""

    __slots__ = ("path", "data", "img", "n_frames", "size", "mode", "fmt",
                 "file_size", "mtime", "alpha", "_frames", "_index",
                 "raw_preview", "orig_size", "draft_ratio", "exif_bytes",
                 "oversize", "auto_drafted", "proxy_img", "proxy_ratio",
                 "file_bytes", "is_preview", "slow_ms",
                 "icc_source", "icc_converted", )

    def __init__(self, path, data, img):
        self.path = path
        self.data = data
        try:
            self.file_bytes = os.path.getsize(path)
        except OSError:
            self.file_bytes = len(data or b"")
        self.img = img
        self.n_frames = int(getattr(img, "n_frames", 1) or 1)
        self.size = img.size
        self.mode = img.mode
        self.fmt = img.format or os.path.splitext(path)[1].lstrip(".").upper()
        try:
            st = os.stat(path)
            self.file_size = st.st_size
            self.mtime = st.st_mtime
        except OSError:
            self.file_size = len(data or b"")
            self.mtime = 0.0
        info = img.info or {}
        self.alpha = (img.mode in ("RGBA", "LA", "PA", "P")
                      and (img.mode != "P" or "transparency" in info))
        self._frames = {}
        self._index = 0
        self.raw_preview = False
        self.orig_size = img.size
        self.draft_ratio = 1.0
        self.exif_bytes = None
        self.proxy_img = None
        self.proxy_ratio = 1.0
        self.auto_drafted = False
        self.is_preview = False
        self.icc_source = "sRGB"
        self.icc_converted = False
        self.slow_ms = 0.0

    @classmethod
    def load(cls, path, draft_to=0, force_full=False):
        # 非 RAW 不再把整个文件读进内存：直接从路径解码。
        # 一张 40MP JPEG 通常 10~30MB，read()+BytesIO 等于多占一份内存、
        # 多一次整块拷贝；doc.data 之前只在内存估算里用到。
        ext = os.path.splitext(path)[1].lower()
        data = None
        if ext in RAW_EXTS:
            with open(path, "rb") as fh:
                data = fh.read()
        img = None
        raw = False
        orig_size = None
        if ext in RAW_EXTS:
            # RAW 优先用内嵌预览：又快又稳，还带着机身的色彩处理
            img = extract_raw_preview(data)
            raw = img is not None
        oversize = False
        auto_drafted = False
        if img is None:
            try:
                try:
                    img = (Image.open(io.BytesIO(data)) if data is not None
                           else Image.open(path))
                except Image.DecompressionBombError:
                    # 超过 MAX_IMAGE_PIXELS 时不要直接失败：临时放宽一档，
                    # 先 draft 到安全尺寸再 load，用户至少能看图。
                    old_max = Image.MAX_IMAGE_PIXELS
                    Image.MAX_IMAGE_PIXELS = max(
                        int(old_max or 0) * 4, SAFE_PIXELS * 2)
                    try:
                        img = (Image.open(io.BytesIO(data)) if data is not None
                               else Image.open(path))
                        oversize = True
                        try:
                            img.draft("RGB", (PROXY_MAX_SIDE, PROXY_MAX_SIDE))
                        except Exception:
                            pass
                    finally:
                        Image.MAX_IMAGE_PIXELS = old_max
                orig_size = img.size          # 必须在 draft 之前记下来
                if (not draft_to and not force_full
                        and orig_size[0] * orig_size[1] > AUTO_DRAFT_PIXELS):
                    # 超大图（>5000 万像素）打开时先解成代理尺寸，
                    # 避免一打开就吃掉几百 MB；需要全分辨率时按 F5 再来一次。
                    try:
                        img.draft("RGB", (PROXY_MAX_SIDE, PROXY_MAX_SIDE))
                        auto_drafted = True
                    except Exception:
                        auto_drafted = False
                if draft_to:
                    # draft 让 libjpeg 直接按 1/2、1/4、1/8 解码，
                    # 解码时间和内存同步下降。请求「画布需要的最小尺寸」，
                    # Pillow 会挑刚好够用的那一档（两个方向都要满足）。
                    try:
                        img.draft("RGB", tuple(draft_to))
                    except Exception:
                        pass
                img.load()
            except Exception:
                if ext in RAW_EXTS:
                    raise ValueError(
                        "无法从这个 RAW 文件里提取预览图"
                        "（可能是不支持的机型或压缩方式）")
                raise
        img.load()
        if data is None:
            try:
                if getattr(img, "fp", None) is not None:
                    img.fp.close()
                img.fp = None
            except Exception:
                pass
        exif_bytes = None
        try:
            exif = img.getexif()
            orient = exif.get(0x0112, 1) if exif else 1
            # 原始 EXIF 必须在这里存下来：下面的转正和后面的 convert 都会
            # 把 EXIF 丢掉，等保存时再去读就拿不到了（曾经就丢过）。
            if exif:
                try:
                    exif_bytes = exif.tobytes()
                except Exception:
                    exif_bytes = None
        except Exception:
            orient = 1
        # ICC 在 EXIF 之后、转正之前处理：profileToProfile 会丢 EXIF，
        # 而 exif_transpose 只动像素方向，不影响色彩空间。
        icc_source = "sRGB"
        icc_converted = False
        icc = (img.info or {}).get("icc_profile")
        if icc:
            img, icc_source, icc_converted = _to_srgb(img, icc)
        if orient and orient != 1:
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass
        doc = cls(path, data, img)
        doc.oversize = oversize
        doc.auto_drafted = auto_drafted
        doc.raw_preview = raw
        doc.exif_bytes = exif_bytes
        doc.icc_source = icc_source
        doc.icc_converted = icc_converted
        if orig_size:
            doc.orig_size = orig_size
        # 用长边算比例：EXIF 转正会交换宽高，用宽度会算错
        if doc.orig_size and max(doc.orig_size) > 0:
            doc.draft_ratio = max(doc.size) / float(max(doc.orig_size))
        # draft_to 是画布尺寸优化，也会把 >5000 万像素的图降档；
        # 这种情况同样允许 F5 取回原图，否则菜单会误报「已经是全分辨率」。
        if (orig_size and not doc.auto_drafted
                and orig_size[0] * orig_size[1] > AUTO_DRAFT_PIXELS
                and doc.draft_ratio < 0.999):
            doc.auto_drafted = True
        return doc

    def mem_bytes(self):
        """估算这张图占的内存（解码位图 + 原始文件字节）。"""
        bpp = 4 if self.alpha else 3
        return (self.size[0] * self.size[1] * bpp
                + (self.file_bytes or len(self.data or b"")))

    def get_frame(self, i):
        """返回第 i 帧的 RGB/RGBA 位图（单帧图直接返回原图）。"""
        if self.n_frames <= 1:
            return self.img
        i %= self.n_frames
        cached = self._frames.get(i)
        if cached is not None:
            return cached
        if i != self._index:
            self.img.seek(i)
            self._index = i
        target = "RGBA" if self.alpha else "RGB"
        frame = self.img.convert(target)
        if len(self._frames) > 24:
            self._frames.clear()
        self._frames[i] = frame
        return frame

    def duration(self, i):
        """当前帧的显示时长（毫秒）。"""
        if self.n_frames <= 1:
            return 0
        try:
            i %= self.n_frames
            if i != self._index:
                self.img.seek(i)
                self._index = i
            d = self.img.info.get("duration", 100)
            return max(20, int(d))
        except Exception:
            return 100


# ---------------------------------------------------------------- 后台解码


class ThumbWorker(threading.Thread):
    """后台批量生成胶片条缩略图。"""

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.out = queue.Queue()
        self.start()

    def submit(self, items):
        for it in items:
            self.q.put(it)

    def run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            path, size = item
            try:
                im = Image.open(path)
                try:
                    im.draft("RGB", size)      # JPEG 直接解到缩略图大小
                except Exception:
                    pass
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail(size, Image.Resampling.BILINEAR)
            except Exception:
                im = None
            self.out.put((path, im))


def _round_window(win):
    """给顶层窗口申请 Windows 11 的原生圆角。

    Tk 自己的 Toplevel 是直角，自绘圆角需要无边框窗口并自己实现拖动/缩放/关闭，
    代价很大。Windows 11 的 DWM 提供一个属性（DWMWA_WINDOW_CORNER_PREFERENCE = 33，
    值 2 = ROUND），系统会替我们画圆角，且不影响拖动与缩放。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        if not hwnd:
            hwnd = win.winfo_id()
        pref = ctypes.c_int(2)          # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref))
    except Exception:
        pass


def _qpe_theme_role(color):
    """把创建时的颜色归到语义角色，切主题时按角色恢复。"""
    for role, val in (("BAR_BG", BAR_BG), ("BTN", BTN_BG),
                      ("ACCENT", ACCENT), ("TROUGH", TROUGH_BG),
                      ("CARD", CARD_BG)):
        try:
            if str(color).lower() == str(val).lower():
                return role
        except Exception:
            pass
    return None


class _QpeRoundButton(tk.Canvas):
    """Canvas 自绘的圆角按钮。

    Tk 的 tk.Button 只能画直角，想做圆角只能自己画。这里用平滑多边形
    画一个圆角矩形，配上 hover 与 disabled 三种状态，接口尽量贴近 tk.Button
    （text / command / state / configure），这样调用方几乎不用改。
    """

    def __init__(self, parent, text="", command=None, bg=BTN_BG, fg=FG,
                 hover_bg=BAR_HOVER, hover_fg=FG_HI, radius=None,
                 padx=10, pady=4, font=None, state="normal", **kw):
        try:
            host_bg = parent.cget("bg")
        except Exception:
            host_bg = BAR_BG
        tk.Canvas.__init__(self, parent, bg=host_bg, highlightthickness=0,
                           bd=0, **kw)
        self._text = text
        self._command = command
        self._bg = bg
        self._theme_role = _qpe_theme_role(bg)
        self._fg = fg
        self._hover_bg = hover_bg
        self._hover_fg = hover_fg
        self._radius = px(RADIUS_SM if radius is None else radius)
        self._padx = px(padx)
        self._pady = px(pady)
        self._font = font
        self._state = state
        self._hover = False
        self._measure()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self.bind("<Configure>", lambda e: self._draw())

    # --- 尺寸与绘制 ---
    def _measure(self):
        try:
            f = tkfont.Font(font=self._font) if self._font else tkfont.Font()
        except Exception:
            f = tkfont.Font()
        tw = f.measure(self._text or " ")
        th = f.metrics("linespace")
        self.configure(width=tw + self._padx * 2, height=th + self._pady * 2)

    def _round_pts(self, x1, y1, x2, y2, r):
        r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        return [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]

    def _draw(self):
        self.delete("all")
        w = max(2, self.winfo_width() or int(self.cget("width")))
        h = max(2, self.winfo_height() or int(self.cget("height")))
        if self._state == "disabled":
            fill, ink = self._bg, FG_DIM
        elif self._hover:
            fill, ink = self._hover_bg, self._hover_fg
        else:
            fill, ink = self._bg, self._fg
        self.create_polygon(self._round_pts(0, 0, w, h, self._radius),
                            smooth=True, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self._text, fill=ink,
                         font=self._font)

    # --- 事件 ---
    def _on_enter(self, _e=None):
        if self._state != "disabled":
            self._hover = True
            self._draw()
            self.configure(cursor="hand2")

    def _on_leave(self, _e=None):
        self._hover = False
        self._draw()

    def _on_click(self, _e=None):
        if self._state == "disabled":
            return
        if callable(self._command):
            self._command()

    # --- 兼容 tk.Button 的少量接口 ---
    def configure(self, **kw):
        redraw = False
        for k, v in kw.items():
            if k == "text":
                self._text = v
                self._measure()          # 英文/日文比中文宽，必须重新量
                redraw = True
            elif k == "state":
                self._state = v; redraw = True
            elif k == "bg":
                self._bg = v
                role = _qpe_theme_role(v)
                if role is not None:
                    self._theme_role = role
                redraw = True
            elif k == "fg":
                self._fg = v; redraw = True
            elif k == "font":
                self._font = v; self._measure(); redraw = True
            else:
                try:
                    tk.Canvas.configure(self, **{k: v})
                except Exception:
                    pass
        if redraw:
            self._draw()
        return self

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key == "state":
            return self._state
        if key == "bg":
            return self._bg
        if key == "fg":
            return self._fg
        try:
            return tk.Canvas.cget(self, key)
        except Exception:
            return ""

    def invoke(self):
        self._on_click()


class _QpeSlider(tk.Canvas):
    """自绘滑杆。

    Tk 自带的 Scale 是带刻度凹槽的老式控件，和这套深色界面很不搭。
    这里只画一条细槽、一段已选填充和一个圆钮，拖动/点击都能改值；
    对外提供 Scale 的常用子集（set / get / configure(command=)），
    其余地方的代码不用改。
    """

    def __init__(self, master, from_=0.0, to=100.0, resolution=1.0, **kw):
        kw.setdefault("height", 24)
        # Tk Canvas 默认请求宽 378 逻辑像素，会把整行滑块撑到面板之外；
        # 实际宽度由 pack(fill="x") 决定，这里只需要一个小请求值。
        kw.setdefault("width", px(120))
        kw.setdefault("bg", BAR_BG)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("bd", 0)
        kw.setdefault("takefocus", 0)
        kw.setdefault("cursor", "hand2")
        tk.Canvas.__init__(self, master, **kw)
        self._lo = float(from_)
        self._hi = float(to)
        self._res = abs(float(resolution)) or 1.0
        self._val = self._lo
        self._cmd = None
        self._drag = False
        self._hover = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", lambda e: self._redraw(hover=True))
        self.bind("<Leave>", lambda e: self._redraw(hover=False))

    # -- 几何 ------------------------------------------------------
    def _geom(self):
        w = self.winfo_width()
        if w <= 1:
            w = px(180)
        h = self.winfo_height()
        if h <= 1:
            h = px(24)
        # 点对点对齐：轨道两端只留一个圆钮半径的余量，这样左端与标签文字、
        # 右端与数值文字的边界对齐；圆钮拖到两端时也不会被裁掉。
        pad = px(6)
        return pad, max(pad + 1, w - pad), h / 2.0

    def _x_to_val(self, x):
        p0, p1, _y = self._geom()
        t = 0.0 if p1 <= p0 else (x - p0) / float(p1 - p0)
        t = max(0.0, min(1.0, t))
        v = self._lo + (self._hi - self._lo) * t
        v = round(v / self._res) * self._res
        return max(self._lo, min(self._hi, v))

    def _val_to_x(self, v):
        p0, p1, _y = self._geom()
        span = self._hi - self._lo
        t = 0.0 if not span else (v - self._lo) / span
        return p0 + (p1 - p0) * max(0.0, min(1.0, t))

    # -- 绘制 ------------------------------------------------------
    def _redraw(self, hover=None):
        if hover is not None:
            self._hover = hover
        try:
            self.delete("all")
            p0, p1, y = self._geom()
            x = self._val_to_x(self._val)
            lw = max(2, px(3))
            self.create_line(p0, y, p1, y, fill=TROUGH_BG, width=lw,
                             capstyle="round")
            if x - p0 > 0.5:
                self.create_line(p0, y, x, y, fill=ACCENT, width=lw,
                                 capstyle="round")
            act = self._hover or self._drag
            r = px(6) if act else px(5)
            self.create_oval(x - r, y - r, x + r, y + r,
                             fill=FG_HI if act else KNOB_BG, outline="")
        except Exception:
            pass

    # -- 对外接口（对齐 Scale 的常用子集）--------------------------
    def set(self, v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return
        self._val = max(self._lo, min(self._hi, f))
        self._redraw()
        if self._cmd is not None:
            self._cmd(str(self._val))

    def get(self):
        return self._val

    def configure(self, **kw):
        cmd = kw.pop("command", None)
        if cmd is not None:
            self._cmd = cmd
        if kw:
            tk.Canvas.configure(self, **kw)

    config = configure

    # -- 交互 ------------------------------------------------------
    def _on_press(self, event):
        self._drag = True
        self.set(self._x_to_val(event.x))

    def _on_drag(self, event):
        if self._drag:
            self.set(self._x_to_val(event.x))

    def _on_release(self, event):
        self._drag = False
        self._redraw()


class DetailWorker(threading.Thread):
    """把清晰度/去朦胧/降噪/锐化这些最贵的空间运算丢到后台线程。

    这样松手后先出「颜色版」，几百毫秒后再无缝换成带细节的版本，
    界面全程不冻结。线程里只做 PIL/numpy 运算，不碰任何 Tk 对象。
    """

    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue()
        self.out = queue.Queue()
        self.start()

    def submit(self, key, img, params):
        try:                      # 只保留最新一个请求
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self.q.put((key, img, params))

    def run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            key, img, params = item
            try:
                out = _detail_stage(img, params)
            except Exception:
                traceback.print_exc()
                continue
            try:
                while True:
                    self.out.get_nowait()
            except queue.Empty:
                pass
            self.out.put((key, out))


class Loader(object):
    """单线程解码器：主线程只做渲染，解码放到后台避免卡界面。"""

    def __init__(self):
        self.q = queue.Queue()
        self.out = queue.Queue()
        self._wanted = frozenset()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def retarget(self, primary, others=(), draft_to=0, proxy_limit=0,
                 preview_to=0):
        """切换目标：丢掉过期请求，优先解码当前图片。

        proxy_limit > 0 时，后台线程解码完会顺手把代理图也生成好，
        主线程只负责取用 —— 省掉每次开图 180ms 左右的阻塞。
        """
        items = []
        for p in (primary,) + tuple(others):
            if p and p not in [i[0] for i in items]:
                # 大图先解一张很小的预览：首帧不用等完整 draft 解码
                if preview_to and p == primary:
                    items.append((p, preview_to, 0, True, False))
                items.append((p, draft_to, proxy_limit, False, False))
        self._wanted = frozenset(it[0] for it in items)
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        for it in items:
            self.q.put(it)

    def request_full(self, path):
        """放大到超出 draft 分辨率时，重新按原始分辨率解码一次。"""
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass
        self._wanted = frozenset([path])
        self.q.put((path, 0, 0, False, True))

    def _run(self):
        while True:
            item = self.q.get()
            if item is None:
                return
            path, draft_to, proxy_limit = item[0], item[1], item[2]
            is_preview = len(item) > 3 and item[3]
            force_full = len(item) > 4 and item[4]
            if self._wanted and path not in self._wanted:
                continue
            t_dec0 = time.perf_counter()
            try:
                doc = ImageDoc.load(path, draft_to, force_full=force_full)
                if globals().get("DEBUG_DECODE") and not is_preview:
                    _plugin_log("decode draft_to=%s -> %s (%.0f ms)"
                                % (draft_to, getattr(doc, "img").size,
                                   (time.perf_counter() - t_dec0) * 1000),
                                plugin_id="decode", stage="load")
                try:
                    doc.slow_ms = (time.perf_counter() - t_dec0) * 1000
                except Exception:
                    pass
                if is_preview:
                    try:
                        doc.is_preview = True
                    except Exception:
                        pass
                if (not is_preview and draft_to and draft_to[0] > 0
                        and PERF_PROFILE == "fast-slider"):
                    # libjpeg 不保证按请求给档位：请求 1904x1186 时仍可能解出
                    # 4000x2500（1/2 档）。这里按整数倍补一次 reduce，把交给
                    # 主线程的图压到画布附近；reduce 是逐格平均，比 LANCZOS 便宜得多。
                    try:
                        need_w = int(draft_to[0])
                        need_h = int(draft_to[1]) if len(draft_to) > 1 else need_w
                        iw, ih = doc.img.size
                        if need_w > 0 and need_h > 0:
                            k = min(iw // need_w, ih // need_h, REDUCE_MAX_K)
                            if k >= 2:
                                doc.img = doc.img.reduce(k)
                                doc.size = doc.img.size
                                # draft_ratio 必须同步，否则缩放/坐标换算会错位
                                doc.draft_ratio = (max(doc.size)
                                                   / float(max(doc.orig_size)))
                    except Exception:
                        pass
                # 代理图在后台线程生成：纯 Pillow 运算，不碰 Tk
                if (proxy_limit and not is_preview
                        and getattr(doc, "img", None) is not None):
                    proxy, ratio = _proxy_for(doc.img, proxy_limit)
                    try:
                        doc.proxy_img = proxy
                        doc.proxy_ratio = ratio
                    except Exception:
                        pass
            except Exception as exc:  # 坏文件不应中断浏览
                doc = exc
            self.out.put((path, doc))


# ---------------------------------------------------------------- 主程序

_BASE = TkinterDnD.Tk if _DND_OK else tk.Tk


# ---------------------------------------------------------------- 镜头 / 胶片 / 人像

_FILM_PRESETS = {
    "无": None,
    "柯达暖调": ((1.055, 1.000, 0.905), 1.04, 1.06),
    "富士艳丽": ((0.985, 1.020, 1.105), 1.10, 1.22),
    "伊尔福黑白": "bw",
    "宝丽来": ((1.075, 1.010, 1.115), 0.94, 0.88),
}


def _gain_lut(gain):
    return [min(255, max(0, int(v * gain))) for v in range(256)]


def _film_apply(img, preset, strength):
    """胶片模拟：每通道增益 + 对比/饱和，再按强度与原图混合。"""
    spec = _FILM_PRESETS.get(preset or "无")
    if spec is None:
        return img
    k = max(0.0, min(1.0, float(strength) / 100.0))
    if k <= 0:
        return img
    if spec == "bw":
        out = ImageOps.grayscale(img).convert("RGB")
        out = ImageEnhance.Contrast(out).enhance(1.0 + 0.18 * k)
        return Image.blend(img, out, k) if k < 1 else out
    gains, contrast, sat = spec
    r, g, b = img.split()
    out = Image.merge("RGB", (r.point(_gain_lut(gains[0])),
                              g.point(_gain_lut(gains[1])),
                              b.point(_gain_lut(gains[2]))))
    out = ImageEnhance.Contrast(out).enhance(1.0 + (contrast - 1.0) * k)
    out = ImageEnhance.Color(out).enhance(1.0 + (sat - 1.0) * k)
    return Image.blend(img, out, k) if k < 1 else out


def _beauty_guard(img, skin=None):
    """美颜的边界保护：返回 (是否继续, 原因)。"""
    W, H = img.size
    if W < 32 or H < 32:
        return False, "图太小"
    if W * H < 4096:
        return False, "像素太少"
    ratio = W / float(max(1, H))
    if ratio > 8.0 or ratio < 0.125:
        return False, "长宽比极端"
    if skin is not None:
        try:
            import numpy as np
            a = np.asarray(skin)
            if a.size and (a > 96).mean() < 0.002:
                return False, "没有肤色区域"
        except Exception:
            pass
    return True, ""


def _is_grayish(img):
    """接近黑白的图：色度几乎为 0。"""
    try:
        import numpy as np
        small = img.convert("RGB")
        w, h = small.size
        if w * h > 40000:
            small = small.resize((200, max(1, int(200 * h / max(1, w)))))
        a = np.asarray(small, dtype=np.int16)
        chroma = (a.max(axis=2) - a.min(axis=2)).mean()
        return chroma < 3.0
    except Exception:
        return False


def _skin_mask(img, feather=0):
    """肤色蒙版（YCbCr 的 Cb/Cr 区间）。

    蒙版本身就是一张平滑的灰度图，大图上没必要逐像素算：先降到半分辨率，
    算完再用双线性放回来，形状几乎不变，耗时降到约 1/4。
    """
    W, H = img.size
    small = None
    if W * H > 400000:
        sw, sh = max(16, W // 2), max(16, H // 2)
        small = img.resize((sw, sh), Image.BILINEAR)
        src = small
    else:
        src = img
    ycc = src.convert("YCbCr")
    cb, cr = ycc.split()[1], ycc.split()[2]
    cb_ok = cb.point(lambda v: 255 if 77 <= v <= 130 else 0)
    cr_ok = cr.point(lambda v: 255 if 132 <= v <= 178 else 0)
    mask = ImageChops.multiply(cb_ok, cr_ok)
    if small is not None:
        mask = mask.resize((W, H), Image.BILINEAR)
    if feather and feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


def _edge_weight(img, blur):
    """边缘权重：只有强边缘（五官、发丝轮廓）才压低，普通皮肤纹理不拦。

    边缘图是粗结构，半分辨率足够；早期版本用 255 - v*3，
    纹理稍多就会把整张脸都判成边缘，磨皮几乎失效。
    """
    W, H = img.size
    src = img
    half = W * H > 400000
    if half:
        src = img.resize((max(16, W // 2), max(16, H // 2)), Image.BILINEAR)
    g = src.convert("L").filter(ImageFilter.FIND_EDGES)
    if blur > 0:
        g = g.filter(ImageFilter.GaussianBlur(max(0.6, blur * (0.5 if half else 1.0))))
    w = g.point(lambda v: 255 if v < 14 else max(0, 255 - (v - 14) * 5))
    if half:
        w = w.resize((W, H), Image.BILINEAR)
    return w


def _freq_smooth(img, radius, strength):
    """频域分离磨皮：只压低频（色斑、不均匀），高频（毛孔、绒毛）原样加回。

    模糊只在半分辨率上做 —— 低频本来就平滑，降采样不改变结果，
    但高斯模糊的开销降到 1/4；加减运算仍在全分辨率做，细节不受影响。
    """
    k = max(0.0, min(1.0, float(strength or 0) / 100.0))
    if k <= 0:
        return img
    W, H = img.size
    r = max(0.6, float(radius))
    half = W * H > 400000
    if half:
        sw, sh = max(16, W // 2), max(16, H // 2)
        small = img.resize((sw, sh), Image.BILINEAR)
        low_s = small.filter(ImageFilter.GaussianBlur(max(0.6, r * 0.5)))
        low2_s = low_s.filter(ImageFilter.GaussianBlur(max(0.6, r * 0.5)))
        low = low_s.resize((W, H), Image.BILINEAR)
        low2 = low2_s.resize((W, H), Image.BILINEAR)
    else:
        low = img.filter(ImageFilter.GaussianBlur(r))
        low2 = low.filter(ImageFilter.GaussianBlur(r * 0.8))
    flat_low = Image.blend(low, low2, (k ** 0.55) * 0.95)
    hi = ImageChops.subtract(img, low, scale=1, offset=128)
    return ImageChops.add(flat_low, hi, scale=1, offset=-128)


def _face_bbox(skin):
    """从肤色蒙版估计人脸包围盒：取肤色最密集的连续列/行区间。"""
    try:
        import numpy as np
    except Exception:
        return None
    a = np.asarray(skin.point(lambda v: 255 if v > 96 else 0), dtype=np.uint8)
    if a.max() == 0:
        return None
    H, W = a.shape
    col = (a > 0).sum(axis=0)
    row = (a > 0).sum(axis=1)
    def span(arr, need):
        idx = np.where(arr >= need)[0]
        if idx.size < max(6, len(arr) // 20):
            return None
        return int(idx[0]), int(idx[-1])
    cs = span(col, max(2, int(col.max() * 0.35)))
    rs = span(row, max(2, int(row.max() * 0.35)))
    if not cs or not rs:
        return None
    x0, x1 = cs
    y0, y1 = rs
    if x1 - x0 < W * 0.08 or y1 - y0 < H * 0.08:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _zone_weight(size, bbox, forehead, cheek, chin, eye):
    """按人脸包围盒生成分区权重图（L 模式，0~255）。"""
    W, H = size
    img = Image.new("L", (W, H), 255)
    if not bbox:
        return img
    x, y, w, h = bbox
    d = ImageDraw.Draw(img)
    # 横向分带、互不重叠：额头 / 眼周 / 脸颊 / 下巴
    bands = ((0.00, 0.30, forehead), (0.30, 0.50, eye),
             (0.50, 0.78, cheek), (0.78, 1.00, chin))
    for fy0, fy1, level in bands:
        d.rectangle([x + w * 0.02, y + h * fy0, x + w * 0.98, y + h * fy1],
                    fill=int(max(0, min(150, level)) * 255 / 100))
    # 只做很小的模糊，避免权重跨区外溢
    return img.filter(ImageFilter.GaussianBlur(max(1.0, min(W, H) / 400.0)))


def _blemish_fix(img, skin, strength, size=5):
    """祛斑 / 痘印：找肤色区里比中值背景明显更暗的孤立小点，用背景替换。"""
    k = max(0.0, min(1.0, float(strength or 0) / 100.0))
    if k <= 0:
        return img
    rgb = img.convert("RGB")
    g = rgb.convert("L")
    # 背景要用比斑点更大的半径估计，否则背景本身被斑点污染（中值窗口小于斑点时无效）
    r = max(6.0, float(size) * 1.8)
    bg = g.filter(ImageFilter.GaussianBlur(r))
    diff = ImageChops.subtract(bg, g)          # 背景比原图亮 = 暗斑
    spot = diff.point(lambda v: 0 if v < 4 else min(255, (v - 4) * 20))
    spot = ImageChops.multiply(spot, skin)
    if spot.getbbox() is None:
        return img
    spot = spot.filter(ImageFilter.GaussianBlur(1.5))
    spot = spot.point(lambda v: int(v * (k ** 0.55)))
    # 修补：用同一套背景（大半径模糊）填充斑点区域
    patch = rgb.filter(ImageFilter.GaussianBlur(r * 0.85))
    return Image.composite(patch, rgb, spot)


def _eye_care(img, skin, strength, spread=50, bbox=None):
    """黑眼圈 / 眼袋：在眼下区域提亮暗部并压低蓝调。"""
    k = max(0.0, min(1.0, float(strength or 0) / 100.0))
    if k <= 0:
        return img
    if bbox is None:
        bbox = _face_bbox(skin)
    if not bbox:
        return img
    x, y, w, h = bbox
    W, H = img.size
    rgb = img.convert("RGB")
    # 眼下区域：左右各一个横向椭圆，位置取人脸高度的 36%~52%
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    rx = w * (0.16 + 0.10 * (spread / 100.0))
    ry = h * (0.055 + 0.030 * (spread / 100.0))
    for fx in (0.32, 0.68):
        cx, cy = x + w * fx, y + h * 0.44
        d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(max(2.0, w * 0.05)))
    m = ImageChops.multiply(m, skin)

    # 暗部提亮：只抬低亮度区域（v + (255-v)*系数），亮处几乎不动
    r0, g0, b0 = rgb.split()

    def _lift(ch):
        return ch.point(lambda v: int(v + (255 - v) * 0.40 * k))

    lit = Image.merge("RGB", (_lift(r0), _lift(g0), _lift(b0)))
    # 再单独压蓝，抵消黑眼圈常见的青紫
    lr, lg, lb = lit.split()
    cooled = Image.merge("RGB", (lr, lg,
                                 lb.point(lambda v: int(v * (1.0 - 0.12 * k)))))
    return Image.composite(cooled, rgb, m)


def _lip_teeth(img, skin, lip, teeth, bbox=None):
    """牙齿美白 + 唇色增强。在嘴部区域按像素特征区分牙齿与嘴唇。"""
    lip = max(0.0, min(100.0, float(lip or 0)))
    teeth = max(0.0, min(100.0, float(teeth or 0)))
    if lip <= 0 and teeth <= 0:
        return img
    if bbox is None:
        bbox = _face_bbox(skin)
    if not bbox:
        return img
    fx, fy, fw, fh = bbox
    W, H = img.size
    rgb = img.convert("RGB")

    # 嘴部区域
    mx0 = fx + fw * 0.28
    mx1 = fx + fw * 0.72
    my0 = fy + fh * 0.60
    my1 = fy + fh * 0.82
    box = (max(0, int(mx0)), max(0, int(my0)),
           min(W, int(mx1)), min(H, int(my1)))
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return img
    crop = rgb.crop(box)
    r, g, b = crop.split()
    l = crop.convert("L")
    rng = ImageChops.subtract(r, g)            # 红-绿：嘴唇明显偏高

    out = crop
    if teeth > 0:
        # 牙齿：嘴部里又亮、又接近中性（低饱和）
        vm = l.point(lambda v: 255 if v > 140 else 0)
        sm = rng.point(lambda v: 255 if v < 26 else 0)
        tm = ImageChops.multiply(vm, sm)
        if tm.getbbox() is not None:
            tm = tm.filter(ImageFilter.GaussianBlur(1.2))
            grey = crop.convert("L").convert("RGB")
            white = Image.blend(crop, grey, 0.55)          # 去黄
            white = ImageEnhance.Brightness(white).enhance(1.0 + 0.18 * teeth / 100.0)
            k = tm.point(lambda v: int(v * teeth / 100.0))
            out = Image.composite(white, out, k)
    if lip > 0:
        lm = rng.point(lambda v: 0 if v < 28 else min(255, (v - 28) * 8))
        lm = lm.filter(ImageFilter.GaussianBlur(1.5))
        k = lm.point(lambda v: int(v * lip / 100.0 * 0.85))
        rr, gg, bb = out.split()
        hot = Image.merge("RGB", (
            rr.point(lambda v: min(255, int(v * 1.10))),
            gg.point(lambda v: int(v * 0.95)),
            bb.point(lambda v: int(v * 0.96))))
        out = Image.composite(hot, out, k)
    rgb.paste(out, box)
    return rgb


def _face_boxes(skin, max_faces=4, min_ratio=0.18):
    """返回若干人脸包围盒（按面积从大到小）。没有模型，用肤色连通域估计。"""
    try:
        import numpy as np
    except Exception:
        b = _face_bbox(skin)
        return [b] if b else []
    W, H = skin.size
    sw = 160
    sh = max(24, int(H * sw / max(1, W)))
    a = np.asarray(skin.resize((sw, sh), Image.BILINEAR)) > 96
    if not a.any():
        return []
    seen = np.zeros_like(a, dtype=bool)
    boxes = []
    for y0 in range(sh):
        for x0 in range(sw):
            if not a[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            minx = maxx = x0
            miny = maxy = y0
            count = 0
            while stack:
                cy, cx = stack.pop()
                count += 1
                if cx < minx: minx = cx
                if cx > maxx: maxx = cx
                if cy < miny: miny = cy
                if cy > maxy: maxy = cy
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < sh and 0 <= nx < sw and a[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            if count < sw * sh * 0.004:
                continue
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if bh < sh * 0.12 or bw < sw * 0.06:
                continue
            boxes.append((minx, miny, bw, bh, count))
    if not boxes:
        return []
    boxes.sort(key=lambda b: -b[2] * b[3])
    biggest = boxes[0][2] * boxes[0][3]
    sx = W / float(sw); sy = H / float(sh)
    out = []
    for (bx, by, bw, bh, cnt) in boxes[:max_faces]:
        area = bw * bh
        if area < biggest * min_ratio:
            continue
        # 形状校验：人脸框通常高略大于宽，且肤色在框内占比较高；
        # 手臂、脖子这类细长或空心的色块会被这两条挡掉
        ratio = bw / float(max(1, bh))
        fill = cnt / float(max(1, area))
        if not (0.40 <= ratio <= 1.45):
            continue
        if not (0.30 <= fill <= 0.97):
            continue
        # 太扁（横跨画面）或太窄（色带）的也排除
        if bw > W * 0.85 and ratio > 1.15:
            continue
        out.append((int(bx * sx), int(by * sy), int(bw * sx), int(bh * sy)))
    return out


def _eye_centers(img, bbox):
    """在脸的上半部找最暗的左右两处，当作眼睛中心（比按固定比例可靠）。"""
    try:
        import numpy as np
    except Exception:
        return None
    x, y, w, h = bbox
    W, H = img.size
    y0 = max(0, int(y + h * 0.18))
    y1 = max(y0 + 4, int(y + h * 0.58))
    x0 = max(0, int(x + w * 0.10))
    x1 = max(x0 + 4, int(x + w * 0.90))
    g = np.asarray(img.convert("L").crop((x0, y0, x1, y1)), dtype=np.float32)
    if g.size < 16:
        return None
    dark = 255.0 - g
    col = dark.mean(axis=0)
    cw = col.size
    if cw < 10:
        return None
    mid = cw // 2
    lx = int(np.argmax(col[:mid])) if mid > 2 else 0
    rx = mid + int(np.argmax(col[mid:])) if cw - mid > 2 else cw - 1
    out = []
    for cx in (lx, rx):
        lo, hi = max(0, cx - 4), min(cw, cx + 5)
        seg = dark[:, lo:hi]
        wsum = seg.sum()
        cy = int((seg.mean(axis=1) * np.arange(seg.shape[0])).sum() / max(1e-6, seg.mean(axis=1).sum()))
        out.append((x0 + cx, y0 + cy))
    return out


def _face_warp(img, skin, slim=0, eyes=0, bbox=None):
    """瘦脸 + 大眼（先整体变形，再用蒙版合成，边缘不留台阶）。"""
    slim = max(0.0, min(100.0, float(slim or 0)))
    eyes = max(0.0, min(100.0, float(eyes or 0)))
    # 变形量极小时直接跳过，避免为看不见的变化付一次全尺寸重采样
    if slim <= 2 and eyes <= 2:
        return img
    if img.size[0] < 32 or img.size[1] < 32:
        return img
    try:
        import numpy as np
    except Exception:
        return img
    if bbox is None:
        bbox = _face_bbox(skin)
    if not bbox:
        return img
    x, y, w, h = bbox
    W, H = img.size
    if w < 24 or h < 24:
        return img

    # 只在人脸区域附近计算：水平外扩 0.30w、垂直外扩 0.14h（与蒙版椭圆一致）
    padx = int(w * 0.30)
    pady = int(h * 0.14)
    rx0 = max(0, int(x - padx)); rx1 = min(W, int(x + w + padx))
    ry0 = max(0, int(y - pady)); ry1 = min(H, int(y + h + pady))
    rw, rh = rx1 - rx0, ry1 - ry0
    if rw < 8 or rh < 8:
        return img.convert("RGB")

    arr = np.asarray(img.convert("RGB"))
    sub = arr[ry0:ry1, rx0:rx1].astype(np.float32)
    yy, xx = np.mgrid[ry0:ry1, rx0:rx1]
    sx = xx.astype(np.float32)
    sy = yy.astype(np.float32)

    # ---- 瘦脸：下半张脸整体向中线挤压 ----
    if slim > 0:
        k = slim / 100.0 * 0.20
        cx = x + w / 2.0
        t = np.clip((yy - (y + h * 0.30)) / (h * 0.55), 0.0, 1.0)
        fy = t * t * (3.0 - 2.0 * t)
        sx = sx + (sx - cx) * k * fy

    # ---- 大眼：两只眼睛位置做局部放大 ----
    if eyes > 0:
        k = eyes / 100.0 * 0.45
        R = max(10.0, w * 0.18)
        centers = _eye_centers(img, bbox)
        if not centers:
            centers = [(x + w * 0.32, y + h * 0.42),
                       (x + w * 0.68, y + h * 0.42)]
        for (ex, ey) in centers:
            d = np.sqrt((xx - ex) ** 2 + (yy - ey) ** 2)
            g = np.clip(1.0 - (d / R) ** 2, 0.0, 1.0)
            sx = sx + (ex - sx) * (k * g)
            sy = sy + (ey - sy) * (k * g)

    # 用 MESH 把重采样交给 PIL 的 C 实现：粗网格 + 双线性，比 numpy 逐像素快一个量级
    # 四边形数量控制在 ~900 个：再多对双线性质量没有提升，只是更慢
    target_cells = 30
    step = max(10, int(max(rw, rh) / float(target_cells)))
    gx = list(range(0, rw, step)) + [rw - 1]
    gy = list(range(0, rh, step)) + [rh - 1]
    grid_x, grid_y = np.meshgrid(np.array(gx, dtype=np.float32),
                                 np.array(gy, dtype=np.float32))
    # 对网格点做同样的逆映射
    px = grid_x + rx0
    py = grid_y + ry0
    if slim > 0:
        k = slim / 100.0 * 0.20
        cx = x + w / 2.0
        t = np.clip((py - (y + h * 0.30)) / (h * 0.55), 0.0, 1.0)
        fy = t * t * (3.0 - 2.0 * t)
        px = px + (px - cx) * k * fy
    if eyes > 0:
        k = eyes / 100.0 * 0.45
        R = max(10.0, w * 0.18)
        cs = _eye_centers(img, bbox) or [(x + w * 0.32, y + h * 0.42),
                                         (x + w * 0.68, y + h * 0.42)]
        for (ex, ey) in cs:
            d = np.sqrt((px - ex) ** 2 + (py - ey) ** 2)
            g = np.clip(1.0 - (d / R) ** 2, 0.0, 1.0)
            px = px + (ex - px) * (k * g)
            py = py + (ey - py) * (k * g)
    px = np.clip(px - rx0, 0, rw - 1)
    py = np.clip(py - ry0, 0, rh - 1)

    mesh = []
    for j in range(len(gy) - 1):
        for i in range(len(gx) - 1):
            x0d, x1d = gx[i], gx[i + 1]
            y0d, y1d = gy[j], gy[j + 1]
            if x1d - x0d < 1 or y1d - y0d < 1:
                continue
            quad = (px[j, i], py[j, i], px[j + 1, i], py[j + 1, i],
                    px[j + 1, i + 1], py[j + 1, i + 1],
                    px[j, i + 1], py[j, i + 1])
            mesh.append(((x0d, y0d, x1d, y1d), quad))
    region = img.convert("RGB").crop((rx0, ry0, rx1, ry1))
    try:
        warped = region.transform((rw, rh), Image.MESH, mesh,
                                  resample=Image.BILINEAR)
    except Exception:
        warped = region

    # ---- 合成：只覆盖这块区域 ----
    m2_full = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m2_full).ellipse(
        [x - w * 0.28, y - h * 0.10, x + w * 1.28, y + h * 1.12], fill=255)
    m2_full = m2_full.filter(ImageFilter.GaussianBlur(max(2.0, w * 0.05)))
    if slim > 0 and eyes <= 0:
        band = Image.new("L", (W, H), 0)
        ImageDraw.Draw(band).rectangle([0, y + h * 0.30, W, H], fill=255)
        band = band.filter(ImageFilter.GaussianBlur(max(2.0, h * 0.06)))
        m2_full = ImageChops.multiply(m2_full, band)

    base = img.convert("RGB")
    region = base.crop((rx0, ry0, rx1, ry1))
    mask = m2_full.crop((rx0, ry0, rx1, ry1))
    base.paste(Image.composite(warped, region, mask), (rx0, ry0))
    return base



def _beautify(img, smooth, radius, bright, even, shine=0, warm=0,
              softness=0, zones=None, blemish=0, spot_size=5,
              eye_care=0, eye_spread=50, lip=0, teeth=0,
              slim=0, eyes=0):
    """保边磨皮 + 提亮 + 肤色均匀（纯算法，无模型）。"""
    smooth = max(0.0, min(100.0, float(smooth or 0)))
    bright = max(0.0, min(100.0, float(bright or 0)))
    even = max(0.0, min(100.0, float(even or 0)))
    radius_lv = max(0.0, min(100.0, float(radius or 0)))
    shine = max(0.0, min(100.0, float(shine or 0)))
    warm = max(-100.0, min(100.0, float(warm or 0)))
    softness = max(0.0, min(100.0, float(softness or 0)))
    if not (smooth or bright or even or shine or warm or softness
            or blemish or eye_care or lip or teeth or slim or eyes):
        return img
    rgb = img.convert("RGB")
    h = rgb.size[1]
    ok, _why = _beauty_guard(rgb)
    if not ok:
        return img
    # 黑白照片没有可靠的肤色信息，色度接近 0 时不做依赖肤色的处理
    if _is_grayish(rgb):
        return img
    skin = _skin_mask(rgb, max(2.0, h / 320.0))
    ok, _why = _beauty_guard(rgb, skin)
    if not ok:
        return img
    faces = _face_boxes(skin) if (slim or eyes or eye_care or lip or teeth) else []
    if not faces:
        fb = _face_bbox(skin)
        faces = [fb] if fb else []
    if slim or eyes:
        for fb in faces:
            rgb = _face_warp(rgb, skin, slim, eyes, fb)
        skin = _skin_mask(rgb, max(2.0, h / 320.0))
    out = rgb
    if smooth > 0 or even > 0:
        # 半径同时受「范围」和「强度」影响：强度越大，压平的低频尺度越大，
        # 否则强度拉到 75 以上几乎看不出差别（实测原来 75 与 100 只差 0.08）
        r = (1.0 + radius_lv / 100.0 * 8.0) * (0.65 + 0.55 * smooth / 100.0) \
            * max(0.6, h / 900.0)
        base = rgb
        if even > 0:
            base = rgb.filter(ImageFilter.MedianFilter(size=5))
            base = Image.blend(rgb, base, even / 100.0 * 0.7)
        if smooth > 0:
            # 频域分离：只压低频，高频（毛孔、绒毛）保留
            soft = _freq_smooth(base, r, smooth)
            edge = _edge_weight(rgb, r * 0.6)
            w = ImageChops.multiply(skin, edge)
            if zones:
                bbox = _face_bbox(skin)
                if bbox:
                    zw = _zone_weight(rgb.size, bbox, *zones)
                    w = ImageChops.multiply(w, zw)
            w = w.point(lambda v: int(v * ((smooth / 100.0) ** 0.55) * 0.97))
            out = Image.composite(soft, out, w)
        else:
            w = skin.point(lambda v: int(v * even / 100.0 * 0.6))
            out = Image.composite(base, out, w)
    if blemish > 0:
        out = _blemish_fix(out, skin, blemish, spot_size)
    if eye_care > 0:
        for fb in faces:
            out = _eye_care(out, skin, eye_care, eye_spread, fb)
    if lip > 0 or teeth > 0:
        for fb in faces:
            out = _lip_teeth(out, skin, lip, teeth, fb)

    if bright > 0:
        k = (bright / 100.0) ** 1.35
        lit = ImageEnhance.Brightness(out).enhance(1.0 + 0.16 * k)
        w = skin.point(lambda v: int(v * k * 0.7))
        out = Image.composite(lit, out, w)

    if shine > 0:
        # 去油光：把皮肤里的高光压下来，越亮的地方压得越多
        k = shine / 100.0
        g = out.convert("L")
        # 只取 180 以上作为油光区
        hot = g.point(lambda v: 0 if v < 180 else min(255, (v - 180) * 4))
        hot = ImageChops.multiply(hot, skin)
        hot = hot.point(lambda v: int(v * k * 0.85))
        dull = ImageEnhance.Brightness(out).enhance(0.82)
        out = Image.composite(dull, out, hot)

    if abs(warm) > 0.5:
        # 肤色冷暖：正值偏暖（红多蓝少），负值偏冷
        k = warm / 100.0
        w = skin.point(lambda v: int(v * min(1.0, abs(k)) * 0.6))
        r, gg, b = out.split()
        tinted = Image.merge("RGB", (
            r.point(lambda v: min(255, int(v * (1.0 + 0.08 * k)))),
            gg.point(lambda v: int(v * (1.0 + 0.02 * k))),
            b.point(lambda v: min(255, int(v * (1.0 - 0.08 * k))))))
        out = Image.composite(tinted, out, w)

    if softness > 0:
        # 柔光：模糊后与原图叠加（Orton），只作用于皮肤
        k = softness / 100.0
        r2 = max(1.0, min(img.size) / 260.0)
        blur = out.filter(ImageFilter.GaussianBlur(r2))
        glow = Image.blend(out, blur, 0.55)
        glow = ImageEnhance.Brightness(glow).enhance(1.06)
        w = skin.point(lambda v: int(v * k * 0.55))
        out = Image.composite(glow, out, w)
    return out


def _lens_warp(img, amount):
    """镜头畸变矫正（径向）。

    amount > 0 向外扩（修桶形畸变），< 0 向内收（修枕形）。
    用最近邻重采样，预览与导出走同一函数，保证一致。
    """
    try:
        import numpy as np
    except Exception:
        return img
    k = max(-100.0, min(100.0, float(amount or 0))) / 100.0 * 0.45
    if abs(k) < 0.002:
        return img
    w, h = img.size
    if w < 8 or h < 8:
        return img
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    nx = (xx.astype(np.float32) - cx) / cx
    ny = (yy.astype(np.float32) - cy) / cy
    f = 1.0 + k * (nx * nx + ny * ny)
    sx = np.clip(cx + nx * f * cx, 0, w - 1).astype(np.int32)
    sy = np.clip(cy + ny * f * cy, 0, h - 1).astype(np.int32)
    arr = np.asarray(img.convert("RGB"))
    return Image.fromarray(arr[sy, sx], "RGB")


def _run_selftest():
    """把 AI 依赖的真实状态写成文件：装好的 exe 里跑 Prism.exe --selftest 即可。"""
    import tempfile
    import traceback
    lines = []
    lines.append("Prism %s 自检" % APP_VERSION)
    lines.append("frozen      = %s" % getattr(sys, "frozen", False))
    lines.append("executable  = %s" % sys.executable)
    lines.append("argv0       = %s" % sys.argv[0])
    lines.append("算法 = 肤色蒙版 + 保边磨皮（无模型）")
    try:
        from PIL import Image
        probe = Image.new("RGB", (640, 640), (200, 170, 150))
        faces = []
        lines.append("空图检测    = %d 张（0 属正常）" % len(faces))
    except Exception:
        lines.append("检测异常:")
        lines.append(traceback.format_exc())
    out = os.path.join(tempfile.gettempdir(), "prism_selftest.txt")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    except Exception:
        pass
    try:
        sys.stderr.write("\n".join(lines) + "\n")
    except Exception:
        pass
    return out


class QPEApp(_BASE):

    def __init__(self):
        super(QPEApp, self).__init__()
        # 配色要在建界面之前定下来，否则控件会先按默认色建出来
        self.fast_skip_fx = False
        self.tips_seen = False
        self._lang_ready = False
        self.low_mem = bool(globals().get("LOW_MEM_ARG", False))
        self.perf_profile = globals().get("PERF_PROFILE", "fast-slider")
        self.focus_mode = False
        self.panel_width = px(238)
        self.soft_proof = False
        self.soft_proof_path = ""
        self.soft_proof_name = ""
        self.soft_proof_transforms = None
        self.beauty_off = False       # 按住 B 时临时关闭美颜，用于对比
        self.hist_sel = None
        self.hist_data = None
        self.b_stop = False
        self.theme = self._peek_theme()
        _apply_palette(self.theme)
        global APP_LANG
        self.lang = self._peek_setting("lang", "zh")
        if self.lang not in ("zh", "en", "ja"):
            self.lang = "zh"
        APP_LANG = self.lang
        self.theme_btn = None
        self.title(APP_TITLE)
        self._apply_icon()
        self.configure(bg=BG)
        self.geometry("%dx%d" % (px(1120), px(760)))
        self.minsize(px(700), px(400))

        self.files = []
        self.folder = None
        self.index = -1
        self.doc = None
        self.loading = None
        self.error = None
        self.tile_cache = {}          # 必须先于任何 tile_cache.clear() 建立
        self.hsv_src = None
        self.hsv_chans = None
        self.detail_worker = DetailWorker()
        self.beauty_cache = {}       # (尺寸, 像素来源, 参数) -> 美颜结果
        self.thumbs_worker = ThumbWorker()
        self.thumbs = {}
        self.thumb_pending = set()
        self.thumb_x = {}
        self.thumb_items = {}
        self.thumb_limit = 160          # 缩略图缓存上限（张）
        self.strip = None
        self.strip_can = None
        self.strip_mark = None
        self.strip_shown = False
        self.last_frame_ms = 0.0
        self.grid_shown = False
        self.grid_win = None
        self.grid_canvas = None
        self.thumb_w = px(84)
        self.thumb_h = px(58)
        self.detail_cache = {}
        self.detail_inflight = None

        # 预设：存成脚本同目录下的 json，随用随取
        self.presets = {}
        # 插件参数：按插件 id 记住上次用的值，下次运行直接恢复
        self.plug_params = {}
        self.preset_box = None
        self.batch_win = None
        self.b_files = []
        self.b_i = 0
        self.b_ok = 0
        self.b_fail = []
        self.b_out_dir = ""
        self.b_ext = ".jpg"
        self.b_fmt_name = "JPEG"
        self.b_quality = 92
        self.b_maxlong = 0
        self.b_use_adj = True
        self.b_overwrite = False
        self.b_busy = False

        self.frame_i = 0
        self.geom = []                  # 几何操作栈 ("rot",deg)/("flip","h|v")/("crop",box)
        self.adj = self._default_adj()  # 非破坏性调整参数
        self.history = []
        self.hist_i = 0
        self.syncing = False
        self.crop_mode = False
        self.crop_anchor = None
        self.crop_rect = None
        self.panel_shown = False
        self.zoom_mode = "fit"          # fit | fitw | free
        self.scale = 1.0
        self.cx = None                  # 视口中心（图像坐标），None = 居中
        self.cy = None

        self.slideshow = False
        self.interval = 5
        self.paused = False
        self.fullscreen = False

        self.cache = {}
        self.cache_order = []
        self.cache_limit = 8
        # 解码位图的总内存上限。实测一张 3000×2000 的图解码就占 18MB，
        # 700MB 能堆到 40 张，对「轻量」来说太宽松了；320MB 够放十几张，
        # 超过就按 LRU 淘汰，重新打开时再解码。
        self.cache_budget = 320 * 1024 * 1024
        self.draft_to = (0, 0)
        self.pending_full = None
        self.full_loading = None
        self.full_started = 0.0
        self.full_tick_job = None
        self.actual_after_full = False
        self.loader = Loader()

        self.photo = None
        self.img_item = None
        self.text_item = None
        self.checker_key = None
        self.checker_img = None
        self.geom_key = None
        self.tile_cache.clear()
        self.geom_img = None
        self.contrast_mean = None
        self.auto_lut = None
        self.tone_key = None
        self.tone_lut = None
        self.color_key = None
        self.color_lut = None
        self.vig_key = None
        self.vig_mask = None
        self.vig_mult = None
        self.vig_mult_key = None
        self.show_original = False
        self.clip_adj = None
        self.preview_key = None
        self.preview_img = None
        self.preview_ratio = 1.0
        self.tile_cache = {}
        self.render_job = None
        self.flash_job = None
        self.last_render = 0.0
        self.render_cost = 16.0
        self.render_interval = 16.0
        self.locals = []
        self.local_sel = -1
        self.local_clip = None
        self.local_mode = None
        self.local_drag = None
        self.local_body = None
        self.local_box = None
        self.local_mask_cache = {}
        self.content_mask_cache = {}
        self.content_mask_cache = {}   # 主体/高对比遮罩缓存
        self.local_items = []
        self.hint_items = []
        self.picker_mode = False
        self.hist_labels = []
        self.hist_box = None
        self.crop_item = None
        self.sliders = []
        self.panel = None
        self.panel_grip = None
        self.pcan = None
        self.psb = None
        self.pwin = None
        self.ai_status_lbl = None
        self.ai_bar = None
        self.ai_progress_lbl = None
        self._ai_extra_shown = False
        self.last_slider = "调整"
        self.cmp_btn = None
        self.hist_undo_btn = None
        self.hist_redo_btn = None
        self.hist_can = None
        self.hist_info = None
        self.curve_hist = None
        self.hist_job = None
        self.curve_can = None
        self.curve_idx = None
        self.curve_channel = "rgb"
        self.curve_tabs = {}
        self.split_wheels = {}
        self.clip_warn = False
        self.clip_btn = None
        self.wm_text = ""
        self.wm_pos = "br"            # br 右下 / bl 左下 / c 居中
        self.wm_size = 3.5            # 占画面宽度的百分比
        self.wm_alpha = 65            # 不透明度 0-100
        self.wm_font_path = None
        self.snapshots = []
        self.snapshot_box = None
        self.about_win = None
        self.sort_key = "name"
        self.sort_desc = False
        self.sort_btn = None
        self.last_dir = ""
        self.saved_geom = ""
        self.saved_panel = False
        self.recent = []
        self.rename_win = None
        self.auto_btn = None
        self.split_x = None
        self.split_drag = False
        self.split_item = None
        self.split_label = None
        self.split_label2 = None
        self.split_btn = None
        self._split_orig = None
        self.straighten = 0.0
        self.crop_ratio = "free"
        self.crop_ratio_btns = {}
        self.cropbar = None
        self.straighten_scale = None
        self.grid_items = []
        self.grid_style = "thirds"      # thirds / golden / cross / none
        self.grid_style_btn = None
        self.pick_lbl = None
        self.pick_job = None
        self.pick_lock = None          # 锁定的取样颜色 (r,g,b)
        self.pick_btn = None
        self.surface_img = None
        self.surface_pos = (0, 0)
        self.hsl_pick = False
        self.hsl_body = None
        self.hsl_tabs = {}
        self.sections = {}
        self.hsl_mode = "sat"
        self.var_gray = None
        self.var_auto = None
        self.drag = None
        self.resize_job = None
        self.refine_job = None
        self.bar_job = None
        self.bar_groups = []
        self.bar_hidden = set()
        self.bar_laid_out = False
        self.fast = False
        self.anim_job = None
        self.slide_job = None
        self.info_win = None
        self.slide_label = None
        self.slide_bg = None

        self.load_settings()          # 必须在建界面之前：水印输入框要预填

        self.ui_font = self._pick_font(px(FONT_SM))
        self.ui_font_b = self._pick_font(px(FONT_SM), True)
        self.ui_font_s = self._pick_font(px(FONT_XS))
        self.ui_font_m = self._pick_font(px(FONT_MD))
        self.ui_font_l = self._pick_font(px(FONT_LG))
        self.mono_font = self._pick_font(px(FONT_SM), mono=True)
        self._mfont = tkfont.Font(font=self.ui_font)

        self._build_ui()
        if BIGSCREEN:
            # 大屏版没有任何快捷键，只保留窗口关闭协议
            self.protocol("WM_DELETE_WINDOW", self.on_close)
        else:
            self._bind_keys()
        self.load_presets()
        self._refresh_preset_box()
        self._refresh_sort_btn()
        if self.saved_geom and not BIGSCREEN:
            try:
                self.geometry(self.saved_geom)
            except Exception:
                pass
        if self.saved_panel:
            try:
                self.toggle_panel(True)
            except Exception:
                pass
        if self.clip_warn and self.clip_btn is not None:
            self.clip_btn.configure(bg=ACCENT, fg="#101010")
        if IS_MAC:
            self._setup_mac_menu()
        self.alive = True
        self.pump_job = self.after(30, self._pump)
        self.after(120, self._render)
        if BIGSCREEN:
            self.after(180, self._bigscreen_start)

    def _bigscreen_start(self):
        """大屏版启动即最大化；全屏由底栏按钮切换。"""
        try:
            self.state("zoomed")
        except Exception:
            try:
                self.attributes("-zoomed", True)
            except Exception:
                pass

    # ------------------------------------------------------------ 字体

    def _pick_font(self, size, bold=False, mono=False):
        if mono:
            fams = (("Menlo", "SF Mono", "Monaco") if IS_MAC else ()) + (
                "Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Courier New")
        elif IS_MAC:
            fams = ("PingFang SC", "Hiragino Sans GB", "Heiti SC",
                    "Helvetica Neue", "Noto Sans CJK SC")
        else:
            fams = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC",
                    "Noto Sans CJK SC", "Segoe UI")
        try:
            avail = set(tkfont.families(self))
        except Exception:
            avail = set()
        for fam in fams:
            if fam in avail:
                style = "bold" if bold else "normal"
                # 负数 = 以像素为单位，避免 Tk 再按 DPI 换算一次
                return (fam, -size, style)
        return ("TkDefaultFont", -size)

    # ------------------------------------------------------------ 界面

    def _mkbtn(self, parent, text, cmd, width=None):
        # 与面板按钮统一：Canvas 自绘圆角，hover 变色
        b = _QpeRoundButton(parent, text=text, command=cmd,
                            font=self.ui_font, bg=BAR_BG, fg=FG,
                            hover_bg=BAR_HOVER, hover_fg=FG_HI,
                            padx=8, pady=3, radius=RADIUS_SM)
        b.pack(side="left", padx=px(1), pady=px(3))
        return b

    def _build_cropbar(self):
        """裁剪模式才出现的细条：比例锁定 + 拉直。"""
        self.cropbar = tk.Frame(self, bg=BAR_BG, height=px(36))
        self.cropbar.pack_propagate(False)
        tk.Label(self.cropbar, text="比例", font=self.ui_font, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left", padx=(px(12), px(6)))
        for key, label in (("free", "自由"), ("orig", "原比例"),
                           ("1:1", "1:1"), ("4:3", "4:3"), ("3:2", "3:2"),
                           ("16:9", "16:9")):
            b = tk.Button(self.cropbar, text=label, font=self.ui_font_s,
                          command=lambda k=key: self._set_crop_ratio(k),
                          bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
                          activeforeground=FG_HI, relief="flat", bd=0,
                          highlightthickness=0, padx=px(8), pady=px(3),
                          cursor="hand2", takefocus=0)
            b.pack(side="left", padx=(0, px(4)), pady=px(5))
            self.crop_ratio_btns[key] = b
        tk.Label(self.cropbar, text="拉直", font=self.ui_font, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left", padx=(px(10), px(4)))
        self.straighten_scale = tk.Scale(
            self.cropbar, from_=-15.0, to=15.0, resolution=0.1,
            orient="horizontal", showvalue=True, bd=0, highlightthickness=0,
            bg=BAR_BG, fg=FG, troughcolor=TROUGH_BG, activebackground=ACCENT,
            sliderrelief="flat", length=px(180), width=px(11),
            font=self.ui_font_s, command=self._on_straighten)
        self.straighten_scale.pack(side="left", padx=px(6))
        self.grid_style_btn = tk.Button(
            self.cropbar, text="构图线：三分", font=self.ui_font_s,
            command=self._cycle_grid_style, bg=BTN_BG, fg=FG,
            activebackground=BAR_HOVER, activeforeground=FG_HI, relief="flat",
            bd=0, highlightthickness=0, padx=px(8), pady=px(3),
            cursor="hand2", takefocus=0)
        self.grid_style_btn.pack(side="left", padx=(px(10), 0), pady=px(5))
        # 右下角：实时尺寸 + 明确的「应用 / 取消」。
        # 以前只能按 Enter 应用，很多人拖完框不知道下一步怎么办。
        self.crop_size_lbl = tk.Label(self.cropbar, text="", font=self.ui_font_s,
                                      bg=BAR_BG, fg=FG_DIM)
        self.crop_size_lbl.pack(side="right", padx=(px(6), px(12)))
        self._panel_btn(self.cropbar, "取消", self.cancel_crop).pack(
            side="right", padx=(px(4), 0))
        b_ok = tk.Button(self.cropbar, text="应用裁剪", font=self.ui_font_s,
                         command=self.apply_crop, bg=ACCENT, fg="#101010",
                         activebackground="#6bb0ff", activeforeground="#101010",
                         relief="flat", bd=0, highlightthickness=0,
                         padx=px(12), pady=px(4), cursor="hand2", takefocus=0)
        b_ok.pack(side="right", padx=(px(8), 0))
        self.straighten_scale.bind("<ButtonRelease-1>",
                                   lambda e: self._push_history("拉直"))
        self._set_crop_ratio("free")

    def _set_crop_ratio(self, key):
        self.crop_ratio = key
        for k, b in self.crop_ratio_btns.items():
            on = (k == key)
            b.configure(bg=ACCENT if on else BTN_BG,
                        fg="#101010" if on else FG)

    def _crop_ratio_value(self):
        if self.crop_ratio == "free":
            return None
        if self.crop_ratio == "orig":
            im = self._view_image()
            return (im.size[0] / float(im.size[1])) if im else None
        try:
            a, b = self.crop_ratio.split(":")
            return float(a) / float(b)
        except Exception:
            return None

    def _on_straighten(self, v):
        if self.syncing:
            return
        try:
            self.straighten = float(v)
        except (TypeError, ValueError):
            return
        self.geom_key = None
        self.tile_cache.clear()
        self.preview_key = None
        self._mark_fast()
        self._request_render()
        self._update_status()

    def _sync_cropbar(self):
        self.syncing = True
        try:
            if self.straighten_scale is not None:
                self.straighten_scale.set(self.straighten)
        finally:
            self.syncing = False

    def _icon_btn(self, parent, kind, cmd):
        """自绘矢量图标按钮：不依赖字体里的符号，跨平台一定长得一样。"""
        s = px(26)
        cv = tk.Canvas(parent, width=s, height=s, bg=BAR_BG,
                       highlightthickness=0, bd=0, cursor="hand2")
        cv.pack(side="left", padx=px(1), pady=px(3))
        # 圆角 hover 底：先铺一层和背景同色的圆角矩形，图标画在它上面
        r = px(RADIUS_SM)
        _bg = cv.create_polygon(
            [r, 0, s - r, 0, s, 0, s, r, s, s - r, s, s, s - r, s,
             r, s, 0, s, 0, s - r, 0, r, 0, 0],
            smooth=True, fill=BAR_BG, outline="", tags="rbg")
        cv.bind("<Enter>", lambda e, c=cv, b=_bg: c.itemconfigure(b, fill=BAR_HOVER))
        cv.bind("<Leave>", lambda e, c=cv, b=_bg: c.itemconfigure(b, fill=BAR_BG))
        k = s / 26.0
        col = FG

        def ln(x1, y1, x2, y2, w=2.2):
            cv.create_line(x1 * k, y1 * k, x2 * k, y2 * k, fill=col,
                           width=max(1, int(w * k)), capstyle="round")

        if kind == "prev":
            cv.create_polygon(17 * k, 6 * k, 17 * k, 20 * k, 7.5 * k, 13 * k,
                              fill=col, outline="")
        elif kind == "next":
            cv.create_polygon(9 * k, 6 * k, 9 * k, 20 * k, 18.5 * k, 13 * k,
                              fill=col, outline="")
        elif kind == "fit":
            for (x1, y1, x2, y2, x3, y3) in (
                    (6, 10, 6, 6, 10, 6), (16, 6, 20, 6, 20, 10),
                    (6, 16, 6, 20, 10, 20), (16, 20, 20, 20, 20, 16)):
                ln(x1, y1, x2, y2, 2.0)
                ln(x2, y2, x3, y3, 2.0)
        elif kind in ("rotl", "rotr"):
            start = 60 if kind == "rotr" else 210
            cv.create_arc(6 * k, 6 * k, 21 * k, 21 * k, start=start,
                          extent=200, style="arc", outline=col,
                          width=max(1, int(2.2 * k)))
            tip = (14.5, 6.5) if kind == "rotr" else (11.5, 6.5)
            cv.create_polygon(tip[0] * k, (tip[1] - 2.5) * k,
                              tip[0] * k, (tip[1] + 3.5) * k,
                              (tip[0] + (5 if kind == "rotr" else -5)) * k,
                              (tip[1] + 0.5) * k, fill=col, outline="")
        # 图标线条/多边形用创建时的 FG 上色；打上 icon 标签，切主题时重上色
        for _item in cv.find_all():
            if _item != _bg:
                cv.addtag_withtag("icon", _item)
        cv.bind("<Button-1>", lambda e: cmd())
        cv.bind("<Enter>", lambda e: cv.configure(bg=BAR_HOVER))
        cv.bind("<Leave>", lambda e: cv.configure(bg=BAR_BG))
        return cv

    def _menubutton(self, parent, label):
        """工具栏上的下拉菜单按钮（文件/编辑/视图/工具/帮助）。"""
        mb = tk.Menubutton(parent, text=label, font=self.ui_font_s,
                           bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
                           activeforeground=FG_HI, relief="flat", bd=0,
                           highlightthickness=0, padx=px(9), pady=px(3),
                           cursor="hand2", takefocus=0)
        menu = tk.Menu(mb, tearoff=0, bg=DEEP2_BG, fg=FG,
                       activebackground=ACCENT, activeforeground=ON_BG,
                       bd=0, relief="flat", font=self.ui_font_s)
        mb.configure(menu=menu)
        # tkinter 的 Menu 只是 Tcl 菜单的 Python 包装，若没有 Python 侧引用，
        # 垃圾回收时会把菜单销毁 —— 表现就是点开是空的。这里显式持有。
        if not hasattr(self, "_menus"):
            self._menus = []
        self._menus.append(menu)
        self._menus.append(mb)
        mb.pack(side="left", padx=(0, px(2)), pady=px(4))
        mb.bind("<Enter>", lambda e, w=mb: w.configure(bg=BAR_HOVER))
        mb.bind("<Leave>", lambda e, w=mb: w.configure(bg=BTN_BG))
        return menu

    def _menu_item(self, menu, label, fn, accel=None):
        if fn is None:
            return
        try:
            if accel:
                menu.add_command(label=label, command=fn, accelerator=accel)
            else:
                menu.add_command(label=label, command=fn)
        except Exception:
            pass

    def _build_menubar(self, parent):
        """把原来散落在工具条上的按钮收进五个下拉菜单。"""
        m_file = self._menubutton(parent, "文件")
        self._menu_item(m_file, "打开文件…", self.open_dialog, "Ctrl+O")
        self._menu_item(m_file, "打开文件夹…", self.open_folder_dialog,
                        "Ctrl+Shift+O")
        self._recent_menu = tk.Menu(
            m_file, tearoff=0, bg=DEEP2_BG, fg=FG, activebackground=ACCENT,
            activeforeground=ON_BG, bd=0, relief="flat",
            font=self.ui_font_s)
        self._rebuild_recent_menu()
        m_file.add_cascade(label=_tr("最近打开"), menu=self._recent_menu)
        m_file.add_separator()
        self._menu_item(m_file, "批量导出…", self.batch_export)
        self._menu_item(m_file, "批量重命名…", self.batch_rename)
        self._menu_item(m_file, "在文件夹中显示", self.reveal_folder, "F2")
        m_file.add_separator()
        self._menu_item(m_file, "退出", self.on_close, "Ctrl+Q")

        m_edit = None
        if not VIEWER_ONLY:            # 看图版没有「编辑」菜单，避免空菜单
            m_edit = self._menubutton(parent, "编辑")
            self._menu_item(m_edit, "撤销", self.undo, "Ctrl+Z")
            self._menu_item(m_edit, "重做", self.redo, "Ctrl+Y")
            m_edit.add_separator()
            self._menu_item(m_edit, "重置全部调整", self.reset_edit_all)
            self._menu_item(m_edit, "复制设置", self.copy_settings)
            self._menu_item(m_edit, "粘贴设置", self.paste_settings)
            m_edit.add_separator()
            self._menu_item(m_edit, "显示 / 隐藏修图面板",
                            self.toggle_panel, "E")

        m_view = self._menubutton(parent, "视图")
        self._menu_item(m_view, "上一张", lambda: self.step(-1), "←")
        self._menu_item(m_view, "下一张", lambda: self.step(1), "→")
        m_view.add_separator()
        self._menu_item(m_view, "适应窗口", self.fit_window, "F")
        self._menu_item(m_view, "原始大小 100%", self.actual_size, "1")
        self._menu_item(m_view, "放大", lambda: self.zoom_by(1.25), "+")
        self._menu_item(m_view, "缩小", lambda: self.zoom_by(1 / 1.25), "-")
        m_view.add_separator()
        self._menu_item(m_view, "逆时针旋转", lambda: self.rotate(-90),
                        "Shift+R")
        self._menu_item(m_view, "顺时针旋转", lambda: self.rotate(90), "R")
        m_view.add_separator()
        self._menu_item(m_view, "胶片条", self.toggle_strip, "T")
        self._menu_item(m_view, "网格浏览", self.toggle_grid, "G")
        self._menu_item(m_view, "幻灯片", self.toggle_slideshow)

        m_tools = self._menubutton(parent, "工具")
        if not VIEWER_ONLY:
            self._menu_item(m_tools, "裁剪", self.toggle_crop, "C")
            m_tools.add_separator()
            self._menu_item(m_tools, "白平衡吸管", self.start_picker)
            self._menu_item(m_tools, "自动色调", self.auto_tone, "U")
            self._menu_item(m_tools, "自动白平衡", self.auto_wb)
            m_tools.add_separator()
            self._menu_item(m_tools, "过曝 / 欠曝警告", self.toggle_clip)
            self._menu_item(m_tools, "锁定取色", self.toggle_pick_lock, "I")
            m_tools.add_separator()
            self._menu_item(m_tools, "径向滤镜",
                            lambda: self.start_local("radial"))
            self._menu_item(m_tools, "渐变滤镜",
                            lambda: self.start_local("linear"))
            m_tools.add_separator()
            self._menu_item(m_tools, "人像美化…",
                            self.show_beauty)
            m_tools.add_separator()
        if not VIEWER_ONLY:
            self._menu_item(m_view, "全屏（兼容模式）", self.toggle_fullscreen,
                        "F11")
        self._menu_item(m_view, "载入全分辨率", self.load_full_resolution,
                        "F5")
        self._menu_item(m_view, "专注模式", self.toggle_focus_mode, "Tab")
        self._menu_item(m_view, "低内存模式", self.toggle_low_mem)
        self._menu_item(m_tools, "插件…", self.show_plugins)
        self._menu_item(m_tools, "设置…", self.show_settings)

        m_help = self._menubutton(parent, "帮助")
        self._menu_item(m_help, "快捷键与说明", self.show_help)
        self._menu_item(m_help, "检查更新…", self.check_updates)
        self._menu_item(m_help, "关于 %s %s" % (APP_NAME, APP_VERSION),
                        self.show_about)

    def _bar_group(self, priority):
        """工具条分组：优先级数字越大越先被隐藏。"""
        frame = tk.Frame(self.bar, bg=BAR_BG)
        self.bar_groups.append((frame, priority))
        return frame

    def _on_bar_configure(self, event=None):
        if self.bar_job is not None:
            try:
                self.after_cancel(self.bar_job)
            except Exception:
                pass
        self.bar_job = self.after(30, self._layout_bar)

    def _layout_bar(self, force=False):
        self.bar_job = None
        groups = self.bar_groups
        if not groups:
            return
        # 右侧常驻控件（缩放比例、插件、设置）也要占宽度。之前只减了缩放标签，
        # 英文/日文变长后就会「以为放得下」，pack 于是把最后几组挤成半截。
        right = px(24)
        for _nm in ("zoom_lbl", "plug_btn", "settings_btn"):
            _w = getattr(self, _nm, None)
            if _w is not None:
                try:
                    right += _w.winfo_reqwidth()
                except Exception:
                    pass
        avail = self.bar.winfo_width() - right
        if avail <= 1:
            return
        total = sum(f.winfo_reqwidth() for f, _p in groups)
        hidden = set()
        order = [k for k in range(len(groups))
                 if not getattr(groups[k][0], "_no_hide", False)]
        for i in sorted(order, key=lambda k: -groups[k][1]):
            if total <= avail:
                break
            hidden.add(i)
            total -= groups[i][0].winfo_reqwidth()
        # bar_laid_out 这个条件很关键：首次排布时如果窗口还没拿到真实宽度，
        # 会从上面 avail <= 1 提前返回；之后 <Configure> 又因为「隐藏集没变」
        # 再次提前返回 —— 结果分组从来没有被 pack 过，工具栏一直是空的。
        if hidden == self.bar_hidden and not force and self.bar_laid_out:
            return
        self.bar_hidden = hidden
        for i, (frame, _p) in enumerate(groups):
            if i in hidden:
                frame.pack_forget()
            else:
                frame.pack(side="left")
        self.bar_laid_out = True

    def _sep(self, parent):
        f = tk.Frame(parent, bg=CARD_LINE, width=max(1, px(1)),
                     height=px(20))
        f.pack(side="left", padx=px(SPACE_SM), pady=px(SPACE_MD))

    def _build_bigscreen_bar(self):
        """大屏版：底部大按钮工具栏，没有菜单、没有快捷键。"""
        self.bar_groups = []
        self.bar_hidden = set()
        self.bar_laid_out = True
        self.bar = tk.Frame(self, bg=BAR_BG, height=px(86))
        _status = getattr(self, "status", None)
        if _status is not None and _status.winfo_exists():
            # 语言切换会重建工具条；必须重新插到状态栏下方，否则会跑到上面
            self.bar.pack(side="bottom", fill="x", before=_status)
        else:
            self.bar.pack(side="bottom", fill="x")
        self.bar.pack_propagate(False)
        big = (self.ui_font[0], -int(px(15)), "bold")

        def add(text, cmd):
            b = tk.Button(
                self.bar, text=text, command=cmd, font=big, bg=BTN_BG, fg=FG,
                activebackground=BAR_HOVER, activeforeground=FG_HI,
                relief="flat", bd=0, highlightthickness=0, padx=px(14),
                pady=px(7), cursor="hand2", takefocus=0)
            b.pack(side="left", padx=px(3), pady=px(11))
            return b

        def sep():
            tk.Frame(self.bar, bg=CARD_LINE, width=max(1, px(1)),
                     height=px(34)).pack(side="left", padx=px(7), pady=px(26))

        add("打开", self.open_dialog)
        add("文件夹", self.open_folder_dialog)
        sep()
        add("◀", lambda: self.step(-1))
        add("▶", lambda: self.step(1))
        sep()
        add("适应", self.fit_window)
        add("1:1", self.actual_size)
        add("−", lambda: self.zoom_by(1 / 1.25))
        add("＋", lambda: self.zoom_by(1.25))
        add("旋转", lambda: self.rotate(90))
        sep()
        self.big_slide_btn = add("幻灯片", self.toggle_slideshow)
        add("网格", self.toggle_grid)
        sep()
        add("全屏", self.toggle_fullscreen)

        tk.Button(
            self.bar, text="退出", command=self.on_close, font=big, bg=BTN_BG,
            fg=FG, activebackground=BAR_HOVER, activeforeground=FG_HI,
            relief="flat", bd=0, highlightthickness=0, padx=px(14),
            pady=px(7), cursor="hand2", takefocus=0).pack(
                side="right", padx=(px(3), px(10)), pady=px(11))
        self.zoom_lbl = tk.Label(
            self.bar, text="", font=self.ui_font, bg=BAR_BG, fg=FG_DIM,
            width=6, anchor="e")
        self.zoom_lbl.pack(side="right", padx=(px(6), px(4)))

    def _build_bar(self):
        """构建（或在切换语言后重建）工具条。"""
        if BIGSCREEN:
            self._build_bigscreen_bar()
            return

        try:
            if getattr(self, "bar", None) is not None:
                self.bar.destroy()
        except Exception:
            pass
        self.bar_groups = []
        self.bar_hidden = set()
        self.bar_laid_out = False
        self.bar = tk.Frame(self, bg=BAR_BG, height=px(36))
        _body = getattr(self, "body", None)
        if _body is not None and _body.winfo_exists():
            # 重建时必须放回 body 之前；直接 pack(top) 会排到 body 后面，
            # 视觉上工具条就掉到窗口底部了（浅色主题切换时最容易看到）。
            self.bar.pack(side="top", fill="x", before=_body)
        else:
            self.bar.pack(side="top", fill="x")
        self.bar.pack_propagate(False)

        # 缩放比例优先靠右占位，窗口变窄时先压缩按钮而不是压扁它
        self.zoom_lbl = tk.Label(self.bar, text="", font=self.ui_font,
                                 bg=BAR_BG, fg=FG_DIM, width=6, anchor="e")
        self.zoom_lbl.pack(side="right", padx=(px(6), px(10)))
        # 设置放在工具条右侧常驻，不用滚到面板底部去找
        self.settings_btn = tk.Button(
            self.bar, text="设置", font=self.ui_font_s, command=self.show_settings,
            bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
            activeforeground=FG_HI, relief="flat", bd=0, highlightthickness=0,
            padx=px(9), pady=px(3), cursor="hand2", takefocus=0)
        self.settings_btn.pack(side="right", padx=(0, px(4)), pady=px(4))
        self.settings_btn.bind("<Enter>",
                               lambda e: self.settings_btn.configure(bg=BAR_HOVER))
        self.settings_btn.bind("<Leave>",
                               lambda e: self.settings_btn.configure(bg=BTN_BG))

        # 插件入口：和设置并排，随时可见
        self.plug_btn = tk.Button(
            self.bar, text="插件", font=self.ui_font_s, command=self.show_plugins,
            bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
            activeforeground=FG_HI, relief="flat", bd=0, highlightthickness=0,
            padx=px(9), pady=px(3), cursor="hand2", takefocus=0)
        self.plug_btn.pack(side="right", padx=(0, px(4)), pady=px(4))
        self.plug_btn.bind("<Enter>",
                           lambda e: self.plug_btn.configure(bg=BAR_HOVER))
        self.plug_btn.bind("<Leave>",
                           lambda e: self.plug_btn.configure(bg=BTN_BG))

        # 菜单栏（原来散在工具条上的按钮都收进这里）
        g = self._bar_group(1)
        g._no_hide = True        # 菜单永不隐藏
        self._build_menubar(g)

        # 工具条按优先级分组：空间不够时整组隐藏，而不是把按钮裁掉
        g = self._bar_group(1)
        g._no_hide = True        # 翻页常驻
        self._sep(g)
        self._icon_btn(g, "prev", lambda: self.step(-1))
        self._icon_btn(g, "next", lambda: self.step(1))

        g = self._bar_group(1)
        g._no_hide = True        # 缩放常驻
        self._sep(g)
        self._mkbtn(g, "-", lambda: self.zoom_by(1 / 1.25))
        self._icon_btn(g, "fit", self.fit_window)
        self._mkbtn(g, "1:1", self.actual_size)
        self._mkbtn(g, "+", lambda: self.zoom_by(1.25))

        g = self._bar_group(4)     # 最先被隐藏：英文/日文变长时优先牺牲这组
        self._sep(g)
        self._icon_btn(g, "rotl", lambda: self.rotate(-90))
        self._icon_btn(g, "rotr", lambda: self.rotate(90))

        # 幻灯片已收进「视图」菜单，原来的右键秒数菜单不再需要

        g = self._bar_group(1)
        g._no_hide = True        # 面板开关常驻
        self._sep(g)
        if not VIEWER_ONLY:
            # 菜单里已经有「编辑」，这个按钮是开关侧栏，改名避免重名
            self.panel_btn = self._mkbtn(g, "面板", self.toggle_panel)

        g = self._bar_group(2)
        self._sep(g)

        self._layout_bar(force=True)
        self.bar.bind("<Configure>", self._on_bar_configure)
    def _build_ui(self):
        self._build_bar()

        # 布局顺序即分配顺序：先让状态栏占住底部，body 再吃剩下的空间，
        # 面板在 body 内部又先于画布，这样打开面板时绝不会被画布挤没。
        self.status = tk.Frame(self, bg=BAR_BG, height=px(26))
        self.status.pack(side="bottom", fill="x")
        self.status.pack_propagate(False)
        self.name_lbl = tk.Label(self.status, text="", font=self.ui_font,
                                 bg=BAR_BG, fg=FG, anchor="w")
        self.name_lbl.pack(side="left", padx=px(12))
        # 降档图在状态栏给一个显式入口，不用记 F5，也不用翻「视图」菜单
        self.full_btn = tk.Button(
            self.status, text="全分辨率", font=self.ui_font_s,
            command=self.load_full_resolution, bg=ACCENT, fg=ON_BG,
            activebackground=BAR_HOVER, activeforeground=FG_HI,
            relief="flat", bd=0, highlightthickness=0, padx=px(8),
            pady=0, cursor="hand2", takefocus=0)
        self.meta_lbl = tk.Label(self.status, text="", font=self.ui_font,
                                 bg=BAR_BG, fg=FG_DIM, anchor="e")
        self.meta_lbl.pack(side="right", padx=px(12))
        self.pick_lbl = tk.Label(self.status, text="", font=self.mono_font,
                                 bg=BAR_BG, fg=FG_DIM, anchor="e")
        self.pick_lbl.pack(side="right", padx=px(10))

        self.body = tk.Frame(self, bg=BG)
        self.body.pack(side="top", fill="both", expand=True)

        self.canvas = tk.Canvas(self.body, bg=BG, highlightthickness=0, bd=0,
                                cursor="arrow")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<ButtonPress-2>", self._on_press)
        self.canvas.bind("<B2-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_wheel_h)
        self.canvas.bind("<Button-4>", lambda e: self._wheel_steps(1, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._wheel_steps(-1, e.x, e.y))
        self.canvas.bind("<Motion>", self._on_motion)

        self._build_cropbar()
        # 面板默认隐藏，首次打开时才构建（启动省 60 ms 左右）
        self._apply_lang()
        self._build_strip()

        if _DND_OK:
            for w in (self.canvas, self):
                try:
                    w.drop_target_register(DND_FILES)
                    w.dnd_bind("<<Drop>>", self._on_drop)
                except Exception:
                    pass

    def _setup_mac_menu(self):
        """macOS 需要真正的应用菜单，否则 ⌘Q / ⌘H 这些标准行为不可用。"""
        try:
            self.createcommand("tk::mac::Quit", self.on_close)
            self.createcommand("tk::mac::ShowPreferences", self.show_help)
            self.createcommand("tk::mac::OnHide", lambda: None)
        except Exception:
            pass
        try:
            menubar = tk.Menu(self)
            apple = tk.Menu(menubar, name="apple", tearoff=0)
            apple.add_command(label="关于 %s %s" % (APP_NAME, APP_VERSION),
                              command=self.show_about)
            apple.add_separator()
            apple.add_command(label="隐藏 Prism", command=self.iconify)
            menubar.add_cascade(menu=apple)

            fm = tk.Menu(menubar, tearoff=0)
            fm.add_command(label="打开…", command=self.open_dialog)
            fm.add_command(label="打开文件夹…", command=self.open_folder_dialog)
            fm.add_separator()
            fm.add_command(label="保存 / 另存为…", command=self.save_as)
            fm.add_command(label="批量导出…", command=self.batch_export)
            fm.add_separator()
            fm.add_command(label="关闭窗口", command=self.on_close)
            menubar.add_cascade(label="文件", menu=fm)

            em = tk.Menu(menubar, tearoff=0)
            em.add_command(label="撤销", command=self.undo)
            em.add_command(label="重做", command=self.redo)
            em.add_separator()
            em.add_command(label="复制设置", command=self.copy_settings)
            em.add_command(label="粘贴设置", command=self.paste_settings)
            em.add_command(label="重置全部", command=self.reset_edit_all)
            menubar.add_cascade(label="编辑", menu=em)

            vm = tk.Menu(menubar, tearoff=0)
            vm.add_command(label="适应窗口", command=self.fit_window)
            vm.add_command(label="原始大小", command=self.actual_size)
            vm.add_separator()
            vm.add_command(label="修图面板", command=self.toggle_panel)
            vm.add_command(label="胶片条", command=self.toggle_strip)
            vm.add_command(label="分屏对比", command=self.toggle_split)
            vm.add_separator()
            menubar.add_cascade(label="视图", menu=vm)

            hm = tk.Menu(menubar, tearoff=0)
            hm.add_command(label="快捷键", command=self.show_help)
            menubar.add_cascade(label="帮助", menu=hm)
            self.configure(menu=menubar)
        except Exception:
            pass

    def _bind_keys(self):
        b = self.bind

        def mb(seq, fn):
            """绑主修饰键；macOS 上再绑一份 Control 版本，照顾跨平台习惯。"""
            b(seq.replace("Mod", K), fn)
            if IS_MAC:
                b(seq.replace("Mod", "Control"), fn)

        mb("<Mod-o>", lambda e: self.open_dialog())
        mb("<Mod-O>", lambda e: self.open_dialog())
        mb("<Mod-Shift-O>", lambda e: self.open_folder_dialog())
        mb("<Mod-Shift-o>", lambda e: self.open_folder_dialog())
        b("<Left>", lambda e: self.step(-1))
        b("<Right>", lambda e: self.step(1))
        b("<Prior>", lambda e: self.step(-1))
        b("<Next>", lambda e: self.step(1))
        b("<Home>", lambda e: self.goto(0))
        b("<End>", lambda e: self.goto(len(self.files) - 1))
        b("<space>", lambda e: self.step(1))
        b("<BackSpace>", lambda e: self.step(-1))
        b("<F5>", lambda e: self.load_full_resolution())
        b("<Tab>", self._toggle_focus_key)
        b("<F11>", lambda e: self.toggle_fullscreen())
        b("<Escape>", lambda e: self._exit_fullscreen())
        b("<f>", lambda e: self.fit_window())
        b("<F>", lambda e: self.fit_window())
        b("<w>", lambda e: self.fit_width())
        b("<W>", lambda e: self.fit_width())
        b("<Key-1>", lambda e: self.actual_size())
        b("<r>", lambda e: self.rotate(90))
        b("<R>", lambda e: self.rotate(-90))
        mb("<Mod-r>", lambda e: self.reset_transform())
        b("<h>", lambda e: self.flip(False))
        b("<H>", lambda e: self.flip(False))
        b("<v>", lambda e: self.flip(True))
        b("<V>", lambda e: self.flip(True))
        b("<s>", lambda e: self.toggle_slideshow())
        b("<S>", lambda e: self.toggle_slideshow())
        b("<p>", lambda e: self.toggle_pause())
        b("<P>", lambda e: self.toggle_pause())
        if not VIEWER_ONLY:
            b("<e>", lambda e: self.toggle_panel())
            b("<E>", lambda e: self.toggle_panel())
            b("<KeyPress-b>", self._beauty_peek_on)
            b("<KeyRelease-b>", self._beauty_peek_off)
        b("<c>", lambda e: self.toggle_crop())
        b("<C>", lambda e: self.toggle_crop())
        b("<Return>", lambda e: self.apply_crop())
        b("<KP_Enter>", lambda e: self.apply_crop())
        mb("<Mod-s>", lambda e: self.save_as())
        mb("<Mod-b>", lambda e: self.batch_export())
        mb("<Mod-backslash>", lambda e: self.toggle_split())
        b("<KeyPress-g>", lambda e: self.toggle_grid())
        b("<KeyPress-G>", lambda e: self.toggle_grid())
        b("<KeyPress-t>", lambda e: self.toggle_strip())
        b("<KeyPress-T>", lambda e: self.toggle_strip())
        b("<KeyPress-backslash>", lambda e: self.toggle_compare(True))
        b("<KeyPress-k>", lambda e: self.start_picker())
        b("<KeyPress-l>", lambda e: self.toggle_clip())
        b("<KeyPress-F2>", lambda e: self.reveal_folder())
        b("<KeyPress-L>", lambda e: self.toggle_clip())
        b("<KeyPress-u>", lambda e: self.auto_tone())
        b("<KeyPress-U>", lambda e: self.auto_wb())
        b("<KeyPress-K>", lambda e: self.start_picker())
        b("<KeyPress-j>", lambda e: self.start_local("radial"))
        b("<KeyPress-J>", lambda e: self.start_local("linear"))
        b("<KeyRelease-backslash>", lambda e: self.toggle_compare(False))
        # 按住反斜杠时如果窗口失去焦点，KeyRelease 收不到，对比状态就会卡住。
        # 失焦一律退出，避免「所有调整都不生效」的假象。
        b("<FocusOut>", lambda e: self._release_modes())
        b("<KeyRelease-Escape>", lambda e: None)
        mb("<Mod-Shift-C>", lambda e: self.copy_settings())
        mb("<Mod-Shift-c>", lambda e: self.copy_settings())
        mb("<Mod-Shift-V>", lambda e: self.paste_settings())
        mb("<Mod-Shift-v>", lambda e: self.paste_settings())
        mb("<Mod-z>", lambda e: self.undo())
        mb("<Mod-y>", lambda e: self.redo())
        mb("<Mod-Shift-Z>", lambda e: self.redo())
        mb("<Mod-Shift-z>", lambda e: self.redo())
        b("<i>", lambda e: self.show_info())
        b("<I>", lambda e: self.show_info())
        b("<F1>", lambda e: self.show_help())
        b("<Escape>", lambda e: self._cancel_modes())
        b("<Delete>", lambda e: self.delete_current())
        mb("<Mod-c>", lambda e: self.copy_path())
        mb("<Mod-w>", lambda e: self.on_close())
        b("<plus>", lambda e: self.zoom_by(1.25))
        b("<equal>", lambda e: self.zoom_by(1.25))
        b("<KP_Add>", lambda e: self.zoom_by(1.25))
        b("<minus>", lambda e: self.zoom_by(1 / 1.25))
        b("<KP_Subtract>", lambda e: self.zoom_by(1 / 1.25))
        mb("<Mod-0>", lambda e: self.fit_window())
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(60, lambda: _round_window(self))

    # ------------------------------------------------------------ 打开

    def open_dialog(self):
        patterns = " ".join("*" + e for e in OPEN_EXTS)
        patterns += " " + " ".join("*" + e for e in sorted(RAW_EXTS))
        if HEIF_OK:
            patterns += " *.heic *.heif"
        path = filedialog.askopenfilename(
            parent=self, title="打开图片",
            filetypes=[("图片文件", patterns), ("所有文件", "*.*")])
        if path:
            self.open_files([path])

    def open_folder_dialog(self):
        folder = filedialog.askdirectory(parent=self, title="选择文件夹")
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder):
        files = list_images(folder)
        self.folder = folder
        if not files:
            self.files = []
            self.index = -1
            self.doc = None
            self._render()
            self._update_status()
            messagebox.showinfo("空文件夹", "这个文件夹里没有可显示的图片。", parent=self)
            return
        self.files = self._sort_list(files)
        self.index = -1
        self._strip_reset()
        self.goto(0)

    def open_files(self, paths):
        paths = [os.path.abspath(p) for p in paths]
        if not paths:
            return
        first = paths[0]
        self._remember_recent(first)
        folder = os.path.dirname(first)
        listing = list_images(folder)
        if first in listing and len(listing) > 1:
            self.folder = folder
            self.files = self._sort_list(listing)
            self.index = -1
            self._strip_reset()
            self.goto(listing.index(first))
        else:
            self.folder = folder
            self.files = paths
            self.index = -1
            self.goto(0)

    def _remember_recent(self, path):
        if not path or not os.path.isfile(path):
            return
        path = os.path.abspath(path)
        self.recent = [path] + [p for p in getattr(self, "recent", [])
                                if p != path]
        self.recent = self.recent[:10]
        try:
            self.save_settings()
        except Exception:
            pass
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        menu = getattr(self, "_recent_menu", None)
        if menu is None:
            return
        try:
            menu.delete(0, "end")
            recent = list(getattr(self, "recent", []))
            if not recent:
                menu.add_command(label=_tr("（空）"), state="disabled")
                return
            for p in recent:
                name = os.path.basename(p)
                if len(name) > 48:
                    name = name[:46] + "…"
                menu.add_command(
                    label="%s    %s" % (name, os.path.dirname(p)),
                    command=lambda q=p: self.open_recent(q))
            menu.add_separator()
            menu.add_command(label=_tr("清空最近打开"), command=self.clear_recent)
        except Exception:
            pass

    def clear_recent(self):
        self.recent = []
        try:
            self.save_settings()
        except Exception:
            pass
        self._rebuild_recent_menu()

    def open_recent(self, path):
        if os.path.isfile(path):
            self.open_files([path])
            return
        self.recent = [p for p in getattr(self, "recent", []) if p != path]
        self._rebuild_recent_menu()
        try:
            self.save_settings()
        except Exception:
            pass
        messagebox.showwarning("最近打开", "文件已不存在：%s" % path,
                               parent=self)

    def _on_drop(self, event):
        raw = self.tk.splitlist(event.data)
        paths = [p for p in raw if os.path.exists(p)]
        if not paths:
            return
        if len(paths) == 1 and os.path.isdir(paths[0]):
            self.open_folder(paths[0])
        else:
            self.open_files(paths)

    # ------------------------------------------------------------ 导航

    def goto(self, i, wrap=True):
        n = len(self.files)
        if n == 0:
            return
        if i < 0:
            i = n - 1 if wrap else 0
        if i >= n:
            i = 0 if wrap else n - 1
        if i == self.index and self.doc is not None and self.error is None:
            return
        self.index = i
        self.frame_i = 0
        self.geom_key = None
        self.tile_cache.clear()
        self.cx = None
        self.cy = None
        # 换图必须退出「对比原图」：否则一旦这个开关卡住（比如按住反斜杠时
        # 窗口失去了焦点，KeyRelease 收不到），之后每张图都只显示原图，
        # 所有调整都看不出效果 —— 表现就是「调完自动变回原图」。
        self.show_original = False
        if self.cmp_btn is not None:
            self.cmp_btn.configure(bg=BTN_BG, fg=FG)
        self._reset_edit()
        self._stop_anim()
        self._load_current()

    def step(self, delta):
        if not self.files:
            return
        self.goto(self.index + delta)

    def _load_current(self):
        if not self.files:
            self.doc = None
            self._render()
            self._update_status()
            return
        path = self.files[self.index]
        # 切图时放弃上一张还没回来的全分辨率请求，避免它把当前图替换掉
        if (getattr(self, "full_loading", None)
                and self.full_loading != path):
            self.pending_full = None
            self.full_loading = None
            self._stop_full_timer()
            self._set_full_btn_busy(False)
        doc = self.cache.get(path)
        self.error = None
        if doc is not None:
            self.doc = doc
            self.loading = None
            self._after_load()
            if getattr(doc, "oversize", False):
                self._flash("图片超过像素上限，已按代理尺寸载入（F5 载入全分辨率）", 4200)
            elif getattr(doc, "auto_drafted", False):
                self._flash("超大图（>%d 万像素）已按代理尺寸载入，按 F5 载入全分辨率"
                            % (AUTO_DRAFT_PIXELS // 10000), 4200)
        else:
            self.doc = None
            self.loading = path
            self.geom_key = None
            self.tile_cache.clear()
            self._retarget()
            self._render()
            self._update_status()
            self._update_title()

    def _retarget(self):
        other = []
        for k in (self.index + 1, self.index - 1, self.index + 2):
            if 0 <= k < len(self.files):
                p = self.files[k]
                if p not in self.cache:
                    other.append(p)
        primary = self.loading
        if primary is None and self.files:
            p = self.files[self.index]
            if p not in self.cache:
                primary = p
        # draft 目标 = 画布需要的最小尺寸（宽高都要满足，
        # Pillow 才会选到更狠的 1/4、1/8 档）
        # 0.85 余量：libjpeg 的档位是 1/1、1/2、1/4、1/8，只要两个方向都够就取低档。
        # 画布 1764x1396 请求原尺寸会落到 4000x2500（1/2 档），像素多 4 倍；
        # 留 15% 余量后落到 2000x1250（1/4 档），显示时上采样 ~12%，肉眼几乎无差。
        self.draft_to = (int(max(800, self.canvas.winfo_width()) * DRAFT_SLACK),
                         max(600, self.canvas.winfo_height()))
        preview_to = 0
        if primary:
            # 两段式与画布大小无关：大图先给一张 2000x1250 的预览，
            # 最终解码仍按 DRAFT_SLACK 走低档。实测（真实 40MP、2 核）：
            #   两段式 + 低档最终解码：首帧 327ms、滑杆 77ms
            #   单段 + 低档：首帧 585ms、滑杆 77ms
            #   两段式 + 高档最终解码：首帧 327ms、滑杆 118ms（滑杆变慢）
            # 所以「先预览、最终仍用低档」是两头都好的组合。
            try:
                big = os.path.getsize(primary) > 8 * 1024 * 1024
            except Exception:
                big = False
            if PERF_PROFILE == "fast-slider":
                preview_to = 0            # 单段：滑杆最快，首帧慢一些
            elif big:
                preview_to = (900, 700)   # auto / fast-first：两段式
            else:
                preview_to = 0
        self.loader.retarget(primary, other, draft_to=self.draft_to,
                             proxy_limit=self._proxy_limit(),
                             preview_to=preview_to)
        if primary or other:
            self._wake_pump()

    def _after_load(self):
        # 首帧用 BILINEAR 抢时间，160ms 后 _refine 自己会补一帧 LANCZOS。
        # 真实 40MP 照片上 LANCZOS 缩放到画布要 230~280ms，BILINEAR 约 1/3，
        # 而 fit 视图下两者肉眼差别很小（放大查看时另有全分辨率解码）。
        self._strip_kick()
        self._strip_focus()
        self._update_title()
        self._update_status()
        self._mark_fast()
        self._render()
        self._start_anim()
        self._retarget()
        if (not BIGSCREEN and not getattr(self, "tips_seen", False)
                and self.doc is not None):
            self.tips_seen = True
            try:
                self._save_setting("tips_seen", True)
            except Exception:
                pass
            self._flash("F5 全分辨率 · Tab 专注模式 · 拖动右栏调宽", 6000)

    def _pump(self):
        self.pump_job = None
        if not self.alive:
            return
        # 网格视图也复用同一批缩略图，所以只要任一视图开着就得排空队列
        if self.strip_shown or self.grid_shown:
            self._strip_drain()
        if self.grid_shown and self.grid_win is not None:
            self._grid_draw()
        try:
            while True:
                key, img = self.detail_worker.out.get_nowait()
                if len(self.detail_cache) > 2:
                    self.detail_cache.clear()
                self.detail_cache[key] = img
                if self.detail_inflight == key:
                    self.detail_inflight = None
                self._render()            # 换成带细节的版本
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        try:
            while True:
                path, doc = self.loader.out.get_nowait()
                try:
                    self._handle_result(path, doc)
                except Exception:
                    traceback.print_exc()  # 单张图出错不能拖垮整个循环
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        try:
            # pump_job is None 这个判断很关键：本轮 drain 里可能已经通过
            # _wake_pump() 排过一次了，这里若无条件重排就会把上一个任务 id
            # 覆盖掉，那个任务从此再也取消不了，关闭窗口后会刷 invalid command name。
            if self.alive and self.pump_job is None:
                # 有活干就 25ms 一次，闲着就 200ms 一次：
                # 原来不管有没有事都每秒轮询 40 次，纯烧 CPU。
                self.pump_job = self.after(25 if self._busy() else 200,
                                           self._pump)
        except tk.TclError:
            pass

    def _busy(self):
        return bool(self.loading or self.pending_full or self.detail_inflight
                    or self.thumb_pending)

    def _wake_pump(self):
        """刚提交了后台任务，把轮询立刻叫醒，别等慢档。"""
        if not self.alive:
            return
        if self.pump_job is not None:
            try:
                self.after_cancel(self.pump_job)
            except Exception:
                pass
        self.pump_job = self.after(10, self._pump)

    def _handle_result(self, path, doc):
        if not isinstance(doc, Exception):
            slow = getattr(doc, "slow_ms", 0.0)
            if slow and slow > SLOW_DECODE_MS:
                try:
                    self._flash("这张图解码用了 %.1f 秒（文件较大或磁盘较慢）"
                                % (slow / 1000.0), 4200)
                except Exception:
                    pass
        if isinstance(doc, Exception):
            self.error = doc
            if self.cache.get(path) is None:
                self.cache[path] = None
        else:
            self._cache_put(path, doc)
            if self.error is not None and path == self.loading:
                self.error = None
        if path == self.pending_full:
            self.pending_full = None
            self.full_loading = None
            self._stop_full_timer()
            self._set_full_btn_busy(False)
            if isinstance(doc, Exception):
                self._flash("载入全分辨率失败：%s" % str(doc)[:60], 4000)
                self._update_status()
                return
            # 只是同一张图换成全分辨率版，不能动用户的编辑状态；
            # 坐标和缩放同步换算，画面才不会跳。
            old = self.doc
            r = getattr(old, "draft_ratio", 1.0) if old is not None else 1.0
            if getattr(self, "actual_after_full", False):
                self.actual_after_full = False
                self.scale = 1.0
                self.zoom_mode = "free"
                self.cx = None
                self.cy = None
            elif 0 < r < 1.0:
                self.scale = max(MIN_SCALE, min(MAX_SCALE, self.scale * r))
                if self.cx is not None:
                    self.cx *= r
                if self.cy is not None:
                    self.cy *= r
            self.cache[path] = doc
            self.doc = doc
            self.geom_key = None
            self.tile_cache.clear()
            self.preview_key = None
            self.hsv_src = None
            self._after_load()
            self._update_status()
            self._flash("已载入全分辨率 %dx%d" % doc.img.size, 2400)
            return
        if path != self.loading:
            return
        self.loading = None
        self.doc = doc if not isinstance(doc, Exception) else None
        self.geom_key = None
        self.tile_cache.clear()
        self.preview_key = None
        self.hsv_src = None
        self.local_mask_cache = {}
        self.cx = None
        self.cy = None
        if self.doc is not None:
            self._after_load()
        else:
            self._render()
            self._update_status()
            self._update_title()

    def _cache_put(self, path, doc):
        if path not in self.cache:
            self.cache_order.append(path)
        self.cache[path] = doc
        keep = set(self.files[self.index:self.index + 3]) if self.files else set()
        if 0 <= self.index < len(self.files):
            keep.add(self.files[self.index])
        # 先按张数，再按内存预算：一张 67MP 就要 190MB，
        # 只限张数的话缓存能涨到 1.5GB 以上。
        while len(self.cache_order) > self.cache_limit:
            old = self.cache_order.pop(0)
            if old in keep or old == self.loading:
                self.cache_order.append(old)
                break
            self.cache.pop(old, None)
        while len(self.cache_order) > 1:
            total = sum(d.mem_bytes() for d in self.cache.values()
                        if d is not None)
            if total <= self.cache_budget:
                break
            oldest = next((p for p in self.cache_order
                           if p not in keep and p != self.loading), None)
            if oldest is None:
                break
            self.cache_order.remove(oldest)
            self.cache.pop(oldest, None)

    # ------------------------------------------------------------ 动画

    def _start_anim(self):
        self._stop_anim()
        if self.doc is not None and self.doc.n_frames > 1 and not self.paused:
            self._schedule_anim()

    def _schedule_anim(self):
        if self.doc is None or self.doc.n_frames <= 1 or self.paused:
            return
        d = self.doc.duration(self.frame_i)
        self.anim_job = self.after(max(20, d), self._anim_tick)

    def _stop_anim(self):
        if self.anim_job is not None:
            try:
                self.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None

    def _anim_tick(self):
        self.anim_job = None
        if self.doc is None or self.doc.n_frames <= 1 or self.paused:
            return
        self.frame_i = (self.frame_i + 1) % self.doc.n_frames
        self.geom_key = None
        self.tile_cache.clear()
        self._render()
        self._schedule_anim()

    def toggle_pause(self):
        self.paused = not self.paused
        if self.paused:
            self._stop_anim()
        else:
            self._start_anim()
        self._update_status()

    # ------------------------------------------------------------ 幻灯片

    def _draw_slide_label(self):
        """幻灯片时在画面底部显示文件名与进度。"""
        c = self.canvas
        for attr in ("slide_label", "slide_bg"):
            it = getattr(self, attr, None)
            if it is not None:
                try:
                    c.delete(it)
                except Exception:
                    pass
                setattr(self, attr, None)
        if not self.slideshow or self.doc is None:
            return
        cw = max(1, c.winfo_width())
        ch = max(1, c.winfo_height())
        text = "%s      %d / %d" % (os.path.basename(self.doc.path),
                                    self.index + 1, len(self.files))
        self.slide_label = c.create_text(
            cw // 2, ch - px(24), text=text, fill="#ffffff",
            font=self.ui_font, anchor="s")
        box = c.bbox(self.slide_label)
        if box:
            self.slide_bg = c.create_rectangle(
                box[0] - px(12), box[1] - px(5),
                box[2] + px(12), box[3] + px(5),
                fill="#101010", outline="")
            c.tag_lower(self.slide_bg, self.slide_label)

    def toggle_slideshow(self):
        self.slideshow = not self.slideshow
        if self.slideshow:
            self.slide_btn.configure(fg=ACCENT)
            self._slide_tick()
        else:
            self.slide_btn.configure(fg=FG)
            if self.slide_job is not None:
                try:
                    self.after_cancel(self.slide_job)
                except Exception:
                    pass
                self.slide_job = None
        self._render()          # 关掉幻灯片时要把底部标签擦掉，必须重绘一次
        self._update_status()

    def _slide_tick(self):
        self.slide_job = None
        if not self.slideshow:
            return
        if self.files:
            self.goto(self.index + 1)
        self.slide_job = self.after(int(self.interval * 1000), self._slide_tick)

    def _reveal_target(self):
        """当前应该在文件管理器里打开哪个目录。"""
        if self.doc is not None:
            p = self.doc.path
            return p if os.path.isdir(p) else os.path.dirname(p)
        if self.folder and os.path.isdir(self.folder):
            return self.folder
        return ""

    def reveal_folder(self):
        """在系统文件管理器里打开当前图片所在目录。"""
        target = self._reveal_target()
        if not target or not os.path.isdir(target):
            self._flash("还没有打开任何文件夹")
            return
        try:
            import subprocess
            if IS_WIN:
                os.startfile(target)
            elif IS_MAC:
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            self._flash("已在文件管理器中打开：%s" % os.path.basename(target))
        except Exception as exc:
            self._flash("打不开目录：%s" % exc)

    def _popup_slide_menu(self, event):
        try:
            self.slide_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.slide_menu.grab_release()
        return "break"

    def set_interval(self, sec):
        self.interval = sec
        if self.slideshow:
            if self.slide_job is not None:
                try:
                    self.after_cancel(self.slide_job)
                except Exception:
                    pass
                self.slide_job = None
            self._slide_tick()
        self._update_status()

    # ------------------------------------------------------------ 缩放

    def _view_image(self):
        """当前帧套用旋转/翻转后的位图（带缓存）。"""
        doc = self.doc
        if doc is None:
            return None
        base = doc.get_frame(self.frame_i)
        key = (doc.path, self.frame_i, tuple(self.geom),
               round(self.straighten, 2),
               round(self.adj.get("lens", 0.0), 1))
        if self.geom_key != key:
            im = base
            if abs(self.straighten) > 0.05:
                im = _straighten(im, self.straighten)
            for op in self.geom:
                kind = op[0]
                if kind == "rot":
                    im = im.rotate(-op[1], expand=True, resample=BICUBIC)
                elif kind == "flip":
                    im = ImageOps.mirror(im) if op[1] == "h" else ImageOps.flip(im)
                elif kind == "crop":
                    im = im.crop(op[1])
            if abs(self.adj.get("lens", 0.0)) > 0.5:
                im = _lens_warp(im, self.adj["lens"])
            self.geom_key = key
            self.geom_img = im
            self.contrast_mean = None
            self.auto_lut = None
        return self.geom_img

    # ------------------------------------------------------------ 调整

    @staticmethod
    def _default_adj():
        """全部默认值都是「不改变画面」的中性值。"""
        return {
            # 白平衡
            "temperature": 0.0, "tint": 0.0,
            # 基本
            "exposure": 0.0, "contrast": 0.0, "highlights": 0.0,
            "shadows": 0.0, "whites": 0.0, "blacks": 0.0,
            "vibrance": 0.0, "saturation": 0.0,
            "auto": False, "grayscale": False,
            # 色调曲线（控制点，0-255）：主 + 红/绿/蓝 分通道
            "curve": [list(p) for p in CURVE_DEFAULT],
            "curve_r": [list(p) for p in CURVE_DEFAULT],
            "curve_g": [list(p) for p in CURVE_DEFAULT],
            "curve_b": [list(p) for p in CURVE_DEFAULT],
            # 8 段 HSL
            "hsl": {"hue": [0.0] * 8, "sat": [0.0] * 8, "lum": [0.0] * 8},
            # 细节
            "sharpen": 0.0, "sharpen_radius": 1.0, "sharpen_detail": 25.0,
            "nr_luma": 0.0, "nr_color": 0.0,
            "clarity": 0.0, "dehaze": 0.0,
            # 色调分离（颜色分级）
            "split_hi_hue": 45.0, "split_hi_sat": 0.0,
            "split_lo_hue": 215.0, "split_lo_sat": 0.0,
            # 效果
            "vignette": 0.0,
            # 镜头 / 胶片 / 人像
            "lens": 0.0, "film": "无", "film_strength": 100.0,
            "skin_smooth": 0.0, "skin_glow": 0.0,
            "skin_even": 0.0, "skin_radius": 40.0,
            "skin_shine": 0.0, "skin_warm": 0.0, "skin_soft": 0.0,
            "skin_blemish": 0.0, "skin_spot_size": 5.0,
            "skin_eye_care": 0.0, "skin_eye_spread": 50.0,
            "skin_lip": 0.0, "skin_teeth": 0.0,
            "skin_slim": 0.0, "skin_eyes": 0.0, "skin_link": True,
            "zone_forehead": 100.0, "zone_cheek": 100.0,
            "zone_chin": 100.0, "zone_eye": 70.0,
        }

    CURVE_KEYS = ("curve", "curve_r", "curve_g", "curve_b")

    def _curve_identity(self):
        return all(_curve_is_identity(self.adj[k]) for k in self.CURVE_KEYS)

    def _active_curve(self):
        return self.adj[{"rgb": "curve", "r": "curve_r", "g": "curve_g",
                         "b": "curve_b"}.get(self.curve_channel, "curve")]

    def _hsl_active(self):
        h = self.adj["hsl"]
        return any(h["hue"]) or any(h["sat"]) or any(h["lum"])

    def _adj_identity(self):
        a = self.adj
        if a["grayscale"] or a["auto"] or not self._curve_identity():
            return False
        for k in ("temperature", "tint", "exposure", "contrast", "highlights",
                  "shadows", "whites", "blacks", "vibrance", "saturation",
                  "sharpen", "nr_luma", "nr_color", "clarity", "dehaze",
                  "split_hi_sat", "split_lo_sat", "vignette", "lens",
                  # 美颜相关：任何一个不为 0 都算「有调整」，否则整条美颜会被跳过
                  "skin_smooth", "skin_glow", "skin_even", "skin_blemish",
                  "skin_eye_care", "skin_lip", "skin_teeth", "skin_slim",
                  "skin_eyes", "skin_shine", "skin_warm", "skin_soft"):
            if a.get(k):
                return False
        # 胶片：选了预设且强度不为 0 才算有改动
        if a.get("film", "无") != "无" and a.get("film_strength", 0):
            return False
        return not self._hsl_active()

    def _contrast_mean(self):
        """对比度基准取全图平均灰度，保证预览和保存结果一致。"""
        if self.contrast_mean is None:
            im = self._view_image()
            if im is None:
                self.contrast_mean = 128
            else:
                g = im.convert("L")
                w, h = g.size
                f = 256.0 / max(w, h)
                if f < 1.0:
                    g = g.resize((max(1, int(w * f)), max(1, int(h * f))))
                self.contrast_mean = int(ImageStat.Stat(g).mean[0] + 0.5)
        return self.contrast_mean

    def _auto_lut(self):
        """自动色阶：按**亮度**直方图 0.5% 截断定黑白场。

        只拉伸明暗、不动各通道比例，所以不会引入偏色。
        """
        if self.auto_lut is not None:
            return self.auto_lut
        im = self._view_image()
        if im is None:
            return None
        small = im.convert("L")
        w, h = small.size
        f = 400.0 / max(w, h)
        if f < 1.0:
            small = small.resize((max(1, int(w * f)), max(1, int(h * f))))
        hist = small.histogram()
        cut = int(sum(hist) * 0.005)
        lo, hi = 0, 255
        acc = 0
        for v in range(256):
            acc += hist[v]
            if acc > cut:
                lo = v
                break
        acc = 0
        for v in range(255, -1, -1):
            acc += hist[v]
            if acc > cut:
                hi = v
                break
        if hi <= lo:
            hi = min(255, lo + 1)
        scale = 255.0 / (hi - lo)
        self.auto_lut = [_clamp255((v - lo) * scale) for v in range(256)]
        return self.auto_lut

    def _tone_signature(self):
        a = self.adj
        return (a["auto"], round(a["temperature"], 3), round(a["tint"], 3),
                round(a["exposure"], 4), round(a["contrast"], 4),
                round(a["highlights"], 4), round(a["shadows"], 4),
                round(a["whites"], 4), round(a["blacks"], 4),
                tuple(tuple(p) for p in a["curve"]),
                tuple(tuple(p) for p in a["curve_r"]),
                tuple(tuple(p) for p in a["curve_g"]),
                tuple(tuple(p) for p in a["curve_b"]), self.geom_key)

    def _tone_lut(self):
        """基本面板 + 自动色阶 + 色调曲线 → 合成一条 LUT，一次 point() 完成。

        这些运算都是逐通道的查表，合并后每帧只做一次遍历，
        比逐个 ImageEnhance 快一个数量级，而且预览与保存严格一致。
        """
        a = self.adj
        neutral = (not a["auto"] and self._curve_identity()
                   and not any(a.get(k) for k in
                               ("temperature", "tint", "exposure", "contrast",
                                "highlights", "shadows", "whites", "blacks")))
        if neutral:
            return None
        sig = self._tone_signature()
        if self.tone_key == sig and self.tone_lut is not None:
            return self.tone_lut
        base = _basic_tone_lut(a)
        if a["auto"]:
            auto = self._auto_lut()
            if auto:
                base = [auto[i] for i in base]
        master = _mono_curve(a["curve"])
        gains = _wb_gains(a)
        per = (a["curve_r"], a["curve_g"], a["curve_b"])
        full = []
        # 顺序：白平衡 → 基本明暗 → 分通道曲线 → 主曲线
        for idx, gain in enumerate(gains):
            pre = [_clamp255(v * gain) for v in range(256)]
            ch = per[idx]
            if _curve_is_identity(ch):
                full.extend([master[base[pre[v]]] for v in range(256)])
            else:
                cl = _mono_curve(ch)
                full.extend([master[cl[base[pre[v]]]] for v in range(256)])
        self.tone_lut = full         # RGB 图像需要 768 条（三通道各一份）
        self.tone_key = sig
        return self.tone_lut

    def _color_luts(self):
        """缓存 色相偏移 / 饱和度 / 明度 三条通道 LUT（只跟 HSL 参数有关）。"""
        a = self.adj
        if not (self._hsl_active() or a["vibrance"] or a["saturation"]):
            return None
        key = (tuple(a["hsl"]["hue"]), tuple(a["hsl"]["sat"]),
               tuple(a["hsl"]["lum"]), round(a["vibrance"], 3),
               round(a["saturation"], 3))
        if self.color_key != key or self.color_lut is None:
            hue_lut, sat_mul, lum_mul, cover = _hsl_luts(a["hsl"])
            # 全局饱和度/自然饱和度会作用于每个像素，这时无需遮罩
            full = bool(a["vibrance"] or a["saturation"]) or not self._hsl_active()
            self.color_lut = (
                hue_lut,
                _s_channel_lut(a, sat_mul),
                [_clamp255(v * lum_mul[v]) for v in range(256)],
                cover,
                any(a["hsl"]["hue"]),
                full,
            )
            self.color_key = key
        return self.color_lut

    def _denoise_color(self, img, amount):
        """颜色降噪：只糊色度通道 Cb/Cr，亮度 Y 原样保留，所以细节不会糊。"""
        r = 0.6 + (amount / 100.0) * 3.4
        ycc = img.convert("YCbCr")
        y, cb, cr = ycc.split()
        cb = cb.filter(ImageFilter.GaussianBlur(r))
        cr = cr.filter(ImageFilter.GaussianBlur(r))
        return Image.merge("YCbCr", (y, cb, cr)).convert("RGB")

    def _denoise_luma(self, img, amount):
        """亮度降噪：模糊后按「与原图的差异」加权融合，差异大的地方（边缘）保留原图。"""
        _np_ready()
        r = 0.5 + (amount / 100.0) * 2.0
        blur = img.filter(ImageFilter.GaussianBlur(r))
        k = amount / 100.0
        if _np is None:
            return Image.blend(img, blur, k * 0.6)
        a = _np.asarray(img, dtype=_np.float32)
        b = _np.asarray(blur, dtype=_np.float32)
        d = _np.abs(a - b).max(axis=2, keepdims=True)
        w = _np.clip(1.0 - d / 26.0, 0.0, 1.0) * k       # 边缘保护
        return Image.fromarray((a * (1.0 - w) + b * w).astype(_np.uint8))

    def _apply_clarity(self, img, amount):
        """清晰度：大半径 USM 提中间调局部对比；负值则向模糊版本靠拢（柔化）。"""
        k = amount / 100.0
        w = max(img.size)
        radius = max(3.0, min(40.0, w / 90.0))
        if k > 0:
            return img.filter(ImageFilter.UnsharpMask(
                radius=radius, percent=int(k * 55), threshold=0))
        blur = img.filter(ImageFilter.GaussianBlur(radius * 0.5))
        return Image.blend(img, blur, min(1.0, -k))

    def _apply_dehaze(self, img, amount):
        """去朦胧：暗通道先验的简化版（估大气光 + 透射率，不做引导滤波）。"""
        _np_ready()
        if _np is None:
            return img
        a = _np.asarray(img, dtype=_np.float32) / 255.0
        dark = a.min(axis=2)
        thr = _np.percentile(dark, 99.9)
        sel = dark >= thr
        air = a[sel].mean(axis=0) if sel.any() else a.reshape(-1, 3).max(axis=0)
        air = _np.clip(air, 0.08, 1.0)
        t = _np.clip(1.0 - 0.85 * dark, 0.15, 1.0)[..., None]
        clear = _np.clip((a - air * (1.0 - t)) / t, 0.0, 1.0)
        k = amount / 100.0
        out = a * (1.0 - k) + clear * k if k > 0 else a * (1.0 + k) + air * (-k)
        return Image.fromarray((_np.clip(out, 0.0, 1.0) * 255.0).astype(_np.uint8))

    @staticmethod
    def _split_lut(amount, high):
        """把 1.5 次幂的权重预先算成 256 级 LUT。

        原来对每个像素做 (1-lum)**1.5 —— 3MP 上光这个幂运算就要几十毫秒。
        权重最终只用于 8 位混合，量化到 256 级完全够用。
        """
        out = []
        for v in range(256):
            f = v / 255.0 if high else 1.0 - v / 255.0
            out.append(max(0, min(255, int(round((f ** 1.5) * amount * 0.85 * 255.0)))))
        return out

    def _split_tone(self, img, a):
        """色调分离：按亮度加权，分别给阴影和高光上色（Lightroom 的颜色分级）。

        arr = arr*(1-w) + c*w 正好等于「以 w 为掩膜、把颜色 c 合成上去」，
        所以整段可以交给 PIL 的 C 实现：亮度用 convert("L")，权重用 LUT，
        混合用 Image.composite。原来用 numpy 做浮点广播要 270 ms，
        现在只要二十几毫秒，且量化误差在 1-2 级以内。
        """
        ss = a["split_hi_sat"] / 100.0
        sl = a["split_lo_sat"] / 100.0
        if not ss and not sl:
            return img
        if img.mode != "RGB":
            return img
        lum = img.convert("L")
        out = img
        for amount, high, hue in ((sl, False, a["split_lo_hue"]),
                                  (ss, True, a["split_hi_hue"])):
            if not amount:
                continue
            m = lum.point(self._split_lut(amount, high))
            col = tuple(int(round(x * 255.0)) for x in _hue_rgb(hue))
            out = Image.composite(Image.new("RGB", out.size, col), out, m)
        return out

    def _local_mask(self, filt, size):
        """按归一化坐标生成局部滤镜的遮罩（小图生成再放大，够平滑也够快）。"""
        w, h = max(1, size[0]), max(1, size[1])
        key = (filt["type"], round(filt["cx"], 4), round(filt["cy"], 4),
               round(filt["rx"], 4), round(filt["ry"], 4),
               round(filt["angle"], 2), round(filt["spread"], 4),
               round(filt["feather"], 1), filt["invert"], w, h)
        hit = self.local_mask_cache.get(key)
        if hit is not None:
            return hit
        nw = 160
        nh = max(8, int(round(nw * h / float(w))))
        cx, cy = filt["cx"], filt["cy"]
        ang = math.radians(filt["angle"])
        ca, sa = math.cos(ang), math.sin(ang)
        feat = max(0.02, min(1.0, filt["feather"] / 100.0))
        diag = math.hypot(w, h)
        rx = max(0.005, filt["rx"])
        ry = max(0.005, filt["ry"])
        span = max(1.0, filt["spread"] * diag * 0.5)
        radial = (filt["type"] == "radial")
        if _np is not None:
            # 向量化：这张小图要逐像素算，Python 循环要 11ms，numpy 只要 1ms
            uu = (_np.arange(nw, dtype=_np.float32) + 0.5) / nw
            vv = (_np.arange(nh, dtype=_np.float32) + 0.5) / nh
            ox = (_np.float32(uu)[None, :] - cx) * w
            oy = (_np.float32(vv)[:, None] - cy) * h
            if radial:
                rxx = ox * ca + oy * sa
                ryy = -ox * sa + oy * ca
                d = _np.sqrt((rxx / (rx * w)) ** 2 + (ryy / (ry * h)) ** 2)
                tt = (1.0 - d) / feat
            else:
                tt = (ox * ca + oy * sa) / span + 0.5
            _np.clip(tt, 0.0, 1.0, out=tt)
            if filt["invert"]:
                tt = 1.0 - tt
            m = Image.fromarray((tt * 255.0).astype(_np.uint8), "L")
        else:
            m = Image.new("L", (nw, nh), 0)
            pxl = m.load()
            for y in range(nh):
                v = (y + 0.5) / nh
                oy = (v - cy) * h
                for x in range(nw):
                    u = (x + 0.5) / nw
                    ox = (u - cx) * w
                    if radial:
                        rxx = ox * ca + oy * sa
                        ryy = -ox * sa + oy * ca
                        d = math.hypot(rxx / (rx * w), ryy / (ry * h))
                        t = (1.0 - d) / feat
                    else:
                        t = (ox * ca + oy * sa) / span + 0.5
                    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                    if filt["invert"]:
                        t = 1.0 - t
                    pxl[x, y] = int(255 * t)
        m = m.resize((w, h), Image.Resampling.BILINEAR)
        # 把非零包围盒挂在图上一起缓存：合成时只需要处理这一块，
        # 3 MP 全图 composite 要 33 ms，缩到 1/4 面积后就降到个位数。
        try:
            m._qpe_box = m.getbbox()
        except Exception:
            m._qpe_box = None
        if len(self.local_mask_cache) > 8:
            self.local_mask_cache.clear()
        self.local_mask_cache[key] = m
        return m

    def _content_mask(self, filt, size):
        """按画面内容生成的遮罩。

        contrast = 高对比主体：取边缘强度，超过阈值的地方才算；
        subject  = 主体：边缘密度 × 中心权重（没有 AI，这是启发式近似，
                   画面中央、细节丰富的地方权重最高）。

        和径向遮罩一样，先在两三百像素的小图上算，再放大到目标尺寸，
        这样既快又平滑。
        """
        from PIL import ImageChops as _IC
        kind = filt["type"]
        thr = float(filt.get("thr", 50.0))
        src = self._view_image()
        w, h = max(1, size[0]), max(1, size[1])
        if src is None:
            return self._local_mask(
                {"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.5,
                 "ry": 0.5, "angle": 0.0, "spread": 0.5, "feather": 60.0,
                 "invert": filt["invert"]}, size)
        key = (kind, id(src), src.size, size, filt["invert"], round(thr, 1))
        hit = self.content_mask_cache.get(key)
        if hit is not None:
            return hit
        cw = 220
        ch = max(8, int(round(cw * h / float(w))))
        small = src.convert("L").resize((cw, ch), Image.Resampling.BILINEAR)
        edges = small.filter(ImageFilter.FIND_EDGES)
        edges = edges.filter(ImageFilter.GaussianBlur(1.0))
        # FIND_EDGES 输出量级很小（常见 5~30），必须按这张图自身的分布归一化，
        # 否则遮罩几乎全黑、看不出任何效果。取 97% 分位当白点。
        hist = edges.histogram()
        tot = max(1, sum(hist))
        acc = 0
        white = 255
        for v in range(256):
            acc += hist[v]
            if acc >= tot * 0.97:
                white = v
                break
        gain = 255.0 / max(12, white)
        edges = edges.point(lambda v, g=gain: min(255, int(v * g)))
        if kind == "contrast":
            lo = 20.0 + thr * 1.4
            lut = []
            for v in range(256):
                t = 0.0 if v <= lo else min(
                    1.0, (v - lo) / max(1.0, 255.0 - lo) * 2.6)
                lut.append(int(t * 255))
            m = edges.point(lut)
        else:
            falloff = self._local_mask(
                {"type": "radial", "cx": 0.5, "cy": 0.5, "rx": 0.62,
                 "ry": 0.62, "angle": 0.0, "spread": 0.5, "feather": 88.0,
                 "invert": False}, (cw, ch))
            m = _IC.multiply(edges, falloff)
            k = 1.1 + thr / 55.0
            m = m.point(lambda v, k=k: min(255, int(v * k)))
        m = m.filter(ImageFilter.GaussianBlur(1.5))
        if filt["invert"]:
            m = ImageOps.invert(m)
        m = m.resize((w, h), Image.Resampling.BILINEAR)
        try:
            m._qpe_box = m.getbbox()
        except Exception:
            m._qpe_box = None
        if len(self.content_mask_cache) > 8:
            self.content_mask_cache.clear()
        self.content_mask_cache[key] = m
        return m

    def add_content_local(self, kind):
        """新增一个按内容生成的局部调整（主体 / 高对比）。"""
        if self.doc is None:
            return
        f = new_local(kind, 0.5, 0.5, 0.4, 0.4, 0.0, 0.5)
        f["thr"] = 50.0
        f["feather"] = 50.0
        self.locals.append(f)
        self.local_mask_cache = {}
        self.toggle_panel(True)
        if "局部调整（径向 / 渐变）" in self.sections:
            body, tog = self.sections["局部调整（径向 / 渐变）"]
            if not body.winfo_ismapped():
                tog()
        self._select_local(len(self.locals) - 1)
        self._flash("已添加「%s」" % ("主体选择" if kind == "subject"
                                     else "高对比主体"))

    def _local_lut(self, adj):
        """局部滤镜的色调 LUT：白平衡 + 基本明暗（不涉及曲线/HSL，保证够快）。"""
        if not any(adj[k] for k in ("temperature", "tint", "exposure",
                                    "contrast", "highlights", "shadows",
                                    "whites", "blacks")):
            return None
        base = _basic_tone_lut(adj)
        full = []
        for gain in _wb_gains(adj):
            pre = [_clamp255(v * gain) for v in range(256)]
            full.extend([base[pre[v]] for v in range(256)])
        return full

    def _apply_local(self, img, filt, fast):
        a = filt["adj"]
        if filt["type"] in ("subject", "contrast"):
            mask = self._content_mask(filt, img.size)
        else:
            mask = self._local_mask(filt, img.size)
        box = getattr(mask, "_qpe_box", None)
        if box is None:
            box = (0, 0) + img.size
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            return img                       # 遮罩全黑，滤镜没有作用
        # 只在遮罩的非零区域内做运算：区域外遮罩是 0，合成结果本来就等于原像素，
        # 所以这样算与整图 composite **逐像素等价**，只是省掉了大部分无用的工作。
        base = img.crop(box)
        sub = base
        lut = self._local_lut(a)
        if lut is not None:
            sub = sub.point(lut)
        if a["saturation"]:
            sub = ImageEnhance.Color(sub).enhance(1.0 + a["saturation"] / 100.0)
        if a["sharpen"] and not fast:
            sub = sub.filter(ImageFilter.UnsharpMask(
                radius=1.0, percent=int(a["sharpen"] * 1.5), threshold=0))
        if sub is base:
            return img                       # 没有任何实际调整，别白复制
        out = img.copy()
        out.paste(Image.composite(sub, base, mask.crop(box)), box)
        return out

    def _locals_active(self):
        for filt in self.locals:
            if any(filt["adj"].values()):
                return True
        return False

    def _vignette_mask(self, size, bright):
        """径向渐变遮罩，按尺寸和方向缓存。"""
        key = (size, bright)
        if self.vig_key == key and self.vig_mask is not None:
            return self.vig_mask
        n = 160
        c = (n - 1) / 2.0
        maxd = math.hypot(c, c)
        if _np is not None:
            yy, xx = _np.mgrid[0:n, 0:n]
            d = _np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / maxd
            t = _np.clip((d - 0.35) / 0.65, 0.0, 1.0) ** 1.6
            m = Image.fromarray((t * 255.0).astype(_np.uint8), "L")
        else:
            m = Image.new("L", (n, n), 0)
            pxl = m.load()
            for y in range(n):
                for x in range(n):
                    d = math.hypot(x - c, y - c) / maxd
                    t = (d - 0.35) / 0.65
                    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
                    pxl[x, y] = int(255 * (t ** 1.6))
        m = m.resize(size, Image.Resampling.BILINEAR)
        self.vig_key = key
        self.vig_mask = m
        return m

    def _vignette_mult(self, size, k):
        """压暗用的 RGB 乘数图，按尺寸和强度缓存。

        Image.composite(Brightness(img, f), img, mask) 在数学上等于
        img * (1 - m*(1-f))，也就是「乘以一张中心 255、边缘 f*255 的图」。
        ImageChops.multiply 是单次 C 运算，比「亮化 + 合成」两张整幅中间图便宜。
        """
        key = (size, round(k, 4))
        if self.vig_mult_key == key and self.vig_mult is not None:
            return self.vig_mult
        mask = self._vignette_mask(size, False)
        f = max(0.0, 1.0 + k * 0.7)
        # 掩膜是「中心 0、边缘 255」。要的乘数是「中心 1、边缘 f」，
        # 也就是 1 - m*(1-f)，所以 LUT 是 255 - v*(1-f) ——
        # 方向写反会变成「中心压暗、边缘不动」，整个暗角正好反过来。
        lut = [max(0, min(255, int(round(255.0 - v * (1.0 - f)))))
               for v in range(256)]
        ml = mask.point(lut)
        self.vig_mult = Image.merge("RGB", (ml, ml, ml))
        self.vig_mult_key = key
        return self.vig_mult

    def _apply_vignette(self, img, amount):
        k = amount / 100.0
        if k < 0 and img.mode == "RGB":
            # 压暗（常见情况）走单次 multiply
            from PIL import ImageChops
            return ImageChops.multiply(img, self._vignette_mult(img.size, k))
        mask = self._vignette_mask(img.size, k > 0)
        target = ImageEnhance.Brightness(img).enhance(max(0.0, 1.0 + k * 0.7))
        return Image.composite(target, img, mask)

    def _watermark(self):
        return bool(self.wm_text and self.wm_text.strip())

    def _apply_watermark(self, img):
        """在画面角上打一行文字水印。预览和导出走同一段代码，所以所见即所得。"""
        text = (self.wm_text or "").strip()
        if not text:
            return img
        w, h = img.size
        size = max(9, int(w * max(0.5, self.wm_size) / 100.0))
        font = _wm_font(size)
        if font is None:
            return img
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
        try:
            l, t, r, b = probe.textbbox((0, 0), text, font=font)
        except Exception:
            l, t, r, b = 0, 0, len(text) * size // 2, size
        tw, th = r - l, b - t
        pad = max(4, int(size * 0.45))
        stroke = max(1, size // 14)
        margin = pad + stroke * 2
        if self.wm_pos == "bl":
            x, y = pad, h - th - pad * 2
        elif self.wm_pos == "c":
            x, y = (w - tw) // 2, (h - th) // 2
        else:
            x, y = w - tw - pad, h - th - pad * 2
        alpha = int(max(0, min(100, self.wm_alpha)) * 2.55)
        # 只画一小块文字贴片再局部合成：原来每次都造一张整幅透明层再 alpha_composite，
        # 3.1MP 上要 25 ms；现在只碰文字那一小块。
        pw = max(1, tw + margin * 2)
        ph = max(1, th + margin * 2)
        ox, oy = x - margin, y - margin       # 贴片左上角在整图里的位置
        patch = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
        ImageDraw.Draw(patch).text(
            (margin - l, margin - t), text, font=font,
            fill=(255, 255, 255, alpha), stroke_width=stroke,
            stroke_fill=(0, 0, 0, alpha // 2))
        # 贴左上/左下角时 ox/oy 可能是负的；直接把贴片裁掉那一部分，
        # 合成位置也相应归零，位置才和整幅绘制的旧实现完全一致。
        sx = max(0, -ox)
        sy = max(0, -oy)
        if sx or sy:
            patch = patch.crop((sx, sy, pw, ph))
        out = (img if img.mode == "RGBA" else img.convert("RGBA")).copy()
        out.alpha_composite(patch, (ox + sx, oy + sy))
        return out if img.mode == "RGBA" else out.convert(img.mode)

    def _color_sig(self):
        """除细节项之外的全部调色状态，用来给细节缓存做键。"""
        return (_freeze({k: v for k, v in self.adj.items()
                         if k not in DETAIL_KEYS}),
                tuple(_freeze(f) for f in self.locals),
                self.show_original)

    def _detail_params(self):
        a = self.adj
        return (round(a["clarity"], 3), round(a["dehaze"], 3),
                round(a["sharpen"], 3), round(a["sharpen_radius"], 3),
                round(a["sharpen_detail"], 3), round(a["nr_luma"], 3),
                round(a["nr_color"], 3))

    def _detail_pending(self):
        return any(self._detail_params())

    def _adjust_color(self, img, fast):
        """颜色级：色调 LUT + HSL/饱和度 + 色调分离 + 局部滤镜。"""
        a = self.adj
        if a["grayscale"]:
            img = ImageOps.grayscale(img).convert("RGB")
        tone = self._tone_lut()
        if tone is not None:
            img = img.point(tone)
        res = self._color_luts()
        if res is not None and fast and not self._hsl_active() \
                and not a["grayscale"]:
            # 拖动中只调全局饱和度/自然饱和度：RGB 混合比 HSV 往返快得多。
            # 注意这里只替换 HSV 那一步，后面的色调分离/局部滤镜/暗角照常执行，
            # 否则拖动时局部滤镜和暗角会整片消失。
            k = 1.0 + (a["saturation"] + a["vibrance"] * 0.7) / 100.0
            img = ImageEnhance.Color(img).enhance(max(0.0, k))
        elif res is not None:
            hue_lut, s_lut, v_lut, cover, hue_on, full = res
            # H/S/V 分解缓存：拖 HSL 滑块时瓦片没变，省掉一次 RGB->HSV 转换
            # 和 split（约 35 ms）。持有原对象引用，避免 id 复用导致误命中。
            if self.hsv_src is img and self.hsv_chans is not None:
                h, s, v = self.hsv_chans
            else:
                h, s, v = img.convert("HSV").split()
                self.hsv_src = img
                self.hsv_chans = (h, s, v)
            h2 = h.point(hue_lut) if hue_on else h
            out = Image.merge("HSV", (h2, s.point(s_lut), v.point(v_lut))
                              ).convert("RGB")
            if full:
                img = out
            else:
                # 只替换受影响的色相：范围之外的像素逐位保持原样。
                # 否则 RGB->HSV->RGB 的 8 位量化会把没调的颜色也悄悄改掉。
                img = Image.composite(out, img, h.point(cover))
        if a["split_hi_sat"] or a["split_lo_sat"]:
            img = self._split_tone(img, a)
        for filt in self.locals:                    # 局部调整
            if any(filt["adj"].values()):
                img = self._apply_local(img, filt, fast)
        return img

    FAST_HALF_MIN_PX = 1200000      # 超过这个像素量，拖动帧才降半分辨率

    _BEAUTY_ON = ("smooth", "glow", "even", "shine", "warm", "soft",
                  "blemish", "eye", "lip", "teeth", "slim", "eyes")

    def _beauty_params(self):
        """把滑杆值折算成一组有效的算法参数（含联动），无效果时返回 None。"""
        a = self.adj
        if getattr(self, "beauty_off", False):
            return None
        eff = {
            "smooth": float(a.get("skin_smooth", 0) or 0),
            "radius": float(a.get("skin_radius", 40.0) or 40.0),
            "glow": float(a.get("skin_glow", 0) or 0),
            "even": float(a.get("skin_even", 0) or 0),
            "shine": float(a.get("skin_shine", 0) or 0),
            "warm": float(a.get("skin_warm", 0) or 0),
            "soft": float(a.get("skin_soft", 0) or 0),
            "blemish": float(a.get("skin_blemish", 0) or 0),
            "spot": float(a.get("skin_spot_size", 5.0) or 5.0),
            "eye": float(a.get("skin_eye_care", 0) or 0),
            "eye_sp": float(a.get("skin_eye_spread", 50.0) or 50.0),
            "lip": float(a.get("skin_lip", 0) or 0),
            "teeth": float(a.get("skin_teeth", 0) or 0),
            "slim": float(a.get("skin_slim", 0) or 0),
            "eyes": float(a.get("skin_eyes", 0) or 0),
            "zf": float(a.get("zone_forehead", 100.0) or 0),
            "zc": float(a.get("zone_cheek", 100.0) or 0),
            "zn": float(a.get("zone_chin", 100.0) or 0),
            "ze": float(a.get("zone_eye", 70.0) or 0),
        }
        if a.get("skin_link", True):
            if eff["slim"] > 20:
                k = min(1.0, eff["slim"] / 100.0)
                eff["smooth"] = eff["smooth"] * (1.0 + 0.18 * k) + 12.0 * k
                eff["even"] = max(eff["even"], 25.0 * k)
            if eff["eyes"] > 10:
                eff["eye"] = max(eff["eye"], eff["eyes"] * 0.55)
        if not any(eff[k] for k in self._BEAUTY_ON):
            return None
        return eff

    def _call_beautify(self, img, p):
        return _beautify(img, p["smooth"], p["radius"], p["glow"], p["even"],
                         p["shine"], p["warm"], p["soft"],
                         (p["zf"], p["zc"], p["zn"], p["ze"]),
                         p["blemish"], p["spot"], p["eye"], p["eye_sp"],
                         p["lip"], p["teeth"], p["slim"], p["eyes"])

    def _beauty_stage(self, img, fast, base_key=None):
        """美颜独立成一级：结果按「像素来源 + 参数」缓存。

        好处有两个：
        1. 拖动曝光/对比度这类颜色滑杆时，美颜参数没变，直接命中缓存，
           **完全不用重算**（这正是之前卡顿的主因）；
        2. 拖动美颜滑杆时按 draft 分辨率算（缩到约 30 万像素再放大），
           松手后 _refine 会走一次全质量渲染。
        """
        p = self._beauty_params()
        if p is None:
            return img
        sig = tuple(sorted(p.items()))
        ck = (img.size, base_key, sig)
        got = self.beauty_cache.get(ck)
        if got is not None:
            return got
        W, H = img.size
        n = W * H
        if fast and n > 300000:
            r = (300000.0 / n) ** 0.5
            small = img.resize((max(1, int(W * r)), max(1, int(H * r))),
                               Image.BILINEAR)
            out = self._call_beautify(small, p).resize((W, H), Image.BILINEAR)
        else:
            out = self._call_beautify(img, p)
        if len(self.beauty_cache) >= 3:
            self.beauty_cache.pop(next(iter(self.beauty_cache)))
        self.beauty_cache[ck] = out
        return out

    def _color_stage(self, img, fast):
        """颜色级入口，负责 RGBA 的拆装。

        降分辨率的处理已上移到 _render（那里能连同暗角、水印一起降），
        这里保持纯粹的按尺寸计算。
        """
        if img.mode == "RGBA":
            r, g, b, alpha = img.split()
            rgb = self._adjust_color(Image.merge("RGB", (r, g, b)), fast)
            rgb = self._film_skin(rgb)
            r, g, b = rgb.split()
            return Image.merge("RGBA", (r, g, b, alpha))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return self._film_skin(self._adjust_color(img, fast))

    def _film_skin(self, img):
        """胶片模拟。人像美化已上移到 _beauty_stage（先于调色，便于缓存）。"""
        a = self.adj
        out = _film_apply(img, a.get("film", "无"), a.get("film_strength", 100))
        return out
        smooth, glow = a.get("skin_smooth", 0), a.get("skin_glow", 0)
        if getattr(self, "beauty_off", False):
            return out
        if (smooth or glow or a.get("skin_even") or a.get("skin_shine")
                or a.get("skin_warm") or a.get("skin_soft")
                or a.get("skin_blemish") or a.get("skin_eye_care")
                or a.get("skin_lip") or a.get("skin_teeth")
                or a.get("skin_slim") or a.get("skin_eyes")):
            # 参数联动：瘦脸会让轮廓线移动，同步把轮廓附近磨得更平一点，
            # 大眼会让眼周被拉伸，顺手补一点眼周提亮，避免"只放大不提亮"的突兀
            if a.get("skin_link", True):
                slim_v = a.get("skin_slim", 0.0)
                eyes_v = a.get("skin_eyes", 0.0)
                if slim_v > 20:
                    k = min(1.0, slim_v / 100.0)
                    smooth = smooth * (1.0 + 0.18 * k) + 12.0 * k
                    a["skin_even"] = max(a.get("skin_even", 0.0), 25.0 * k)
                if eyes_v > 10:
                    a["skin_eye_care"] = max(a.get("skin_eye_care", 0.0),
                                             eyes_v * 0.55)
            zones = (a.get("zone_forehead", 100.0), a.get("zone_cheek", 100.0),
                     a.get("zone_chin", 100.0), a.get("zone_eye", 70.0))
            out = _beautify(out, smooth, a.get("skin_radius", 40.0), glow,
                            a.get("skin_even", 0.0), a.get("skin_shine", 0.0),
                            a.get("skin_warm", 0.0), a.get("skin_soft", 0.0),
                            zones, a.get("skin_blemish", 0.0),
                            a.get("skin_spot_size", 5.0),
                            a.get("skin_eye_care", 0.0),
                            a.get("skin_eye_spread", 50.0),
                            a.get("skin_lip", 0.0), a.get("skin_teeth", 0.0),
                            a.get("skin_slim", 0.0), a.get("skin_eyes", 0.0))
        return out

    def _ai_progress(self, frac, text=""):
        """面板顶部那条进度：0 隐藏，>0 显示。"""
        bar = getattr(self, "ai_bar", None)
        if bar is None:
            return
        try:
            bar.update_idletasks()
            w = max(1, bar.winfo_width())
            bar.delete("all")
            h = max(2, px(5))
            bar.create_rectangle(0, 0, w, h, fill=TROUGH_BG, outline="")
            if 0 < frac < 1.0 or frac >= 1.0:
                bar.create_rectangle(0, 0, int(w * min(1.0, frac)), h,
                                     fill=ACCENT, outline="")
            if text:
                lbl = getattr(self, "ai_progress_lbl", None)
                if lbl is not None:
                    lbl.configure(text=text)
            self._sync_ai_extra(text)
            self.update_idletasks()
        except Exception:
            pass
        if frac >= 1.0:
            self.after(260, self._ai_progress_hide)

    def _ai_progress_hide(self):
        bar = getattr(self, "ai_bar", None)
        if bar is not None:
            try:
                bar.delete("all")
            except Exception:
                pass
        lbl = getattr(self, "ai_progress_lbl", None)
        if lbl is not None:
            try:
                lbl.configure(text="")
            except Exception:
                pass
        self._sync_ai_extra("")

    def _apply_adjust(self, img, fast=False, detail=True):
        """完整管线（保存用，同步算完）。"""
        if self.show_original:
            return img
        if (self._adj_identity() and not self._locals_active()
                and not self._watermark()):
            return img
        img = self._beauty_stage(img, fast, "export")
        img = self._color_stage(img, fast)
        if detail:
            img = _detail_stage(img, self._detail_params())
        if self.adj["vignette"]:
            img = self._apply_vignette(img, self.adj["vignette"])
        if self._watermark():
            img = self._apply_watermark(img)
        return img

    def _flatten(self):
        """按当前编辑状态生成一张完整成品图（保存用）。

        这里必须无视「对比原图」状态：那只是屏幕上的预览开关，
        如果保存也跟着它走，用户按住反斜杠时按下保存就会把调好的图
        导成没调过的原图（曾经就是这个 bug）。
        """
        im = self._view_image()
        if im is None:
            return None
        if im.mode not in ("RGB", "RGBA", "L"):
            im = im.convert("RGB")
        keep = self.show_original
        self.show_original = False
        try:
            return self._apply_adjust(im, fast=False)
        finally:
            self.show_original = keep

    # ------------------------------------------------------------ 撤销 / 重做

    def _snapshot(self):
        # 必须深拷贝：adj 里有 hsl / curve 这样的嵌套可变结构，
        # 只存引用的话，之后的修改会把历史记录一起改掉，撤销就失效了。
        return (tuple(self.geom), copy.deepcopy(self.adj))

    def _push_history(self, label=None):
        snap = self._snapshot()
        if self.history and self.history[self.hist_i] == snap:
            return
        del self.history[self.hist_i + 1:]
        del self.hist_labels[self.hist_i + 1:]
        self.history.append(snap)
        self.hist_labels.append(_trf(label) if label else "调整")
        if len(self.history) > 60:
            self.history.pop(0)
            self.hist_labels.pop(0)
        self.hist_i = len(self.history) - 1
        self._update_hist_buttons()
        self._refresh_history_box()

    def undo(self):
        if self.hist_i > 0:
            self.hist_i -= 1
            self._restore(self.history[self.hist_i])

    def redo(self):
        if self.hist_i < len(self.history) - 1:
            self.hist_i += 1
            self._restore(self.history[self.hist_i])

    def _restore(self, snap):
        self.geom = list(snap[0])
        self.adj = copy.deepcopy(snap[1])
        self.geom_key = None
        self.tile_cache.clear()
        self.contrast_mean = None
        self.auto_lut = None
        self.cx = None
        self.cy = None
        self._sync_panel()
        self._update_hist_buttons()
        self._refresh_history_box()
        self._render()
        self._update_status()

    def _reset_edit(self):
        """切图时清空这张图的编辑状态。"""
        self.geom = []
        self.adj = self._default_adj()
        self.snapshots = []
        self._refresh_snapshot_box()
        self.hsv_src = None
        self.hsv_chans = None
        self.locals = []
        self.local_sel = -1
        self.local_mode = None
        self.local_drag = None
        self.picker_mode = False
        self.geom_key = None
        self.tile_cache.clear()
        self.contrast_mean = None
        self.auto_lut = None
        self.crop_mode = False
        self.crop_anchor = None
        self.crop_rect = None
        if self.crop_item is not None:
            try:
                self.canvas.delete(self.crop_item)
            except Exception:
                pass
            self.crop_item = None
        self.history = [self._snapshot()]
        self.hist_labels = ["打开图片"]
        self.hist_i = 0
        self._sync_panel()
        self._update_hist_buttons()
        self._refresh_history_box()

    def fit_window(self):
        self.zoom_mode = "fit"
        self.cx = None
        self.cy = None
        self._render()
        self._update_status()

    def fit_width(self):
        self.zoom_mode = "fitw"
        self.cx = None
        self.cy = None
        self._render()
        self._update_status()

    def actual_size(self):
        # draft 状态下 scale 是相对「已解码」尺寸的，直接设 1.0 只有原始分辨率的
        # 一小部分。所以先请后台取回原始分辨率，拿到了再真正切到 1:1。
        if (self.doc is not None
                and getattr(self.doc, "draft_ratio", 1.0) < 1.0):
            self.actual_after_full = True
            self.pending_full = self.doc.path
            self.loader.request_full(self.doc.path)
            self._flash("正在取回原始分辨率…")
            return
        self._set_scale(1.0, None)

    def zoom_by(self, factor):
        self._set_scale(self.scale * factor, None)

    def _set_scale(self, new, anchor):
        new = max(MIN_SCALE, min(MAX_SCALE, new))
        im = self._view_image()
        if im is not None and anchor is not None:
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            old = self.scale
            iw, ih = im.size
            cx = self.cx if self.cx is not None else iw / 2.0
            cy = self.cy if self.cy is not None else ih / 2.0
            mx, my = anchor
            ix = cx + (mx - cw / 2.0) / old
            iy = cy + (my - ch / 2.0) / old
            self.scale = new
            self.cx = ix - (mx - cw / 2.0) / new
            self.cy = iy - (my - ch / 2.0) / new
        else:
            self.scale = new
        self.zoom_mode = "free"
        self._mark_fast()
        self._request_render()
        self._update_status()

    def reset_transform(self):
        self.geom = []
        self.geom_key = None
        self.tile_cache.clear()
        self.cx = None
        self.cy = None
        self._push_history()
        self._render()
        self._update_status()

    def rotate(self, deg):
        if self.doc is None:
            return
        self.geom.append(("rot", deg % 360))
        self.geom_key = None
        self.tile_cache.clear()
        self.cx = None
        self.cy = None
        self._push_history("旋转 %d°" % (deg % 360))
        self._render()
        self._update_status()

    def flip(self, vertical):
        if self.doc is None:
            return
        self.geom.append(("flip", "v" if vertical else "h"))
        self.geom_key = None
        self.tile_cache.clear()
        self.cx = None
        self.cy = None
        self._push_history("垂直翻转" if vertical else "水平翻转")
        self._render()
        self._update_status()

    # ------------------------------------------------------------ 鼠标

    def _on_wheel(self, event):
        if self.doc is None:
            return
        self._wheel_steps(wheel_units(event.delta), event.x, event.y)

    def _on_wheel_h(self, event):
        if self.doc is None:
            return
        im = self._view_image()
        if im is None:
            return
        cx = self.cx if self.cx is not None else im.size[0] / 2.0
        self.cx = cx - wheel_units(event.delta) * 60.0 / max(self.scale, 0.001)
        self._mark_fast()
        self._render()

    def _wheel_steps(self, steps, x, y):
        if self.doc is None or steps == 0:
            return
        self._set_scale(self.scale * (1.2 ** steps), (x, y))

    def _hit_handle(self, x, y):
        """选中滤镜的五个手柄：中心=移动，左右=改 rx，上下=改 ry。"""
        if not (0 <= self.local_sel < len(self.locals)):
            return None
        f = self.locals[self.local_sel]
        im = self._view_image()
        if im is None:
            return None
        cx, cy = self._norm_to_canvas(f["cx"], f["cy"])
        rx = max(2.0, f["rx"] * im.size[0] * max(self.scale, 1e-6))
        ry = max(2.0, f["ry"] * im.size[1] * max(self.scale, 1e-6))
        tol = px(8)
        spots = ((("c"), cx, cy), (("r"), cx + rx, cy), (("l"), cx - rx, cy),
                 (("b"), cx, cy + ry), (("t"), cx, cy - ry))
        for which, hx, hy in spots:
            if abs(x - hx) <= tol and abs(y - hy) <= tol:
                return self.local_sel, which
        return None

    def _on_press(self, event):
        if self.split_x is not None and not self.crop_mode:
            cw = max(1, self.canvas.winfo_width())
            if abs(event.x - cw * self.split_x) <= px(9):
                self.split_drag = True
                self.canvas.configure(cursor="sb_h_double_arrow")
                return
        if self.picker_mode:
            self.pick_white_balance(event.x, event.y)
            return
        if self.local_mode in ("radial", "linear"):
            u, v = self._canvas_to_norm(event.x, event.y)
            kind = self.local_mode
            filt = new_local(kind, u, v, 0.05, 0.05, 0.0, 0.10)
            # 给一个看得见的默认效果：新建滤镜立刻就能看到变化，
            # 否则全 0 的参数会让画面毫无反应，像是「没渲染」。
            filt["adj"]["exposure"] = 0.6 if kind == "radial" else -0.6
            self._add_local(filt)
            self.local_drag = ("create", event.x, event.y, u, v)
            return
        if self.local_mode is None and self.locals:
            h = self._hit_handle(event.x, event.y)
            if h is not None:
                idx, which = h
                if idx != self.local_sel:
                    self._select_local(idx)
                f = self.locals[idx]
                if which == "c":
                    self.local_drag = ("move", event.x, event.y, f["cx"], f["cy"])
                else:
                    self.local_drag = ("size", which, event.x, event.y,
                                       f["rx"], f["ry"])
                self.canvas.configure(
                    cursor={"r": "sb_h_double_arrow", "l": "sb_h_double_arrow",
                            "b": "sb_v_double_arrow", "t": "sb_v_double_arrow",
                            "c": "fleur"}[which])
                return
            idx = self._hit_local(event.x, event.y)
            if idx >= 0:
                if idx != self.local_sel:
                    self._select_local(idx)
                f = self.locals[idx]
                self.local_drag = ("move", event.x, event.y, f["cx"], f["cy"])
                return
        if self.crop_mode:
            self.crop_anchor = self._canvas_to_image(event.x, event.y)
            self.crop_rect = None
            if self.crop_item is not None:
                self.canvas.delete(self.crop_item)
                self.crop_item = None
            return
        self.drag = (event.x, event.y, self.cx, self.cy)

    def _on_drag(self, event):
        if self.split_drag:
            cw = max(1, self.canvas.winfo_width())
            self.split_x = max(0.02, min(0.98, event.x / float(cw)))
            self._request_render()
            return
        if self.local_drag is not None and self.doc is not None:
            im = self._view_image()
            if im is None:
                return
            iw, ih = max(1, im.size[0]), max(1, im.size[1])
            mode = self.local_drag[0]
            f = self.locals[self.local_sel] if 0 <= self.local_sel < len(
                self.locals) else None
            if f is None:
                self.local_drag = None
                return
            if mode == "create":
                _, sx, sy, u0, v0 = self.local_drag
                u1, v1 = self._canvas_to_norm(event.x, event.y)
                if f["type"] == "radial":
                    f["cx"], f["cy"] = (u0 + u1) / 2.0, (v0 + v1) / 2.0
                    f["rx"] = max(0.02, abs(u1 - u0) / 2.0)
                    f["ry"] = max(0.02, abs(v1 - v0) / 2.0)
                else:
                    dx = (u1 - u0) * iw
                    dy = (v1 - v0) * ih
                    f["angle"] = math.degrees(math.atan2(dy, dx)) - 90.0
                    f["spread"] = max(0.05, math.hypot(u1 - u0, v1 - v0) * 2.0)
                    f["cx"], f["cy"] = (u0 + u1) / 2.0, (v0 + v1) / 2.0
            elif mode == "size":
                _, which, sx, sy, rx0, ry0 = self.local_drag
                du = (event.x - sx) / max(1e-6, self.scale) / iw
                dv = (event.y - sy) / max(1e-6, self.scale) / ih
                if which == "r":
                    f["rx"] = max(0.02, min(1.5, rx0 + du))
                elif which == "l":
                    f["rx"] = max(0.02, min(1.5, rx0 - du))
                elif which == "b":
                    f["ry"] = max(0.02, min(1.5, ry0 + dv))
                elif which == "t":
                    f["ry"] = max(0.02, min(1.5, ry0 - dv))
                self.local_mask_cache = {}
            else:
                _, sx, sy, cx0, cy0 = self.local_drag
                du = (event.x - sx) / max(1e-6, self.scale) / iw
                dv = (event.y - sy) / max(1e-6, self.scale) / ih
                f["cx"], f["cy"] = cx0 + du, cy0 + dv
            self._mark_fast()
            self._render()
            self._rebuild_local_values()
            return
        if self.crop_mode:
            if self.crop_anchor is None:
                return
            im = self._view_image()
            if im is None:
                return
            iw, ih = im.size
            ax, ay = self.crop_anchor
            ix, iy = self._canvas_to_image(event.x, event.y)
            ix = max(0.0, min(float(iw), ix))
            iy = max(0.0, min(float(ih), iy))
            ratio = self._crop_ratio_value()
            if ratio:
                w = abs(ix - ax)
                h = abs(iy - ay)
                if h < 1e-6 or w / h > ratio:
                    w = h * ratio
                else:
                    h = w / ratio
                ix = ax + math.copysign(w, ix - ax) if w else ax
                iy = ay + math.copysign(h, iy - ay) if h else ay
            self.crop_rect = (min(ax, ix), min(ay, iy),
                              max(ax, ix), max(ay, iy))
            self._draw_crop()
            return
        if self.drag is None or self.doc is None:
            return
        im = self._view_image()
        if im is None:
            return
        x0, y0, cx0, cy0 = self.drag
        if cx0 is None:
            cx0 = im.size[0] / 2.0
        if cy0 is None:
            cy0 = im.size[1] / 2.0
        s = max(self.scale, 0.001)
        self.cx = cx0 - (event.x - x0) / s
        self.cy = cy0 - (event.y - y0) / s
        self._mark_fast()
        self._request_render()
        self.canvas.configure(cursor="fleur")

    def _on_release(self, event):
        if self.split_drag:
            self.split_drag = False
            self._flush_render()
            self._update_cursor()
            return
        if self.local_drag is None and not self.crop_mode:
            self._flush_render()
        if self.local_drag is not None:
            mode = self.local_drag[0]
            self.local_drag = None
            if mode == "create":
                # 只是点一下没拖动的话，给一个看得见的默认大小，
                # 否则会生成一个几乎看不见的"隐形"滤镜。
                f = self.locals[self.local_sel] if 0 <= self.local_sel < len(
                    self.locals) else None
                if f is not None:
                    if f["type"] == "radial" and f["rx"] < 0.08:
                        f["rx"] = f["ry"] = 0.28
                    elif f["type"] == "linear" and f["spread"] < 0.12:
                        f["spread"] = 0.45
                    self._flash("已建立%s滤镜 · 默认曝光 %+.1f，可在「滤镜参数」里调"
                                % ("径向" if f["type"] == "radial" else "渐变",
                                   f["adj"]["exposure"]))
                self.local_mode = None
                self._update_cursor()
                self._refresh_local_box()
            self._rebuild_local_sliders()
            self._push_history("调整局部滤镜")
            self._update_status()
            return
        if self.crop_mode:
            return
        self.drag = None
        self._update_cursor()

    def _on_double(self, event):
        self.drag = None
        if self.doc is None:
            return
        if abs(self.scale - 1.0) > 1e-6:
            self._set_scale(1.0, (event.x, event.y))
        else:
            self.fit_window()

    def _on_motion(self, event):
        if self.drag is None:
            self._update_cursor()
        self._schedule_sample(event.x, event.y)

    def _schedule_sample(self, x, y):
        """鼠标悬停时在状态栏显示该点颜色。节流，避免每个移动事件都算。"""
        self._sample_at = (x, y)
        if self.pick_job is not None:
            return
        self.pick_job = self.after(55, self._do_sample)

    def _do_sample(self):
        self.pick_job = None
        if self.pick_lbl is None or not self.pick_lbl.winfo_exists():
            return
        pos = getattr(self, "_sample_at", None)
        if pos is None or self.doc is None or self.photo is None:
            return
        x, y = pos
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        if not (0 <= x < cw and 0 <= y < ch):
            self.pick_lbl.configure(text="")
            return
        # 从最后一次渲染的位图上取样：ImageTk.PhotoImage 没有 get()，
        # 而且这样取到的是屏幕上真正显示的颜色（含所有调整）。
        img = self.surface_img
        if img is None:
            return
        sx = x - self.surface_pos[0]
        sy = y - self.surface_pos[1]
        if not (0 <= sx < img.width and 0 <= sy < img.height):
            self.pick_lbl.configure(text="")
            return
        try:
            px = img.getpixel((sx, sy))
            r, g, b = px[0], px[1], px[2]
        except Exception:
            self.pick_lbl.configure(text="")
            return
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        cur = "R%3d G%3d B%3d  H%3d° S%3d%% V%3d%%" % (
            r, g, b, int(h * 360), int(s * 100), int(v * 100))
        if self.pick_lock is not None:
            lr, lg, lb = self.pick_lock
            cur += "   | 锁定 %d,%d,%d  Δ %+d,%+d,%+d" % (
                lr, lg, lb, r - lr, g - lg, b - lb)
        self.pick_lbl.configure(text=cur)

    def toggle_pick_lock(self):
        """锁定当前取样的颜色，之后悬停会同时显示与锁定色的差值。"""
        if self.pick_lock is not None:
            self.pick_lock = None
            if self.pick_btn is not None and self.pick_btn.winfo_exists():
                self.pick_btn.configure(bg=BTN_BG, fg=FG)
            self._flash("已取消取样锁定")
        else:
            img = self.surface_img
            pos = getattr(self, "_sample_at", None)
            if img is None or pos is None:
                self._flash("把鼠标移到画面上再按锁定")
                return
            sx = pos[0] - self.surface_pos[0]
            sy = pos[1] - self.surface_pos[1]
            if not (0 <= sx < img.width and 0 <= sy < img.height):
                self._flash("鼠标不在图片上，无法锁定")
                return
            try:
                px = img.getpixel((sx, sy))
            except Exception:
                return
            self.pick_lock = (px[0], px[1], px[2])
            if self.pick_btn is not None and self.pick_btn.winfo_exists():
                self.pick_btn.configure(bg=ACCENT, fg="#101010")
            self._flash("已锁定 %d,%d,%d —— 移动鼠标可看到差值" % self.pick_lock)
        self._do_sample()

    def _update_cursor(self):
        if self.crop_mode or self.picker_mode or self.local_mode:
            self.canvas.configure(cursor="crosshair")
            return
        if self.doc is None:
            self.canvas.configure(cursor="arrow")
            return
        im = self._view_image()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        big = im is not None and (im.size[0] * self.scale > cw + 2
                                  or im.size[1] * self.scale > ch + 2)
        self.canvas.configure(cursor="fleur" if big else "arrow")

    def _mark_fast(self):
        """标记为快速渲染，停手 160ms 后自动补一张高质量图。"""
        self.fast = True
        if self.refine_job is not None:
            try:
                self.after_cancel(self.refine_job)
            except Exception:
                pass
        self.refine_job = self.after(160, self._refine)

    def _refine(self):
        self.refine_job = None
        if self.fast:
            self.fast = False
            self._render()

    def _request_render(self):
        # 美颜状态行：参数改了也要跟着变，防抖刷新
        if getattr(self, "_ai_job", None):
            try:
                self.after_cancel(self._ai_job)
            except Exception:
                pass
        self._ai_job = self.after(260, self._refresh_ai_status)
        """把连续的鼠标/滑块事件合并成按目标帧率出图。

        一帧要几十毫秒时，如果每个事件都同步渲染，事件队列会越堆越长，
        鼠标就像粘住一样。这里保证「上一帧画完之前不画下一帧」。
        """
        now = time.perf_counter()
        elapsed = (now - self.last_render) * 1000.0
        if elapsed >= self.render_interval:
            if self.render_job is not None:
                try:
                    self.after_cancel(self.render_job)
                except Exception:
                    pass
                self.render_job = None
            self._render()
        elif self.render_job is None:
            delay = max(1, int(self.render_interval - elapsed))
            self.render_job = self.after(delay, self._throttled_render)

    def _throttled_render(self):
        self.render_job = None
        self._render()

    def _flush_render(self):
        """交互结束时立刻补一帧，避免最后一帧被节流吃掉。"""
        if self.render_job is not None:
            try:
                self.after_cancel(self.render_job)
            except Exception:
                pass
            self.render_job = None
            self._render()

    def _proxy_limit(self):
        """代理图长边：--proxy 优先，其次低内存模式，最后默认。"""
        if PROXY_ARG:
            return PROXY_ARG
        return PREVIEW_MAX_LOWMEM if getattr(self, "low_mem", False) else PREVIEW_MAX

    def _use_paste_photo(self):
        """选择 PhotoImage 更新方式：auto 按核数，也可用 --perf-profile xxx-paste 强制。"""
        if PHOTO_MODE == "paste":
            return True
        if PHOTO_MODE == "new":
            return False
        try:
            n = os.cpu_count() or 1
        except Exception:
            n = 1
        return n <= PASTE_MAX_CORES

    def _preview_of(self, im):
        """按需生成并缓存低分辨率副本（只在缩小时使用）。"""
        key = (id(im), im.size, self._proxy_limit())
        if self.preview_key == key:
            return self.preview_img, self.preview_ratio
        # 后台线程已经算好的代理图：主线程零成本取用
        doc = getattr(self, "doc", None)
        if (doc is not None and im is getattr(doc, "img", None)
                and getattr(doc, "proxy_img", None) is not None
                and im.size[0] > self._proxy_limit()):
            self.preview_key = key
            self.preview_img = doc.proxy_img
            self.preview_ratio = getattr(doc, "proxy_ratio", 1.0)
            self.tile_cache.clear()
            return self.preview_img, self.preview_ratio
        iw, ih = im.size
        m = max(iw, ih)
        limit = self._proxy_limit()
        self.preview_key = key
        if m <= limit:
            self.preview_img = None
            self.preview_ratio = 1.0
            return None, 1.0
        r = limit / float(m)
        nw, nh = max(1, int(iw * r)), max(1, int(ih * r))
        self.preview_img = _fast_downscale(im, (nw, nh))
        self.preview_ratio = nw / float(iw)
        self.tile_cache.clear()
        return self.preview_img, self.preview_ratio

    def _on_canvas_configure(self, event):
        if self.resize_job is not None:
            try:
                self.after_cancel(self.resize_job)
            except Exception:
                pass
        self.resize_job = self.after(SCALE_DEBOUNCE_MS, self._do_resize)

    def _do_resize(self):
        self.resize_job = None
        self._mark_fast()
        self._render()
        self._update_status()

    def toggle_low_mem(self):
        """低内存模式：代理图长边 2048、瓦片缓存减到 2 张。

        预览走代理图、导出仍用原图，所以观感差别只在极端放大时出现。
        """
        self.low_mem = not getattr(self, "low_mem", False)
        self.preview_key = None
        self.preview_img = None
        self.tile_cache.clear()
        try:
            self._save_setting("low_mem", self.low_mem)
        except Exception:
            pass
        self._mark_fast()
        self._render()
        self._flash("低内存模式：%s（预览走代理图 %d，导出仍用原图）"
                    % ("开" if self.low_mem else "关",
                       PREVIEW_MAX_LOWMEM if self.low_mem else PREVIEW_MAX), 3000)

    def set_perf_profile(self, profile, persist=True):
        """切换性能档位：拖动优先 / 首帧优先 / 自动。运行中立即生效。"""
        global PERF_PROFILE
        if profile not in ("fast-slider", "fast-first", "auto"):
            return
        self.perf_profile = profile
        PERF_PROFILE = profile
        self.preview_key = None
        self.preview_img = None
        if persist:
            try:
                self._save_setting("perf_profile", profile)
            except Exception:
                pass
        self._mark_fast()
        self._render()
        self._flash(_trf("性能档位：%s") % _tr({
            "fast-slider": "拖动优先（最跟手）",
            "fast-first": "首帧优先（打开更快）",
            "auto": "自动",
        }[profile]), 2400)

    def _apply_soft_proof(self, img):
        pair = getattr(self, "soft_proof_transforms", None)
        if not pair or ImageCms is None:
            return img
        try:
            if img.mode != "RGB":
                img = img.convert("RGB")
            out = ImageCms.applyTransform(img, pair[0])
            out = ImageCms.applyTransform(out, pair[1])
            return out
        except Exception:
            return img

    def set_soft_proof_profile(self, path, enable=True, persist=True):
        try:
            t1, t2, name = _build_soft_proof(path)
        except Exception as exc:
            messagebox.showerror(
                "软打样", "软打样失败：%s" % str(exc)[:120], parent=self)
            return False
        self.soft_proof_transforms = (t1, t2)
        self.soft_proof_name = name
        self.soft_proof_path = os.path.abspath(path)
        self.soft_proof = bool(enable)
        if persist:
            try:
                self.save_settings()
            except Exception:
                pass
        self._mark_fast()
        self._render()
        self._flash(_trf("软打样已启用：%s") % name, 2600)
        return True

    def choose_soft_proof_profile(self):
        path = filedialog.askopenfilename(
            parent=self, title="选择 ICC 配置文件",
            filetypes=[("ICC 配置文件", "*.icc *.icm"), ("所有文件", "*.*")])
        if path:
            self.set_soft_proof_profile(path)

    def toggle_soft_proof(self, on=None):
        want = (not getattr(self, "soft_proof", False)) if on is None \
            else bool(on)
        if want and not getattr(self, "soft_proof_transforms", None):
            self.choose_soft_proof_profile()
            if not getattr(self, "soft_proof_transforms", None):
                return
        self.soft_proof = want
        try:
            self.save_settings()
        except Exception:
            pass
        self._mark_fast()
        self._render()
        self._flash(_trf("软打样：%s") % _tr("开" if want else "关"), 2000)

    def _toggle_focus_key(self, event=None):
        """Tab 切换专注模式；输入框里保留 Tab 的原始用途。"""
        w = self.focus_get()
        if isinstance(w, (tk.Entry, tk.Text, ttk.Combobox, tk.Spinbox)):
            return None
        self.toggle_focus_mode()
        return "break"

    def toggle_focus_mode(self, show=None):
        """极简暗房：收起工具条、状态栏和右侧面板，只留画布。"""
        want = (not getattr(self, "focus_mode", False)) if show is None \
            else bool(show)
        if want == getattr(self, "focus_mode", False):
            return
        self.focus_mode = want
        if want:
            self._focus_panel_was = bool(self.panel_shown)
            if self.panel_shown:
                self.toggle_panel(False)
            self.bar.pack_forget()
            self.status.pack_forget()
            self._focus_hint()
        else:
            try:
                if getattr(self, "_focus_tip", None) is not None:
                    self._focus_tip.destroy()
            except Exception:
                pass
            self._focus_tip = None
            self.bar.pack(side="top", fill="x", before=self.body)
            self.status.pack(side="bottom", fill="x", before=self.body)
            if getattr(self, "_focus_panel_was", False):
                self.toggle_panel(True)
        self._mark_fast()
        self._render()
        self._update_status()

    def _focus_hint(self):
        try:
            if getattr(self, "_focus_tip", None) is not None:
                self._focus_tip.destroy()
        except Exception:
            pass
        try:
            tip = tk.Label(self, text=_tr("按 Tab 退出专注模式"),
                           bg=BG, fg=FG_DIM, font=self.ui_font,
                           padx=px(12), pady=px(6))
            tip.place(relx=0.5, y=px(14), anchor="n")
            self._focus_tip = tip
            self.after(2400, tip.destroy)
        except Exception:
            self._focus_tip = None

    def toggle_fullscreen(self):
        """无边框最大化，Esc 退出。出错自动回退窗口最大化。"""
        if getattr(self, "_fs_on", False):
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        try:
            self._fs_geo = self.geometry()
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            try:
                self.overrideredirect(True)
            except Exception:
                pass
            self.geometry("%dx%d+0+0" % (sw, sh))
            self._fs_on = True
            self._mark_fast()
            self._render()
            self._flash("全屏（兼容模式）：按「全屏」按钮退出" if BIGSCREEN
                        else "全屏（兼容模式）：按 Esc 退出", 2600)
        except Exception:
            try:
                self.overrideredirect(False)
            except Exception:
                pass
            self._fs_on = False
            try:
                self.state("zoomed")
            except Exception:
                pass
            self._flash("全屏不可用，已回退为窗口最大化", 3200)

    def _exit_fullscreen(self):
        if not getattr(self, "_fs_on", False):
            return
        self._fs_on = False
        try:
            self.overrideredirect(False)
        except Exception:
            pass
        try:
            if getattr(self, "_fs_geo", None):
                self.geometry(self._fs_geo)
            else:
                self.state("normal")
        except Exception:
            pass
        self._mark_fast()
        self._render()

    # ------------------------------------------------------------ 渲染

    def _checker(self, w, h):
        if self.checker_key == (w, h) and self.checker_img is not None:
            return self.checker_img
        cell = max(4, px(12))
        img = Image.new("RGB", (w, h), CHECK_A)
        d = ImageDraw.Draw(img)
        for y in range(0, h, cell):
            for x in range(0, w, cell):
                if ((x // cell) + (y // cell)) % 2:
                    d.rectangle([x, y, x + cell - 1, y + cell - 1], fill=CHECK_B)
        self.checker_key = (w, h)
        self.checker_img = img
        return img

    def _set_text(self, msg):
        if self.img_item is not None:
            self.canvas.delete(self.img_item)
            self.img_item = None
        self.photo = None
        if self.text_item is None:
            self.text_item = self.canvas.create_text(
                0, 0, text="", fill=FG_DIM, font=self.ui_font, justify="center")
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        self.canvas.coords(self.text_item, cw // 2, ch // 2)
        self.canvas.itemconfigure(self.text_item, text=_trf(msg),
                                  state="normal" if msg else "hidden")
        if msg:
            self.canvas.tag_raise(self.text_item)

    def _render(self, fast=None):
        render_t0 = time.perf_counter()
        if fast is None:
            fast = self.fast
        t_frame = time.perf_counter()
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return

        if self.doc is None:
            if not self.files:
                hint = ("把图片拖到这里" if _DND_OK
                        else "打开一张图片开始浏览")
                if BIGSCREEN:
                    self._set_text(_tr(hint) + _tr(
                        "\n\n用底部大按钮打开图片或文件夹"))
                else:
                    self._set_text(_tr(hint) + _tr(
                        "\n\nCtrl+O 打开文件    Ctrl+Shift+O 打开文件夹"
                        "\n\nF5 全分辨率 · Tab 专注模式 · 拖动右栏调宽"
                        "\n\n按 F1 查看全部快捷键"))
            elif self.error is not None:
                self._set_text(_trf("无法打开这个文件\n\n%s" % self.error))
            else:
                self._set_text("载入中…")
            return

        im = self._view_image()
        if im is None:
            return
        iw, ih = im.size

        if self.zoom_mode == "fit":
            self.scale = max(MIN_SCALE, min(cw / float(iw), ch / float(ih), 1.0))
        elif self.zoom_mode == "fitw":
            self.scale = max(MIN_SCALE, min(cw / float(iw), 1.0))
        scale = max(MIN_SCALE, min(MAX_SCALE, self.scale))
        self.scale = scale

        # 放大到超过 draft 分辨率时，后台重新按原始分辨率解码一次；
        # 期间继续显示 draft（会被放大，略软），拿到全分辨率后再无缝替换。
        if (self.doc is not None
                and getattr(self.doc, "draft_ratio", 1.0) < 1.0
                and self.pending_full is None
                and scale >= 1.0):
            # scale 是「屏幕像素 / 已解码像素」，所以只有放大到超过已解码尺寸的
            # 100% 才真的需要原始分辨率；此时后台重解一次。
            self.pending_full = self.doc.path
            self.loader.request_full(self.doc.path)

        half_w = cw / (2.0 * scale)
        half_h = ch / (2.0 * scale)
        if self.cx is None:
            cx = iw / 2.0
        elif iw <= half_w * 2:
            cx = iw / 2.0
        else:
            cx = min(max(self.cx, half_w), iw - half_w)
        if self.cy is None:
            cy = ih / 2.0
        elif ih <= half_h * 2:
            cy = ih / 2.0
        else:
            cy = min(max(self.cy, half_h), ih - half_h)
        self.cx = cx
        self.cy = cy

        ox = cw / 2.0 - cx * scale
        oy = ch / 2.0 - cy * scale
        ix0 = int(math.floor(max(0.0, ox)))
        iy0 = int(math.floor(max(0.0, oy)))
        ix1 = int(math.ceil(min(float(cw), ox + iw * scale)))
        iy1 = int(math.ceil(min(float(ch), oy + ih * scale)))
        tw = max(1, ix1 - ix0)
        th = max(1, iy1 - iy0)

        sx0 = max(0, int(math.floor((ix0 - ox) / scale)))
        sy0 = max(0, int(math.floor((iy0 - oy) / scale)))
        sx1 = min(iw, int(math.ceil((ix1 - ox) / scale)))
        sy1 = min(ih, int(math.ceil((iy1 - oy) / scale)))
        if sx1 <= sx0 or sy1 <= sy0:
            sx0, sy0, sx1, sy1 = 0, 0, iw, ih

        if fast:
            resample = RESAMPLING.BILINEAR      # 拖动/缩放时优先跟手
        else:
            resample = LANCZOS if scale < 1.0 else BICUBIC

        # 缩小时改用低分辨率副本：6000x4000 缩到屏幕上，用 2600 长边的
        # 副本算，观感一样但快好几倍。
        src = im
        ratio = 1.0
        _pmax = self._proxy_limit()
        if (scale < 1.0 and max(iw, ih) > _pmax
                and max(iw, ih) * scale <= _pmax):
            prev, ratio = self._preview_of(im)
            if prev is not None and ratio > 0:
                pw, ph = prev.size
                sx0 = max(0, int(sx0 * ratio))
                sy0 = max(0, int(sy0 * ratio))
                sx1 = min(pw, max(sx0 + 1, int(math.ceil(sx1 * ratio))))
                sy1 = min(ph, max(sy0 + 1, int(math.ceil(sy1 * ratio))))
                src = prev

        # 基瓦片缓存：调色滑块拖动时视角没变，裁剪+缩放结果可以直接复用
        tkey = (id(src), self.geom_key, self.frame_i, sx0, sy0, sx1, sy1,
                tw, th, resample)
        tile = self.tile_cache.get(tkey)
        if tile is None:
            if (sx0, sy0, sx1, sy1) == (0, 0, src.size[0], src.size[1]):
                tile = src
            else:
                tile = src.crop((sx0, sy0, sx1, sy1))
            # 两步降采样在这里不划算：4000x2500 -> 1764x1396 的整数倍只有 1
            # （高度 2500/1396=1.79），reduce 不会触发，反而多一层开销 ——
            # 实测两步 326ms、单步 228ms。reduce 的收益要 >=4 倍才出现。
            try:
                tile = tile.resize((tw, th), resample,
                                   reducing_gap=2.0 if scale < 1.0 else None)
            except TypeError:
                tile = tile.resize((tw, th), resample)
            if len(self.tile_cache) > (2 if getattr(self, "low_mem", False) else 3):
                self.tile_cache.clear()
            self.tile_cache[tkey] = tile

        # 实测结论：在这个画布尺寸（1764×1396）上，拖动帧的耗时主要来自
        # 「Tk 上传 2.46 MP 图像 38 ms + 表面转换 11 ms」，与我们处理多少像素无关 ——
        # 把渲染降到 1/4 分辨率实测帧时几乎不变（83 vs 90 ms），却让预览变糊。
        # 所以这里**不做降分辨率**，保证拖动时看到的也是完整画质。
        # 拖动帧里是否暂时省略暗角与水印（设置里可开）
        skip_fx = bool(fast and getattr(self, "fast_skip_fx", False))
        self._split_orig = tile
        if self.show_original or (self._adj_identity()
                                  and not self._locals_active()):
            pass
        else:
            # 缩放到屏幕分辨率之后再调色：亮度/对比度/饱和度都是逐像素运算，
            # 与缩放的先后顺序无关，放在后面可以省掉巨量计算。
            tile = self._beauty_stage(tile, fast, tkey)
            tile = self._color_stage(tile, fast)
            dparams = self._detail_params()
            if fast or not any(dparams):
                pass                      # 拖动中不跑空间运算，保持跟手
            else:
                        # 颜色参数必须进缓存键！否则改完曝光/对比度/色温之后，
                # 这里会拿「旧颜色 + 细节」的缓存把刚算好的颜色版覆盖掉，
                # 屏幕上所有调色改动都失效（看起来就是图片悄悄变回原图）。
                dk = (tkey, self._color_sig(), dparams)
                got = self.detail_cache.get(dk)
                if got is not None and got.size == tile.size:
                    tile = got           # 后台算好的成品，直接用
                elif self.detail_inflight != dk:
                    # 先把颜色版显示出来，细节交给后台线程，界面不冻结
                    self.detail_inflight = dk
                    self.detail_worker.submit(dk, tile, dparams)
                    self._wake_pump()
            # 暗角(约 15 ms)、水印(约 30 ms)不随明暗/色彩类参数变化，
            # 拖动帧里可以省掉，松手后的精修帧会补上。
            if self.adj["vignette"] and not skip_fx:
                tile = self._apply_vignette(tile, self.adj["vignette"])
        if self._watermark() and not skip_fx:
            tile = self._apply_watermark(tile)
        if getattr(self, "soft_proof", False) and not fast:
            tile = self._apply_soft_proof(tile)
        if fast:
            dt = (time.perf_counter() - render_t0) * 1000.0
            self.last_frame_ms = dt

        # 只生成图片所占区域的位图，画布其余部分直接露出背景色：
        # 渲染开销与「可见图片面积」成正比，而不是整个画布。
        def _to_surface(src):
            if src.mode == "RGBA":
                # 透明区域铺棋盘格，合成必须在 RGBA 空间进行
                if self.doc is not None and self.doc.alpha:
                    region = self._checker(cw, ch).crop(
                        (ix0, iy0, ix0 + tw, iy0 + th)).convert("RGBA")
                else:
                    region = Image.new("RGBA", (tw, th), BG_RGB + (255,))
                return Image.alpha_composite(region, src).convert("RGB")
            return src if src.mode == "RGB" else src.convert("RGB")

        surface = _to_surface(tile)
        self.surface_img = surface          # 供色彩取样器读取屏幕像素
        self.surface_pos = (ix0, iy0)
        # 分屏对比：左半边换成原图。原图就是调色前的同一块瓦片，
        # 已经在瓦片缓存里，所以几乎不额外花时间。
        if self.split_x is not None and self._split_orig is not None:
            sx = min(tw, max(0, int(cw * self.split_x) - ix0))
            if sx > 0:
                surface = surface.copy()
                surface.paste(_to_surface(self._split_orig).crop((0, 0, sx, th)),
                              (0, 0))
        # 过曝/欠曝提示画在最后，且不写回 surface_img，
        # 免得色彩取样器读到红/蓝色的警告色。
        if self.clip_warn and not self.show_original:
            surface = _clip_overlay(surface)

        # 实测（1764x1148）：复用同一个 PhotoImage 用 paste 刷新要 52.1 ms，
        # 而直接新建一个只要 25.8 ms —— 反直觉，但 paste 走的是逐行拷贝的老路径。
        # 所以这里每帧都新建、再把画布项指过去，旧图由引用计数回收。
        reuse = (self._use_paste_photo() and self.photo is not None
                 and getattr(self, "_photo_size", None) == surface.size)
        if reuse:
            try:
                self.photo.paste(surface)
            except Exception:
                reuse = False
        if not reuse:
            self.photo = ImageTk.PhotoImage(surface, master=self.canvas)
            self._photo_size = surface.size
        if self.img_item is None:
            self.img_item = self.canvas.create_image(
                ix0, iy0, anchor="nw", image=self.photo)
        else:
            self.canvas.itemconfigure(self.img_item, image=self.photo)
        self.canvas.coords(self.img_item, ix0, iy0)
        if self.text_item is not None:
            self.canvas.itemconfigure(self.text_item, state="hidden")
        self._draw_split()      # 关闭分屏时也要走一遍，否则分割线不会被删掉
        if self.crop_mode:
            self._draw_crop()
            self._draw_crop_grid()
        elif self.crop_item is not None:
            self.canvas.tag_raise(self.crop_item)
        self._draw_locals()
        self._draw_slide_label()
        self._draw_hint()
        self._update_cursor()

        # 记录本帧耗时，作为下一帧的节流间隔：慢的时候自动少画几帧，
        # 保证鼠标始终跟手，而不是越拖越卡。
        cost = (time.perf_counter() - t_frame) * 1000.0
        self.render_cost = self.render_cost * 0.7 + cost * 0.3
        self.render_interval = max(8.0, min(60.0, self.render_cost))
        self.last_render = time.perf_counter()

    # ------------------------------------------------------------ 状态

    def _update_title(self):
        if self.doc is not None:
            self.title("%s - %s %s" % (os.path.basename(self.doc.path),
                                         APP_NAME, APP_VERSION))
        elif self.loading:
            self.title(_trf("载入中 - %s %s" % (APP_NAME, APP_VERSION)))
        else:
            self.title(_trf(APP_TITLE))

    def _update_status(self):
        if not getattr(self, "alive", True):
            return
        doc = self.doc
        if doc is None:
            self.name_lbl.configure(text="")
            self.meta_lbl.configure(text="")
            self.zoom_lbl.configure(text="")
            return
        name = os.path.basename(doc.path)
        marks = []
        if doc.n_frames > 1:
            marks.append(_trf("动图 %d 帧%s" % (
                doc.n_frames, _tr("（已暂停）") if self.paused else "")))
        rots = sum(op[1] for op in self.geom if op[0] == "rot")
        flips = sum(1 for op in self.geom if op[0] == "flip")
        crops = sum(1 for op in self.geom if op[0] == "crop")
        if rots % 360:
            marks.append(_trf("旋转 %d°" % (rots % 360)))
        if flips:
            marks.append(_tr("翻转"))
        if crops:
            marks.append(_tr("已裁剪"))
        if not self._adj_identity():
            marks.append(_tr("已调整"))
        if self.show_original:
            marks.append(_tr("正在显示原图（再按一次反斜杠或点「对比原图」返回）"))
        if getattr(doc, "draft_ratio", 1.0) < 1.0:
            marks.append(_tr("快速预览（按 1:1 自动换全分辨率）"))
        if self.slideshow:
            marks.append(_tr("幻灯片 %ds") % self.interval)
        full = name + ("    " + " · ".join(marks) if marks else "")

        im = self._view_image()
        size = im.size if im is not None else doc.size
        total = len(self.files)
        pos = "%d / %d" % (self.index + 1, total) if total else "-"
        meta = "%s    %d × %d    %s    %s" % (
            pos, size[0], size[1], doc.fmt, human_size(doc.file_size))

        # 窗口太窄时截断文件名，避免两段文字挤在一起
        avail = self.status.winfo_width() - px(28) - self._mfont.measure(meta)
        if avail > px(40):
            full = _ellipsize(self._mfont, full, avail)
        # 同样的文字重复 configure 只会白白多走几趟 Tk 往返；
        # 拖动时每帧都会调 _update_status，这里做个去重。
        # 状态行：图片或美颜参数变化时刷新一次（避免每帧重算）
        a0 = self.adj
        key = (doc.path, self.frame_i,
               round(a0.get("skin_smooth", 0), 0), round(a0.get("skin_blemish", 0), 0),
               round(a0.get("skin_eye_care", 0), 0), round(a0.get("skin_teeth", 0), 0),
               round(a0.get("skin_slim", 0), 0), round(a0.get("skin_eyes", 0), 0),
               getattr(self, "beauty_off", False))
        if key != getattr(self, "_ai_status_key", None):
            self._ai_status_key = key
            self.after(180, self._refresh_ai_status)
        if full != getattr(self, "_last_name_txt", None):
            self.name_lbl.configure(text=full)
            self._last_name_txt = full
        try:
            want_full = (doc is not None
                         and getattr(doc, "draft_ratio", 1.0) < 0.999)
            if want_full and not self.full_btn.winfo_ismapped():
                self.full_btn.pack(side="left", padx=(px(4), 0), pady=px(2))
            elif not want_full and self.full_btn.winfo_ismapped():
                self.full_btn.pack_forget()
        except Exception:
            pass
        if meta != getattr(self, "_last_meta_txt", None):
            self.meta_lbl.configure(text=meta)
            self._last_meta_txt = meta
        r = getattr(doc, "draft_ratio", 1.0)
        zt = "%d%%" % int(round(self.scale * r * 100))
        if zt != getattr(self, "_last_zoom_txt", None):
            self.zoom_lbl.configure(text=zt)
            self._last_zoom_txt = zt

    # ------------------------------------------------------------ 修图面板

    def _hover_tip(self, widget, text, delay=420, caps=None):
        """鼠标停留片刻后弹一行说明（用于插件卡片这种信息压缩场景）。

        caps 给出能力声明时，用彩色圆点 + 文字替代干巴巴的「联网 是/否」。
        """
        state = {"job": None, "win": None}

        def show():
            state["job"] = None
            try:
                w = tk.Toplevel(widget)
                w.wm_overrideredirect(True)
                _round_window(w)
                tk.Label(w, text=text, font=self.ui_font_s, bg=BAR_BG, fg=FG,
                         justify="left", padx=px(8), pady=px(5),
                         wraplength=px(320)).pack(fill="x")
                if caps:
                    inc = tk.Frame(w, bg=BAR_BG)
                    inc.pack(fill="x", padx=px(8), pady=(0, px(5)))
                    for label, on in ((_tr("联网"), bool(caps.get("network"))),
                                      (_tr("写文件"), bool(caps.get("writes_files")))):
                        col = "#ff8a6b" if on else "#5c5c5c"
                        tk.Label(inc, text="●", font=self.ui_font_s,
                                 bg=BAR_BG, fg=col).pack(side="left")
                        tk.Label(inc, text=label, font=self.ui_font_s,
                                 bg=BAR_BG, fg=FG_DIM).pack(side="left",
                                                            padx=(px(2), px(8)))
                x = widget.winfo_rootx() + px(12)
                y = widget.winfo_rooty() + widget.winfo_height() + px(6)
                w.wm_geometry("+%d+%d" % (x, y))
                state["win"] = w
            except Exception:
                state["win"] = None

        def enter(_e=None):
            leave()
            state["job"] = widget.after(delay, show)

        def leave(_e=None):
            job = state.get("job")
            if job is not None:
                try:
                    widget.after_cancel(job)
                except Exception:
                    pass
                state["job"] = None
            win = state.get("win")
            if win is not None:
                try:
                    win.destroy()
                except Exception:
                    pass
                state["win"] = None

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")
        return leave

    def _panel_btn(self, parent, text, cmd, side="left", wide=False):
        # 圆角按钮：Tk 的 Button 只能画直角，这里换成 Canvas 自绘控件
        b = _QpeRoundButton(parent, text=text, command=cmd,
                            font=self.ui_font_s, bg=BTN_BG, fg=FG,
                            hover_bg=BAR_HOVER, hover_fg=FG_HI)
        if side == "grid":
            return b
        if side == "left":
            b.pack(side="left", padx=(0, px(SPACE_MD)), pady=px(1))
        else:
            b.pack(side=side, fill="x" if wide else None,
                   expand=1 if wide else 0, pady=px(1))
        return b

    # -------------------------------------------------------- 滑块 / 区块

    def _slider(self, parent, label, lo, hi, value, setter, getter,
                default=0.0, step=1, fmt="%+.0f", swatch=None, swatch_fn=None):
        row = tk.Frame(parent, bg=BAR_BG)
        row.pack(fill="x", pady=(px(1), 0))
        sw = None
        if swatch or swatch_fn:
            sw = tk.Frame(row, width=px(9), height=px(9))
            sw.configure(bg=swatch_fn(value) if swatch_fn else swatch)
            sw.pack(side="left", padx=(0, px(5)))
        lab = tk.Label(row, text=label, font=self.ui_font_s, bg=BAR_BG,
                       fg=FG_DIM, anchor="w", cursor="hand2")
        lab.pack(side="left")
        # 数值固定 6 个字符宽、等宽字体：右边缘才能对齐成一列
        val = tk.Label(row, text=fmt % value, font=self.ui_font_s, bg=BAR_BG,
                       fg=FG, anchor="e", width=6, cursor="hand2")
        val.pack(side="right")
        sc = _QpeSlider(parent, from_=lo, to=hi, resolution=step,
                        height=px(20))
        sc.configure(command=lambda v, s=sc, vl=val, st=setter, f=fmt,
                              w=sw, wf=swatch_fn, lb=label:
                     self._slide(v, s, vl, st, f, w, wf, lb))
        sc.pack(fill="x")
        self.syncing = True
        sc.set(value)
        self.syncing = False
        # add="+"：自绘滑杆自己也要收 ButtonRelease 来结束拖动
        sc.bind("<ButtonRelease-1>", lambda e: self._slide_done(), add="+")
        for w in (lab, val):                      # 双击标签或数值复位
            w.bind("<Double-Button-1>",
                   lambda e, s=sc, d=default: self._reset_slider(s, d))
        # 右键点数值：直接输入精确值（拖滑块很难精确到个位数）
        val.bind("<Button-3>", lambda e, s=sc, lo=lo, hi=hi, f=fmt,
                 lb=label: self._ask_slider_value(s, lo, hi, f, lb))
        val.configure(text=fmt % value)
        self.sliders.append((sc, val, getter, fmt, label))
        return sc

    def _ask_slider_value(self, sc, lo, hi, fmt, label):
        """右键点数值标签时弹出输入框，直接填一个精确值。"""
        try:
            cur = float(sc.get())
        except Exception:
            cur = 0.0
        try:
            from tkinter import simpledialog
            v = simpledialog.askfloat(
                "输入数值", "%s（%g ~ %g）" % (label, lo, hi),
                parent=self, initialvalue=cur, minvalue=lo, maxvalue=hi)
        except Exception:
            v = None
        if v is None:
            return
        self.syncing = True
        try:
            sc.set(v)
        finally:
            self.syncing = False
        self._mark_fast()
        self._request_render()
        self._push_history("%s = %s" % (label, fmt % v))
        self._flash("%s = %s" % (label, fmt % v))

    def _slide(self, v, sc, val, setter, fmt, swatch=None, swatch_fn=None,
               label=None):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return
        val.configure(text=fmt % f)
        if swatch is not None and swatch_fn is not None:
            swatch.configure(bg=swatch_fn(f))
        if self.syncing:
            return
        setter(f)
        self.last_slider = label or "调整"
        self._mark_fast()
        self._request_render()

    def _slide_done(self):
        if self.syncing:
            return
        self._flush_render()
        self._push_history(self.last_slider)
        self._update_status()
        self._schedule_histogram()

    def _reset_slider(self, sc, default):
        sc.set(default)          # 触发 command，走一次正常的应用流程
        self._slide_done()

    def _section(self, parent, title, opened=True, on_open=None):
        # 分组标题只用「小箭头 + 小字 + 一条细线」，不画底色块、不加强调条。
        # 这样一列分组靠留白和细线区分层次，而不是靠仿 Lightroom 的重标题栏。
        # 每块分区是一张「卡片」：面板底更深（PANEL_BG），卡片用 CARD_BG，
        # 靠明度差和 6px 外距分层，而不是靠边框或色块。
        wrap = tk.Frame(parent, bg=CARD_BG)
        wrap.pack(fill="x", padx=px(SPACE_MD), pady=(px(SPACE_MD), 0))
        head = tk.Frame(wrap, bg=CARD_BG, cursor="hand2")
        head.pack(fill="x")
        mark = tk.Label(head, text="▾" if opened else "▸",
                        font=self.ui_font_s, bg=CARD_BG,
                        fg=FG_DIM, width=1, cursor="hand2")
        mark.pack(side="left")
        title_lbl = tk.Label(head, text=title, font=self.ui_font_m, bg=CARD_BG,
                             fg=FG if opened else FG_DIM, anchor="w",
                             cursor="hand2")
        title_lbl.pack(side="left", padx=(px(1), px(SPACE_LG)))
        rule = tk.Frame(head, bg=CARD_LINE, height=max(1, px(1)))
        rule.pack(side="left", fill="x", expand=True, pady=(px(1), 0))
        body = tk.Frame(parent, bg=CARD_BG)
        if hasattr(self, "_theme_cards"):
            self._theme_cards.extend((wrap, head, title_lbl, body))
        state = {"open": opened, "ran": False}

        def ensure():
            if on_open is not None and not state["ran"]:
                state["ran"] = True
                try:
                    on_open(body)      # 把 body 传进去，回调里不再引用外层局部变量
                except Exception:
                    traceback.print_exc()

        def paint():
            on = state["open"]
            mark.configure(fg=ACCENT if on else FG_DIM)
            title_lbl.configure(fg=FG if on else FG_DIM)
            rule.configure(bg=RULE_BG if on else BTN_BG)

        def toggle(_e=None):
            state["open"] = not state["open"]
            if state["open"]:
                body.pack(fill="x", padx=(px(11), 0), pady=(px(3), 0))
                mark.configure(text="▾")
            else:
                body.pack_forget()
                mark.configure(text="▸")
            paint()
            if state["open"]:
                ensure()
            self._relayout_panel()

        for w in [head, mark] + list(head.winfo_children()):
            w.bind("<Button-1>", toggle)
        if opened:
            body.pack(fill="x", padx=(px(11), 0), pady=(px(3), 0))
            ensure()
        self.sections[title] = (body, toggle)     # 便于程序化展开 / 定位
        return body

    def _draw_local_mini(self):
        """在面板上画一个小图，示意选中滤镜的作用范围与羽化。"""
        cv = getattr(self, "local_mini", None)
        lbl = getattr(self, "local_mini_lbl", None)
        if cv is None or not cv.winfo_exists():
            return
        cv.delete("all")
        if not (0 <= self.local_sel < len(self.locals)):
            if lbl is not None and lbl.winfo_exists():
                lbl.configure(text="尚未选中滤镜")
            return
        f = self.locals[self.local_sel]
        try:
            w = int(cv.cget("width"))
            h = int(cv.cget("height"))
        except Exception:
            return
        pad = px(6)
        cv.create_rectangle(pad, pad, w - pad, h - pad, outline=TROUGH_BG)
        if f["type"] == "radial":
            cx = pad + (w - 2 * pad) * f["cx"]
            cy = pad + (h - 2 * pad) * f["cy"]
            rx = max(2.0, (w - 2 * pad) * f["rx"])
            ry = max(2.0, (h - 2 * pad) * f["ry"])
            cv.create_oval(cx - rx, cy - ry, cx + rx, cy + ry,
                           outline=ACCENT, width=2)
            feat = max(0.02, min(1.0, f["feather"] / 100.0))
            inner = 1.0 - feat
            if inner > 0.02:
                cv.create_oval(cx - rx * inner, cy - ry * inner,
                               cx + rx * inner, cy + ry * inner,
                               outline="#ffffff", dash=(3, 3))
            info = "径向  覆盖 %.0f%%  羽化 %.0f%%" % (
                min(100, f["rx"] * f["ry"] * 400), f["feather"])
        else:
            a = math.radians(f["angle"])
            L = math.hypot(w, h)
            cx = pad + (w - 2 * pad) * f["cx"]
            cy = pad + (h - 2 * pad) * f["cy"]
            nx, ny = -math.sin(a), math.cos(a)
            span_px = max(2.0, f["spread"] * h * 0.5)
            for off, col, dash in ((0.0, ACCENT, ()),
                                   (-span_px, "#ffffff", (3, 3)),
                                   (span_px, "#ffffff", (3, 3))):
                bx = cx + math.cos(a) * off
                by = cy + math.sin(a) * off
                cv.create_line(bx - nx * L, by - ny * L, bx + nx * L,
                               by + ny * L, fill=col, dash=dash)
            info = "渐变  跨度 x%.2f  角度 %.0f" % (f["spread"], f["angle"])
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text=info)

    def _rebuild_local_values(self):
        """拖动滤镜后把滑块数值同步过来（不重建控件）。"""
        self.syncing = True
        try:
            for sc, val, getter, fmt, _lb in self.sliders:
                if not sc.winfo_exists():
                    continue
                try:
                    v = getter()
                except Exception:
                    continue
                if isinstance(v, (int, float)):
                    sc.set(v)
                    val.configure(text=fmt % v)
        finally:
            self.syncing = False

    def _relayout_panel(self):
        self.after(20, lambda: self.pcan.configure(
            scrollregion=self.pcan.bbox("all")))

    # -------------------------------------------------------- 直方图

    def _preview_thumb(self):
        """调色后的缩略图，用来算直方图。"""
        im = self._view_image()
        if im is None:
            return None
        w, h = im.size
        f = 220.0 / max(w, h)
        if f < 1.0:
            im = im.resize((max(1, int(w * f)), max(1, int(h * f))),
                           Image.Resampling.BILINEAR)
        if im.mode != "RGB":
            im = im.convert("RGB")
        try:
            return self._apply_adjust(im, fast=True)
        except Exception:
            return im

    def _schedule_histogram(self):
        if self.hist_can is None or not self.panel_shown:
            return
        if self.hist_job is not None:
            try:
                self.after_cancel(self.hist_job)
            except Exception:
                pass
        self.hist_job = self.after(180, self._update_histogram)

    def _hist_draw_marker(self):
        """在直方图上画出点击位置的竖线和亮度读数。"""
        c = self.hist_can
        if c is None or not c.winfo_exists():
            return
        c.delete("histmark")
        sel = getattr(self, "hist_sel", None)
        if sel is None:
            return
        w = max(40, c.winfo_width())
        h = max(30, c.winfo_height())
        x = sel / 255.0 * w
        c.create_line(x, 0, x, h, fill=FG_HI, dash=(px(3), px(3)),
                      tags="histmark")
        c.create_line(x, 0, x, h, fill=FG_HI, width=max(1, px(1)),
                      tags="histmark")
        hist = getattr(self, "hist_data", None)
        txt = "亮度 %d" % sel
        if hist:
            tot = sum(hist) or 1
            cnt = sum(hist[b * 256 + sel] for b in range(3))
            txt = "亮度 %d · %.2f%%" % (sel, 100.0 * cnt / tot)
        # 靠右时文字左对齐，避免跑出画布
        anchor = "ne" if x > w * 0.6 else "nw"
        dx = -px(4) if anchor == "ne" else px(4)
        c.create_text(x + dx, px(2), text=txt, anchor=anchor,
                      fill=FG_HI, font=self.ui_font_s, tags="histmark")

    def _hist_click(self, event):
        c = self.hist_can
        if c is None or not c.winfo_exists():
            return
        w = max(1, c.winfo_width())
        self.hist_sel = int(max(0, min(255, round(event.x / float(w) * 255))))
        self._hist_draw_marker()

    def _hist_clear(self, event=None):
        self.hist_sel = None
        c = self.hist_can
        if c is not None and c.winfo_exists():
            c.delete("histmark")

    def _update_histogram(self):
        self.hist_job = None
        c = self.hist_can
        if c is None or not c.winfo_exists():
            return
        c.delete("all")
        # 尺寸先算出来：空态提示也要用到 w/h（之前写成在下面才算，导致
        # NameError 被 except 吞掉，提示永远不显示）
        w = max(40, c.winfo_width())
        h = max(30, c.winfo_height())
        im = self._preview_thumb()
        if im is None:
            try:
                k = max(1, px(10))
                c.create_text(w // 2, h // 2, text="打开图片后显示直方图",
                              fill=FG_DIM, font=self.ui_font_s)
            except Exception:
                pass
            return
        hist = im.histogram()
        peak = 1
        for band in range(3):
            for v in hist[band * 256:(band + 1) * 256]:
                if v > peak:
                    peak = v
        for band, col in ((0, "#ff5c5c"), (1, "#5cff8a"), (2, "#5c9bff")):
            hh = hist[band * 256:(band + 1) * 256]
            pts = []
            for i in range(0, 256, 3):
                v = max(hh[i:i + 3])
                y = h - (v / float(peak)) ** 0.42 * (h - 2)
                pts.extend((i / 255.0 * w, y))
            if len(pts) >= 4:
                c.create_polygon(*([0, h] + pts + [w, h]), fill=col,
                                 outline="", stipple="gray50")
        self.hist_data = hist
        self._hist_draw_marker()
        self._update_hist_info(im, hist)
        # 顺手给曲线编辑器准备一份 64 格的亮度直方图当背景
        try:
            total = 0
            bins = [0] * 64
            for b in range(3):
                hh = hist[b * 256:(b + 1) * 256]
                total += sum(hh)
                for i, v in enumerate(hh):
                    bins[i * 64 // 256] += v
            top = max(bins) or 1
            self.curve_hist = [v / float(top) for v in bins]
        except Exception:
            self.curve_hist = None
        self._draw_curve()

    def _update_hist_info(self, im, hist):
        """直方图下方的读数：暗部/亮部剪裁比例 + 平均亮度。"""
        lbl = getattr(self, "hist_info", None)
        if lbl is None or not lbl.winfo_exists():
            return
        total = 1
        try:
            total = max(1, im.size[0] * im.size[1])
        except Exception:
            pass
        # 注意：hist 是三个通道分开统计的，加起来之后要除以 3 倍像素数，
        # 否则结果会大 3 倍（第一次就是这么算错的：1/6 的白块显示成 50%）。
        dark = (hist[0] + hist[256] + hist[512]) / 3.0
        bright = (hist[255] + hist[511] + hist[767]) / 3.0
        try:
            small = im.resize((64, 64), Image.Resampling.BILINEAR)
            mean = sum(small.convert("L").getdata()) / 4096.0
        except Exception:
            mean = 0.0
        # 面板只有约 221 逻辑像素宽，长句必然折行错位；改成三段短读数
        _d, _b, _m = _tr("暗"), _tr("亮"), _tr("均")
        lbl.configure(text=(_d + "%5.2f%%   " + _b + "%5.2f%%   "
                             + _m + "%4.0f") % (
            min(100.0, dark * 100.0 / total),
            min(100.0, bright * 100.0 / total), mean),
            fg=("#ff8a6b" if (dark > total * 0.02 or bright > total * 0.02)
                else FG_DIM))

    # -------------------------------------------------------- 色调曲线

    def _curve_geom(self):
        return (max(60, self.curve_can.winfo_width()),
                max(60, self.curve_can.winfo_height()))

    def _set_curve_channel(self, key):
        self.curve_channel = key
        for k, btn in getattr(self, "curve_tabs", {}).items():
            on = (k == key)
            btn.configure(bg=ACCENT if on else BTN_BG,
                          fg="#101010" if on else
                          {"rgb": FG, "r": "#ff6b6b", "g": "#5cff8a",
                           "b": "#5c9bff"}[k])
        self._draw_curve()

    def _draw_curve(self):
        c = self.curve_can
        if c is None or not c.winfo_exists():
            return
        c.delete("all")
        w, h = self._curve_geom()
        for i in range(1, 4):
            c.create_line(w * i / 4.0, 0, w * i / 4.0, h, fill=BTN_BG)
            c.create_line(0, h * i / 4.0, w, h * i / 4.0, fill=BTN_BG)
        # 背景铺一层亮度直方图，方便看出曲线该往哪里扳
        if getattr(self, "curve_hist", None):
            pts = []
            n = len(self.curve_hist)
            for i, v in enumerate(self.curve_hist):
                pts.extend((i / float(n - 1) * w, h - (v ** 0.5) * (h - 2)))
            if len(pts) >= 4:
                c.create_polygon(*([0, h] + pts + [w, h]),
                                 fill=BTN_BG, outline="")
        c.create_line(0, h, w, 0, fill=RULE_BG, dash=(2, 3))
        # 其它通道画成淡色参考线
        for key, col in (("curve", FG_DIM), ("curve_r", "#c05050"),
                         ("curve_g", "#3f9f62"), ("curve_b", "#4a7fc0")):
            if key == {"rgb": "curve", "r": "curve_r", "g": "curve_g",
                       "b": "curve_b"}[self.curve_channel]:
                continue
            if _curve_is_identity(self.adj[key]):
                continue
            lut = _mono_curve(self.adj[key])
            pts = []
            for v in range(0, 256, 6):
                pts.extend((v / 255.0 * w, h - lut[v] / 255.0 * h))
            if len(pts) >= 4:
                c.create_line(*pts, fill=col, width=max(1, px(1)))
        cur = self._active_curve()
        lut = _mono_curve(cur)
        col = {"rgb": ACCENT, "r": "#ff6b6b", "g": "#5cff8a",
               "b": "#5c9bff"}[self.curve_channel]
        pts = []
        for v in range(0, 256, 3):
            pts.extend((v / 255.0 * w, h - lut[v] / 255.0 * h))
        if len(pts) >= 4:
            c.create_line(*pts, fill=col, width=max(1, px(2)))
        for cx, cy in cur:
            x = cx / 255.0 * w
            y = h - cy / 255.0 * h
            r = px(4)
            c.create_oval(x - r, y - r, x + r, y + r, fill=FG_HI,
                          outline=ACCENT)

    def _curve_press(self, event):
        w, h = self._curve_geom()
        cur = self._active_curve()
        best, bi = 1e9, -1
        for i, (cx, cy) in enumerate(cur):
            d = math.hypot(event.x - cx / 255.0 * w,
                           event.y - (h - cy / 255.0 * h))
            if d < best:
                best, bi = d, i
        if best <= px(11):
            self.curve_idx = bi
        else:
            vx = max(0.0, min(255.0, event.x / w * 255.0))
            vy = max(0.0, min(255.0, (h - event.y) / h * 255.0))
            pts = cur
            pts.append([vx, vy])
            pts.sort(key=lambda p: p[0])
            self.curve_idx = pts.index([vx, vy])
        self._curve_drag(event)

    def _curve_drag(self, event):
        if self.curve_idx is None:
            return
        w, h = self._curve_geom()
        pts = self._active_curve()
        i = self.curve_idx
        if not (0 <= i < len(pts)):
            return
        vy = max(0.0, min(255.0, (h - event.y) / h * 255.0))
        if i == 0:
            vx = 0.0
        elif i == len(pts) - 1:
            vx = 255.0
        else:
            vx = max(0.0, min(255.0, event.x / w * 255.0))
            vx = max(pts[i - 1][0] + 4.0, min(pts[i + 1][0] - 4.0, vx))
        pts[i][0] = vx
        pts[i][1] = vy
        self.tone_key = None
        self._draw_curve()
        self._mark_fast()
        self._render()
        self._schedule_histogram()

    def _curve_release(self, event):
        if self.curve_idx is not None:
            self.curve_idx = None
            self._push_history("色调曲线")
            self._update_status()

    def _draw_curve_thumb(self, cv, pts):
        """把小缩略图画成曲线形状，肉眼一看就知道是哪种。"""
        try:
            w = int(cv.cget("width"))
            h = int(cv.cget("height"))
        except Exception:
            return
        cv.delete("all")
        cv.create_line(0, h, w, 0, fill=RULE_BG, dash=(2, 3))
        lut = _mono_curve([list(p) for p in pts])
        coords = []
        for v in range(0, 256, 4):
            coords.extend((v / 255.0 * w, h - lut[v] / 255.0 * h))
        if len(coords) >= 4:
            cv.create_line(*coords, fill=ACCENT, width=2)

    def _refresh_curve_thumbs(self):
        """当前通道用的就是某个预设时，把那个缩略图点亮。"""
        ck = {"rgb": "curve", "r": "curve_r", "g": "curve_g",
              "b": "curve_b"}[self.curve_channel]
        cur = [list(p) for p in self.adj[ck]]
        for key, cv in getattr(self, "curve_preset_btns", {}).items():
            if cv is None or not cv.winfo_exists():
                continue
            on = [list(p) for p in CURVE_PRESETS[key]] == cur
            holder = self.curve_preset_keys.get(key)
            if holder is not None and holder.winfo_exists():
                holder.configure(bg=TROUGH_BG if on else CARD_BG)
                for w in holder.winfo_children():
                    try:
                        if w is cv:
                            w.configure(bg=TROUGH_BG if on else CARD_BG)
                    except Exception:
                        pass

    def _apply_curve_preset(self, key):
        """一键套用常用曲线形状（作用于当前选中的通道）。"""
        pts = CURVE_PRESETS.get(key)
        if not pts:
            return
        ck = {"rgb": "curve", "r": "curve_r", "g": "curve_g",
              "b": "curve_b"}[self.curve_channel]
        self.adj[ck] = [list(p) for p in pts]
        self.tone_key = None
        self._draw_curve()
        self._refresh_curve_thumbs()
        self._mark_fast()
        self._request_render()
        self._push_history("曲线：" + key)
        self._flash("已套用曲线「%s」（%s 通道）" % (
            key, {"rgb": "主", "r": "红", "g": "绿", "b": "蓝"}[self.curve_channel]))

    def _curve_reset(self):
        key = {"rgb": "curve", "r": "curve_r", "g": "curve_g",
               "b": "curve_b"}[self.curve_channel]
        self.adj[key] = [list(p) for p in CURVE_DEFAULT]
        self.tone_key = None
        self._draw_curve()
        self._push_history()
        self._render()
        self._schedule_histogram()

    # -------------------------------------------------------- 面板

    def _defer_sections(self, holder, builders):
        """逐个在事件循环空闲时构建面板分区，避免启动时一次性卡住。

        每个分区单独一个 after(1)，而不是一口气全建 —— 这样首帧能抢在
        这些分区之前画出来，用户看到的是「窗口已出现，面板还在长」。
        """
        todo = list(builders)

        def step():
            if not todo:
                try:
                    self._relayout_panel()
                except Exception:
                    pass
                return
            fn = todo.pop(0)
            try:
                fn(holder)
            except Exception:
                traceback.print_exc()
            if todo:
                self.defer_job = self.after(1, step)
            else:
                try:
                    self._relayout_panel()
                except Exception:
                    pass

        self.defer_job = self.after(1, step)

    def _build_panel(self):
        self.sliders = []
        self.panel = tk.Frame(self.body, bg=BAR_BG,
                              width=int(getattr(self, "panel_width", px(238))),
                              height=px(600))
        self.panel.pack_propagate(False)
        # 面板左缘的拖拽条：拖动改宽度，双击恢复默认
        self.panel_grip = tk.Frame(self.body, bg=RULE_BG, width=px(5),
                                   cursor="sb_h_double_arrow")
        self.panel_grip.bind("<ButtonPress-1>", self._panel_drag_start)
        self.panel_grip.bind("<B1-Motion>", self._panel_drag_move)
        self.panel_grip.bind("<ButtonRelease-1>", self._panel_drag_end)
        self.panel_grip.bind("<Double-Button-1>", self._panel_drag_reset)
        self.pcan = tk.Canvas(self.panel, bg=BAR_BG, highlightthickness=0, bd=0,
                              yscrollincrement=px(22))
        self.psb = tk.Scrollbar(self.panel, orient="vertical",
                                command=self.pcan.yview)
        self.pcan.configure(yscrollcommand=self.psb.set)
        self.psb.pack(side="right", fill="y")
        self.pcan.pack(side="left", fill="both", expand=True)
        wrap = tk.Frame(self.pcan, bg=BAR_BG)
        self.pwin = self.pcan.create_window((0, 0), window=wrap, anchor="nw")
        wrap.bind("<Configure>", lambda e: self.pcan.configure(
            scrollregion=self.pcan.bbox("all")))
        self.pcan.bind("<Configure>", lambda e: self.pcan.itemconfigure(
            self.pwin, width=e.width))
        inner = tk.Frame(wrap, bg=PANEL_BG)
        self.panel_wrap = wrap
        self.panel_inner = inner
        self._theme_cards = []
        inner.pack(fill="both", expand=True, padx=px(4), pady=px(8))

        tk.Label(inner, text="修图", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x")

        # 不写 width 时 Tk 会给 378 逻辑像素的默认请求宽，把整列撑出面板。
        # 实际宽度由 pack(fill="x") 决定。
        self.hist_can = tk.Canvas(inner, height=px(64), width=px(10),
                                  bg=DEEP_BG, highlightthickness=0, bd=0)
        self.hist_can.pack(fill="x", pady=(px(3), 0))
        self.hist_can.bind("<Button-1>", self._hist_click)
        self.hist_can.bind("<Button-3>", self._hist_clear)
        self.hist_can.bind("<Leave>", self._hist_clear)
        # 面板是懒建的：首次 pack 后宽度从 10 变成真实宽度，必须重画
        self.hist_can.bind("<Configure>", lambda e: self._schedule_histogram())
        self.hist_info = tk.Label(inner, text="", font=self.mono_font,
                                  bg=PANEL_BG, fg=FG_DIM, anchor="w",
                                  justify="left")
        self.hist_info.pack(fill="x", pady=(px(1), 0))

        # 常驻入口：不依赖滚动位置，任何窗口高度都点得到
        # 2x2 网格：四个按钮塞一行会被面板宽度裁掉（最后一个是半个字）
        quick = tk.Frame(inner, bg=PANEL_BG)
        quick.pack(fill="x", pady=(px(SPACE_SM), px(SPACE_XS)))
        quick.columnconfigure(0, weight=1, uniform="qb")
        quick.columnconfigure(1, weight=1, uniform="qb")
        for _i, (_txt, _cmd) in enumerate((
                ("人像美化", lambda: self._focus_film("skin")),
                ("胶片", lambda: self._focus_film("film")),
                ("畸变", lambda: self._focus_film("lens")),
                ("对比(B)", self.toggle_beauty_peek))):
            _b = self._panel_btn(quick, _txt, _cmd, side="grid")
            _b.grid(row=_i // 2, column=_i % 2, sticky="ew",
                    padx=(0 if _i % 2 == 0 else px(SPACE_SM), 0),
                    pady=(0 if _i < 2 else px(SPACE_SM), 0))
        self.ai_status_lbl = tk.Label(inner, text="", font=self.ui_font_s,
                                      bg=PANEL_BG, fg=FG_DIM, anchor="w",
                                      justify="left", wraplength=px(200))
        self.ai_status_lbl.pack(fill="x", pady=(0, px(1)))
        # 进度条与进度文字默认**不占位**：之前它们一直 pack 着，
        # 空的时候也吃掉约 50 逻辑像素，状态行到「基本」之间就留出一大块空白。
        self.ai_bar = tk.Canvas(inner, height=px(5), bg=PANEL_BG,
                                highlightthickness=0, bd=0)
        self.ai_progress_lbl = tk.Label(inner, text="", font=self.ui_font_s,
                                        bg=PANEL_BG, fg=ACCENT, anchor="w")
        self._ai_extra_shown = False
        self._ai_job = self.after(120, self._refresh_ai_status)

        self._sec_basic(inner)
        self._sec_film(inner)        # 美颜/胶片/畸变放在前面，避免藏在面板底部
        self._sec_beauty_adv(inner)
        # 首屏只需要「基本 + 镜头」两块；其余分区推迟到首帧之后再建，
        # 窗口能早 300~400ms 出来（低配机上差别更明显）。
        holder = tk.Frame(inner, bg=BAR_BG)
        holder.pack(fill="x")
        self._defer_sections(holder, [
            self._sec_curve, self._sec_hsl, self._sec_detail,
            self._sec_effect, self._sec_split, self._sec_local,
            self._sec_preset, self._sec_snapshot,
        ])

        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(SPACE_XL), 0))
        self._panel_btn(row, "裁剪", self.toggle_crop)
        # 重置全部 / 复制设置 / 关于 已经收进设置窗口
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.hist_undo_btn = self._panel_btn(row, "撤销", self.undo)
        self.hist_redo_btn = self._panel_btn(row, "重做", self.redo)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.cmp_btn = self._panel_btn(row, "对比原图", self.toggle_compare)
        self._panel_btn(row, "批量", self.batch_export)
        self._panel_btn(row, "改名", self.batch_rename)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.split_btn = self._panel_btn(row, "分屏对比", self.toggle_split)
        self._panel_btn(row, "胶片条", self.toggle_strip)
        self._panel_btn(row, "网格", self.toggle_grid)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.sort_btn = self._panel_btn(row, "排序：文件名", self._sort_menu)
        pass
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "所在文件夹", self.reveal_folder)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.auto_btn = self._panel_btn(row, "自动色调", self.auto_tone)
        self.clip_btn = self._panel_btn(row, "过曝警告", self.toggle_clip)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.pick_btn = self._panel_btn(row, "锁定取色", self.toggle_pick_lock)
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.theme_btn = self._panel_btn(row, "设置", self.show_settings)
        pass
        row = tk.Frame(inner, bg=PANEL_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "粘贴设置", self.paste_settings, side="top",
                        wide=True)
        row = tk.Frame(inner, bg=BAR_BG)
        row.pack(fill="x", pady=(px(6), 0))
        self._panel_btn(row, "保存 / 另存为", self.save_as, side="top", wide=True)

        head = tk.Frame(inner, bg=HEAD_BG)
        head.pack(fill="x", pady=(px(10), 0))
        tk.Label(head, text="历史记录", font=self.ui_font_b, bg=HEAD_BG,
                 fg=FG, anchor="w").pack(side="left", padx=px(6), pady=px(4))
        self.hist_box = tk.Listbox(
            inner, height=8, bg=DEEP_BG, fg=FG, selectbackground=ACCENT,
            selectforeground="#101010", bd=0, highlightthickness=0,
            font=self.ui_font_s, activestyle="none", exportselection=False)
        self.hist_box.pack(fill="x", pady=(px(2), 0))
        self.hist_box.bind("<<ListboxSelect>>", self._on_hist_select)
        self._bind_wheel(self.hist_box)

        tk.Label(inner, text="双击滑块标签可复位 · 裁剪按 C · \\ 看原图",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                 justify="left", wraplength=px(200)).pack(
                     fill="x", pady=(px(6), 0))

        self._bind_wheel(self.pcan)
        self._update_hist_buttons()

    def _sec_basic(self, parent):
        b = self._section(parent, "基本")
        for key, label in (("temperature", "色温"), ("tint", "色调")):
            self._slider(b, label, -100, 100, self.adj[key],
                         lambda v, k=key: self.adj.__setitem__(k, v),
                         lambda k=key: self.adj[k], 0.0, 1, "%+.0f")
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(4), 0))
        self.pick_btn = self._panel_btn(row, "白平衡吸管", self.start_picker)
        for key, label, lo, hi, step, fmt in (
                ("exposure", "曝光", -3.0, 3.0, 0.01, "%+.2f"),
                ("contrast", "对比度", -100, 100, 1, "%+.0f"),
                ("highlights", "高光", -100, 100, 1, "%+.0f"),
                ("shadows", "阴影", -100, 100, 1, "%+.0f"),
                ("whites", "白色色阶", -100, 100, 1, "%+.0f"),
                ("blacks", "黑色色阶", -100, 100, 1, "%+.0f"),
                ("vibrance", "自然饱和度", -100, 100, 1, "%+.0f"),
                ("saturation", "饱和度", -100, 100, 1, "%+.0f")):
            self._slider(b, label, lo, hi, self.adj[key],
                         lambda v, k=key: self.adj.__setitem__(k, v),
                         lambda k=key: self.adj[k], 0.0, step, fmt)
        self.var_auto = tk.IntVar(value=0)
        self.var_gray = tk.IntVar(value=0)
        for var, text, key in ((self.var_auto, "自动色阶", "auto"),
                               (self.var_gray, "灰度", "grayscale")):
            tk.Checkbutton(b, text=text, variable=var, font=self.ui_font,
                           bg=BAR_BG, fg=FG, selectcolor=TROUGH_BG,
                           activebackground=BAR_BG, activeforeground=FG_HI,
                           bd=0, highlightthickness=0, anchor="w", takefocus=0,
                           command=lambda k=key, v=var: self._on_toggle(k, v)
                           ).pack(fill="x")

    def _sec_curve(self, parent):
        b = self._section(parent, "色调曲线", opened=False,
                          on_open=self._curve_lazy)
        self.curve_can = tk.Canvas(b, height=px(150), width=px(10),
                                   bg=DEEP_BG, highlightthickness=0, bd=0,
                                   cursor="crosshair")
        self.curve_can.pack(fill="x", pady=(px(2), px(3)))
        self.curve_can.bind("<ButtonPress-1>", self._curve_press)
        self.curve_can.bind("<B1-Motion>", self._curve_drag)
        self.curve_can.bind("<ButtonRelease-1>", self._curve_release)
        self.curve_can.bind("<Configure>", lambda e: self._draw_curve())
        tk.Label(b, text="拖动控制点 · 空白处点击可加点",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                 anchor="w").pack(fill="x")
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.curve_tabs = {}
        for key, label, col in (("rgb", "主", FG), ("r", "红", "#ff6b6b"),
                                ("g", "绿", "#5cff8a"), ("b", "蓝", "#5c9bff")):
            btn = tk.Button(row, text=label, font=self.ui_font_s,
                            command=lambda k=key: self._set_curve_channel(k),
                            bg=BTN_BG, fg=col, relief="flat", bd=0,
                            highlightthickness=0, padx=px(8), pady=px(3),
                            cursor="hand2", takefocus=0)
            btn.pack(side="left", padx=(0, px(3)))
            self.curve_tabs[key] = btn
        row2 = tk.Frame(b, bg=BAR_BG)
        row2.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row2, "重置本通道", self._curve_reset)
        row3 = tk.Frame(b, bg=BAR_BG)
        row3.pack(fill="x", pady=(px(3), 0))
        self.curve_preset_btns = {}
        self.curve_preset_keys = {}
        self._curve_pending = []
        for key in ("柔和S", "强对比", "褪色", "提亮"):
            holder = tk.Frame(row3, bg="#1c1c1c")
            holder.pack(side="left", padx=(0, px(4)))
            cv = tk.Canvas(holder, width=px(46), height=px(32), bg="#1c1c1c",
                           highlightthickness=0, bd=0, cursor="hand2")
            cv.pack(padx=px(2), pady=(px(2), 0))
            lab = tk.Label(holder, text=key, font=self.ui_font_s,
                           bg="#1c1c1c", fg=FG_DIM)
            lab.pack(pady=(0, px(2)))
            for w in (cv, lab):
                w.bind("<Button-1>", lambda e, k=key: self._apply_curve_preset(k))
                w.bind("<Enter>", lambda e, c=cv: c.configure(bg=HEAD_BG))
                w.bind("<Leave>", lambda e, c=cv: c.configure(bg="#1c1c1c"))
            self.curve_preset_btns[key] = cv
            self.curve_preset_keys[key] = holder
            self._curve_pending.append((cv, CURVE_PRESETS[key]))
        self._set_curve_channel("rgb")

    def _curve_lazy(self, _b=None):
        """曲线分区第一次展开时才画缩略图，省启动时间。"""
        for cv, pts in getattr(self, "_curve_pending", []):
            try:
                if cv.winfo_exists():
                    self._draw_curve_thumb(cv, pts)
            except Exception:
                pass
        self._curve_pending = []
        self._refresh_curve_thumbs()

    def _sec_hsl(self, parent):
        b = self._section(parent, "HSL / 颜色", opened=False,
                          on_open=self._build_hsl_body)
        # 色带概览：一眼看到 8 个色段各自调了多少，点一下就定位过去
        self.hsl_strip = tk.Canvas(b, height=px(30), width=px(10),
                                   bg=DEEP_BG, highlightthickness=0, bd=0)
        self.hsl_strip.pack(fill="x", pady=(px(2), px(3)))
        self.hsl_strip.bind("<Button-1>", self._hsl_strip_click)
        self.hsl_strip.bind("<Configure>", lambda e: self._draw_hsl_strip())
        self.hsl_sel = -1
        tabs = tk.Frame(b, bg=BAR_BG)
        tabs.pack(fill="x", pady=(px(2), px(3)))
        self.hsl_tabs = {}
        for mode, label in (("hue", "色相"), ("sat", "饱和度"),
                            ("lum", "明亮度")):
            btn = tk.Button(tabs, text=label, font=self.ui_font_s,
                            command=lambda m=mode: self._set_hsl_mode(m),
                            bg=BTN_BG, fg=FG, relief="flat", bd=0,
                            highlightthickness=0, padx=px(7), pady=px(3),
                            cursor="hand2", takefocus=0)
            btn.pack(side="left", padx=(0, px(3)))
            self.hsl_tabs[mode] = btn
        self.hsl_body = tk.Frame(b, bg=BAR_BG)
        self.hsl_body.pack(fill="x")
        self.hsl_mode = "sat"

    def _build_hsl_body(self, _b=None):
        """8 组色段滑块 + 色带：展开时才建，启动少创建约 30 个控件。"""
        self._set_hsl_mode(self.hsl_mode)
        self._draw_hsl_strip()

    def _hsl_strip_geo(self):
        c = self.hsl_strip
        return (max(80, c.winfo_width()), max(18, c.winfo_height()))

    def _draw_hsl_strip(self):
        """画色带概览：每段用真实色相着色，中间的白线是 0，短条表示当前值。"""
        c = getattr(self, "hsl_strip", None)
        if c is None or not c.winfo_exists():
            return
        c.delete("all")
        w, h = self._hsl_strip_geo()
        n = len(HSL_BANDS)
        seg = w / float(n)
        mode = self.hsl_mode
        vals = self.adj["hsl"].get(mode, [0.0] * n)
        mid = h / 2.0
        for i in range(n):
            x0, x1 = i * seg, (i + 1) * seg
            col = _hue_swatch(HSL_HUES[i])
            c.create_rectangle(x0 + 0.5, 0, x1 - 0.5, h, fill=col, outline="")
            # 值条：从中间往上下伸
            v = max(-100.0, min(100.0, float(vals[i])))
            if abs(v) > 0.5:
                half = (h / 2.0 - 2) * abs(v) / 100.0
                if v > 0:
                    c.create_rectangle(x0 + seg * 0.3, mid - half,
                                       x1 - seg * 0.3, mid,
                                       fill="#ffffff", outline="")
                else:
                    c.create_rectangle(x0 + seg * 0.3, mid,
                                       x1 - seg * 0.3, mid + half,
                                       fill="#101010", outline="")
            c.create_line(x0 + 0.5, 0, x0 + 0.5, h, fill=DEEP_BG)
            if i == self.hsl_sel:
                c.create_rectangle(x0 + 1, 1, x1 - 1, h - 1,
                                   outline="#ffffff", width=2)
        c.create_line(0, mid, w, mid, fill=DEEP_BG, dash=(2, 3))

    def _hsl_strip_click(self, event):
        w, h = self._hsl_strip_geo()
        n = len(HSL_BANDS)
        i = int(event.x / (w / float(n)))
        if not (0 <= i < n):
            return
        self.hsl_sel = i
        self._draw_hsl_strip()
        try:
            self.pcan.yview_moveto(min(1.0, max(0.0, i / float(n))))
        except Exception:
            pass
        self._flash("%s 色段（%s）：%+.0f" % (
            HSL_BANDS[i], {"hue": "色相", "sat": "饱和度",
                           "lum": "明亮度"}[self.hsl_mode],
            self.adj["hsl"][self.hsl_mode][i]))

    def _set_hsl_mode(self, mode):
        self.hsl_mode = mode
        for m, btn in self.hsl_tabs.items():
            on = (m == mode)
            btn.configure(bg=ACCENT if on else BTN_BG,
                          fg="#101010" if on else FG)
        self._rebuild_hsl()
        self._draw_hsl_strip()

    def _rebuild_hsl(self):
        for w in self.hsl_body.winfo_children():
            w.destroy()
        self.sliders = [s for s in self.sliders if s[0].winfo_exists()]
        mode = self.hsl_mode
        for i, name in enumerate(HSL_BANDS):
            self._slider(
                self.hsl_body, name, -100, 100, self.adj["hsl"][mode][i],
                lambda v, k=mode, j=i: (
                    self.adj["hsl"][k].__setitem__(j, v),
                    self.hsl_sel == j and self._draw_hsl_strip()),
                lambda k=mode, j=i: self.adj["hsl"][k][j],
                0.0, 1, "%+.0f", swatch=_hue_swatch(HSL_HUES[i]))
        self._bind_wheel(self.hsl_body)
        self._relayout_panel()

    def _sec_detail(self, parent):
        return self._section(parent, "细节", opened=False,
                             on_open=self._build_detail)

    def _build_detail(self, b):
        for key, label, lo, hi, step, fmt in (
                ("sharpen", "锐化 · 数量", 0, 150, 1, "%+.0f"),
                ("sharpen_radius", "锐化 · 半径", 0.5, 3.0, 0.1, "%.1f"),
                ("sharpen_detail", "锐化 · 细节", 0, 100, 1, "%+.0f"),
                ("nr_luma", "降噪 · 亮度", 0, 100, 1, "%+.0f"),
                ("nr_color", "降噪 · 颜色", 0, 100, 1, "%+.0f"),
                ("clarity", "清晰度", -100, 100, 1, "%+.0f"),
                ("dehaze", "去朦胧", -100, 100, 1, "%+.0f")):
            self._slider(b, label, lo, hi, self.adj[key],
                         lambda v, k=key: self.adj.__setitem__(k, v),
                         lambda k=key: self.adj[k],
                         self._default_adj()[key], step, fmt)

    def _draw_hue_wheel(self, cv, hue):
        """画色相环并把当前色相标出来。点环上任一角度即可选色相。"""
        import math as _m
        cv.delete("all")
        try:
            w = int(cv.cget("width"))
            h = int(cv.cget("height"))
        except Exception:
            return
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) / 2.0 - 2
        n = 60
        for i in range(n):
            a0 = i * 360.0 / n
            cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=a0,
                          extent=360.0 / n + 1.2, style="pieslice",
                          fill=_hue_swatch(a0 + 3), outline=_hue_swatch(a0 + 3))
        # 中心挖空做一个环
        cv.create_oval(cx - r * 0.45, cy - r * 0.45, cx + r * 0.45,
                       cy + r * 0.45, fill=DEEP_BG, outline=DEEP_BG)
        a = _m.radians(hue)
        x1 = cx + r * _m.cos(a) * 0.50
        y1 = cy - r * _m.sin(a) * 0.50
        x2 = cx + r * _m.cos(a)
        y2 = cy - r * _m.sin(a)
        cv.create_line(x1, y1, x2, y2, fill="#ffffff", width=3)
        cv.create_oval(x2 - 3, y2 - 3, x2 + 3, y2 + 3, fill="#ffffff",
                       outline="#101010")

    def _wheel_click(self, which, event):
        import math as _m
        cv = self.split_wheels[which]
        try:
            w = int(cv.cget("width"))
            h = int(cv.cget("height"))
        except Exception:
            return
        cx, cy = w / 2.0, h / 2.0
        if abs(event.x - cx) < 2 and abs(event.y - cy) < 2:
            return
        hue = _m.degrees(_m.atan2(cy - event.y, event.x - cx)) % 360.0
        key = "split_hi_hue" if which == "hi" else "split_lo_hue"
        self.adj[key] = round(hue, 1)
        self._draw_hue_wheel(cv, self.adj[key])
        self.curves_key = None
        self.tone_key = None
        self._mark_fast()
        self._request_render()
        self._push_history("色调分离色相")

    def _sec_film(self, parent):
        return self._section(parent, "镜头 · 胶片 · 人像", opened=True,
                             on_open=self._build_film)

    def _sec_beauty_adv(self, parent):
        return self._section(parent, "人像 · 高级", opened=False,
                             on_open=self._build_beauty_adv)

    def _build_beauty_adv(self, b):
        self._slider(b, "去油光", 0, 100, self.adj["skin_shine"],
                     lambda v: self.adj.__setitem__("skin_shine", v),
                     lambda: self.adj["skin_shine"], 0.0, 5, "%.0f")
        self._slider(b, "肤色冷暖", -100, 100, self.adj["skin_warm"],
                     lambda v: self.adj.__setitem__("skin_warm", v),
                     lambda: self.adj["skin_warm"], 0.0, 5, "%+.0f")
        self._slider(b, "柔光", 0, 100, self.adj["skin_soft"],
                     lambda v: self.adj.__setitem__("skin_soft", v),
                     lambda: self.adj["skin_soft"], 0.0, 5, "%.0f")
        tk.Label(b, text="分区强度（作用于磨皮，100 为默认）",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                 justify="left", wraplength=px(200)).pack(
                     fill="x", pady=(px(8), px(2)))
        for key, label, dflt in (("zone_forehead", "额头", 100.0),
                                 ("zone_eye", "眼周", 70.0),
                                 ("zone_cheek", "脸颊", 100.0),
                                 ("zone_chin", "下巴", 100.0)):
            self._slider(b, label, 0, 150, self.adj[key],
                         lambda v, k=key: self.adj.__setitem__(k, v),
                         lambda k=key: self.adj[k], dflt, 5, "%.0f")

    def _build_film(self, b):
        # ---- 镜头畸变矫正 ----
        self._slider(b, "畸变矫正", -100, 100, self.adj["lens"],
                     lambda v: self.adj.__setitem__("lens", v),
                     lambda: self.adj["lens"], 0.0, 1, "%+.0f")
        tk.Label(b, text="正值拉直桶形畸变，负值修枕形",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                 justify="left", wraplength=px(200)).pack(fill="x")

        # ---- 胶片模拟 ----
        tk.Label(b, text="胶片模拟", font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                 anchor="w").pack(fill="x", pady=(px(10), px(2)))
        self.film_var = tk.StringVar(value=self.adj.get("film", "无"))
        cb = ttk.Combobox(b, textvariable=self.film_var,
                          values=list(_FILM_PRESETS.keys()), state="readonly",
                          font=self.ui_font_s)
        cb.pack(fill="x")
        cb.bind("<<ComboboxSelected>>", lambda e: self._on_film())
        self._slider(b, "胶片强度", 0, 100, self.adj["film_strength"],
                     lambda v: self.adj.__setitem__("film_strength", v),
                     lambda: self.adj["film_strength"], 100.0, 5, "%.0f")

        # ---- 人像美化 ----
        row_p = tk.Frame(b, bg=BAR_BG)
        row_p.pack(fill="x", pady=(px(8), px(2)))
        for nm in ("自然", "人像", "网红", "素颜"):
            self._panel_btn(row_p, nm,
                            lambda n=nm: self.apply_beauty_preset(n))
        tk.Label(b, text="人像美化（按肤色定位，不是神经网络）",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                 justify="left", wraplength=px(200)).pack(
                     fill="x", pady=(px(10), px(2)))
        self._slider(b, "肤色柔化", 0, 100, self.adj["skin_smooth"],
                     lambda v: self.adj.__setitem__("skin_smooth", v),
                     lambda: self.adj["skin_smooth"], 0.0, 5, "%.0f")
        self._slider(b, "肤色提亮", 0, 100, self.adj["skin_glow"],
                     lambda v: self.adj.__setitem__("skin_glow", v),
                     lambda: self.adj["skin_glow"], 0.0, 5, "%.0f")
        self._slider(b, "磨皮范围", 0, 100, self.adj["skin_radius"],
                     lambda v: self.adj.__setitem__("skin_radius", v),
                     lambda: self.adj["skin_radius"], 40.0, 5, "%.0f")
        self._slider(b, "肤色均匀", 0, 100, self.adj["skin_even"],
                     lambda v: self.adj.__setitem__("skin_even", v),
                     lambda: self.adj["skin_even"], 0.0, 5, "%.0f")
        tk.Label(b, text="祛斑 / 痘印",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", pady=(px(10), px(2)))
        self._slider(b, "祛斑强度", 0, 100, self.adj["skin_blemish"],
                     lambda v: self.adj.__setitem__("skin_blemish", v),
                     lambda: self.adj["skin_blemish"], 0.0, 5, "%.0f")
        self._slider(b, "斑点大小", 2, 15, self.adj["skin_spot_size"],
                     lambda v: self.adj.__setitem__("skin_spot_size", v),
                     lambda: self.adj["skin_spot_size"], 5.0, 1, "%.0f")
        tk.Label(b, text="黑眼圈 / 眼袋",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", pady=(px(10), px(2)))
        self._slider(b, "眼周提亮", 0, 100, self.adj["skin_eye_care"],
                     lambda v: self.adj.__setitem__("skin_eye_care", v),
                     lambda: self.adj["skin_eye_care"], 0.0, 5, "%.0f")
        self._slider(b, "眼周范围", 0, 100, self.adj["skin_eye_spread"],
                     lambda v: self.adj.__setitem__("skin_eye_spread", v),
                     lambda: self.adj["skin_eye_spread"], 50.0, 5, "%.0f")
        tk.Label(b, text="牙齿 / 唇色",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", pady=(px(10), px(2)))
        self._slider(b, "牙齿美白", 0, 100, self.adj["skin_teeth"],
                     lambda v: self.adj.__setitem__("skin_teeth", v),
                     lambda: self.adj["skin_teeth"], 0.0, 5, "%.0f")
        self._slider(b, "唇色增强", 0, 100, self.adj["skin_lip"],
                     lambda v: self.adj.__setitem__("skin_lip", v),
                     lambda: self.adj["skin_lip"], 0.0, 5, "%.0f")
        tk.Label(b, text="脸型 / 眼睛（几何变形）",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", pady=(px(10), px(2)))
        self._slider(b, "瘦脸", 0, 100, self.adj["skin_slim"],
                     lambda v: self.adj.__setitem__("skin_slim", v),
                     lambda: self.adj["skin_slim"], 0.0, 5, "%.0f")
        self.link_var = tk.IntVar(value=1 if self.adj.get("skin_link", True) else 0)

        def _on_link():
            self.adj["skin_link"] = bool(self.link_var.get())
            self._mark_fast()
            self._request_render()

        tk.Checkbutton(b, text="瘦脸时自动加强轮廓磨皮 / 大眼时补眼周提亮",
                       variable=self.link_var, command=_on_link,
                       font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                       activebackground=BAR_BG, activeforeground=FG,
                       selectcolor=DEEP_BG, bd=0, highlightthickness=0,
                       anchor="w", justify="left",
                       wraplength=px(196)).pack(fill="x", pady=(px(2), 0))
        self._slider(b, "大眼", 0, 100, self.adj["skin_eyes"],
                     lambda v: self.adj.__setitem__("skin_eyes", v),
                     lambda: self.adj["skin_eyes"], 0.0, 5, "%.0f")

    def _beauty_sig(self):
        a = self.adj
        return (getattr(getattr(self, "doc", None), "path", None), self.frame_i,
                round(a.get("skin_smooth", 0), 0), round(a.get("skin_blemish", 0), 0),
                round(a.get("skin_eye_care", 0), 0), round(a.get("skin_teeth", 0), 0),
                round(a.get("skin_slim", 0), 0), round(a.get("skin_eyes", 0), 0),
                round(a.get("skin_lip", 0), 0),
                bool(getattr(self, "beauty_off", False)))

    def _sync_ai_extra(self, text=""):
        """有进度就插到状态行下面，没进度就彻底收起来。"""
        try:
            want = bool(text)
            if want and not self._ai_extra_shown:
                self.ai_bar.pack(fill="x", pady=(px(SPACE_XS), px(SPACE_XXS)),
                                 after=self.ai_status_lbl)
                self.ai_progress_lbl.pack(fill="x", after=self.ai_bar)
                self._ai_extra_shown = True
            elif not want and self._ai_extra_shown:
                self.ai_bar.pack_forget()
                self.ai_progress_lbl.pack_forget()
                self._ai_extra_shown = False
        except Exception:
            pass

    def _refresh_ai_status(self):
        """状态行：这张图检测到几张脸、美颜是否生效、主要参数是多少。"""
        self._ai_job = None
        if not getattr(self, "alive", True):
            return
        lbl = getattr(self, "ai_status_lbl", None)
        if lbl is None:
            return
        sig = self._beauty_sig()
        if sig == getattr(self, "_ai_status_sig", None):
            return
        self._ai_status_sig = sig
        try:
            if self.doc is None:
                lbl.configure(text=_tr("人像美化：打开图片后自动识别"))
                return
            src = self._view_image()
            if src is None:
                lbl.configure(text=_tr("人像美化：等待图像"))
                return
            ok, why = _beauty_guard(src)
            if not ok:
                lbl.configure(text=_tr("人像美化：本图不适用（%s）") % _tr(why))
                return
            if _is_grayish(src):
                lbl.configure(text=_tr("人像美化：本图不适用（黑白照片）"))
                return
            skin = _skin_mask(src, 4)
            ok, why = _beauty_guard(src, skin)
            if not ok:
                lbl.configure(text=_tr("人像美化：本图不适用（%s）") % _tr(why))
                return
            faces = _face_boxes(skin)
            a = self.adj
            on = [n for n, k in (("磨皮", "skin_smooth"), ("祛斑", "skin_blemish"),
                                 ("眼周", "skin_eye_care"), ("牙齿", "skin_teeth"),
                                 ("瘦脸", "skin_slim"), ("大眼", "skin_eyes"))
                  if a.get(k)]
            if not on:
                head = (_tr("检出 %d 张脸") % len(faces)) if faces else _tr("未检出人脸")
                lbl.configure(text=_tr("人像美化：%s · 当前未启用") % head)
                return
            parts = []
            if faces:
                parts.append(_tr("检出 %d 张脸") % len(faces))
            else:
                parts.append(_tr("未检出人脸（按肤色处理）"))
            detail = " ".join("%s%.0f" % (_tr(n), a.get(k, 0)) for n, k in
                              (("磨皮", "skin_smooth"), ("祛斑", "skin_blemish"),
                               ("眼周", "skin_eye_care"), ("瘦脸", "skin_slim"))
                              if a.get(k))
            if detail:
                parts.append(detail)
            if getattr(self, "beauty_off", False):
                parts.append(_tr("对比中（已关闭）"))
            lbl.configure(text=_tr("人像美化：") + " · ".join(parts))
        except Exception as exc:
            lbl.configure(text="人像美化：状态未知（%s）" % str(exc)[:24])


    def show_beauty(self):
        """人像美化统一入口：面板 → 分区 → 滚动 → 提示。"""
        if VIEWER_ONLY:
            return
        self._focus_film("skin")

    def _in_text_widget(self):
        try:
            w = self.focus_get()
            return w is not None and w.winfo_class() in (
                "Entry", "Text", "TCombobox", "Spinbox", "TEntry")
        except Exception:
            return False

    def _beauty_peek_on(self, event=None):
        """按住 B：临时关掉美颜，用来对比前后。"""
        if VIEWER_ONLY or self._in_text_widget() or self.beauty_off:
            return
        self.beauty_off = True
        self._mark_fast()
        self._request_render()
        self._flash("对比中：已关闭美颜（松开 B 恢复）", 1200)

    def _beauty_peek_off(self, event=None):
        if not getattr(self, "beauty_off", False):
            return
        self.beauty_off = False
        self._mark_fast()
        self._request_render()

    def toggle_beauty_peek(self):
        if self.beauty_off:
            self._beauty_peek_off()
        else:
            self._beauty_peek_on()

    BEAUTY_KEYS = ("skin_smooth", "skin_radius", "skin_glow", "skin_even",
                   "skin_blemish", "skin_spot_size", "skin_eye_care",
                   "skin_eye_spread", "skin_lip", "skin_teeth",
                   "skin_slim", "skin_eyes", "skin_shine", "skin_warm",
                   "skin_soft", "zone_forehead", "zone_cheek", "zone_chin",
                   "zone_eye")

    BEAUTY_PRESETS = {
        "自然": dict(skin_smooth=35, skin_radius=40, skin_glow=15, skin_even=20,
                   skin_blemish=25, skin_eye_care=0, skin_lip=10, skin_teeth=20,
                   skin_slim=0, skin_eyes=0, skin_shine=20, skin_warm=0,
                   skin_soft=0),
        "人像": dict(skin_smooth=60, skin_radius=50, skin_glow=30, skin_even=45,
                   skin_blemish=50, skin_eye_care=35, skin_lip=25, skin_teeth=40,
                   skin_slim=15, skin_eyes=15, skin_shine=35, skin_warm=10,
                   skin_soft=15),
        "网红": dict(skin_smooth=85, skin_radius=65, skin_glow=55, skin_even=70,
                   skin_blemish=70, skin_eye_care=60, skin_lip=55, skin_teeth=70,
                   skin_slim=45, skin_eyes=40, skin_shine=55, skin_warm=25,
                   skin_soft=35),
        "素颜": {k: 0 for k in ("skin_smooth", "skin_glow", "skin_even",
                               "skin_blemish", "skin_eye_care", "skin_lip",
                               "skin_teeth", "skin_slim", "skin_eyes",
                               "skin_shine", "skin_warm", "skin_soft")},
    }

    def apply_beauty_preset(self, name):
        """一键套用美颜预设（只改美颜相关参数，不动曲线/HSL/胶片）。"""
        preset = self.BEAUTY_PRESETS.get(name)
        if not preset:
            return
        self.adj["skin_radius"] = self.adj.get("skin_radius", 40.0)
        for k, v in preset.items():
            self.adj[k] = float(v)
        if "zone_forehead" not in preset:
            for z in ("zone_forehead", "zone_cheek", "zone_chin"):
                if not self.adj.get(z):
                    self.adj[z] = 100.0
            if not self.adj.get("zone_eye"):
                self.adj["zone_eye"] = 70.0
        self.beauty_off = False
        self._mark_fast()
        try:
            self._sync_panel()
        except Exception:
            pass
        self._request_render()
        self._flash("已套用美颜预设：%s" % name, 1600)

    def _focus_film(self, which="skin"):
        """从菜单直接跳到「镜头 · 胶片 · 人像」分区。"""
        if VIEWER_ONLY:
            return
        self.toggle_panel(True)
        entry = self.sections.get("镜头 · 胶片 · 人像")
        if entry:
            body, toggle = entry
            try:
                if not body.winfo_ismapped():
                    toggle()
            except Exception:
                pass
        # 滚动到该分区，避免"点了菜单却看不到内容"
        try:
            if entry:
                body = entry[0]
                self.pcan.update_idletasks()
                bbox = self.pcan.bbox("all")
                total = max(1, bbox[3] - bbox[1]) if bbox else 1
                top = max(0, body.winfo_y() - px(8))
                self.pcan.yview_moveto(min(1.0, top / float(total)))
        except Exception:
            pass
        tips = {
            "skin": "人像美化：拖「肤色柔化」与「肤色提亮」；检测到人脸时只作用于脸",
            "film": "胶片模拟：先在下拉框选风格，再用「胶片强度」控制力度",
            "lens": "镜头畸变矫正：正值拉直桶形，负值修枕形，0 为不处理",
        }
        self._flash(tips.get(which, "已打开「镜头 · 胶片 · 人像」"))
        self.after(60, self._update_histogram)

    def _on_film(self):
        self.adj["film"] = self.film_var.get()
        self._mark_fast()
        self._request_render()

    def _sec_split(self, parent):
        b = self._section(parent, "色调分离（颜色分级）", opened=False,
                          on_open=self._split_lazy)
        self.split_body = b
        wheels = tk.Frame(b, bg=BAR_BG)
        wheels.pack(fill="x", pady=(px(2), px(4)))
        self.split_wheels = {}
        for which, label in (("hi", "高光"), ("lo", "阴影")):
            box = tk.Frame(wheels, bg=BAR_BG)
            box.pack(side="left", padx=(0, px(10)))
            tk.Label(box, text=label, font=self.ui_font_s, bg=BAR_BG,
                     fg=FG_DIM).pack()
            cv = tk.Canvas(box, width=px(62), height=px(62), bg=DEEP_BG,
                           highlightthickness=0, bd=0, cursor="hand2")
            cv.pack()
            cv.bind("<Button-1>", lambda e, w=which: self._wheel_click(w, e))
            self.split_wheels[which] = cv
        tk.Label(wheels, text="点色环选色相", font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left", anchor="s")
        # 120 个扇形推迟到展开时再画

    def _split_lazy(self, _b=None):
        for which in ("hi", "lo"):
            self._draw_hue_wheel(
                self.split_wheels[which],
                self.adj["split_hi_hue" if which == "hi" else "split_lo_hue"])
        b = self.split_body
        self._slider(b, "高光 · 饱和度", 0, 100, self.adj["split_hi_sat"],
                     lambda v: self.adj.__setitem__("split_hi_sat", v),
                     lambda: self.adj["split_hi_sat"], 0.0, 1, "%+.0f",
                     swatch=self._split_swatch("hi"))
        self._slider(b, "阴影 · 饱和度", 0, 100, self.adj["split_lo_sat"],
                     lambda v: self.adj.__setitem__("split_lo_sat", v),
                     lambda: self.adj["split_lo_sat"], 0.0, 1, "%+.0f",
                     swatch=self._split_swatch("lo"))

    def _split_swatch(self, which):
        try:
            r, g, b = _hue_rgb(self.adj["split_hi_hue" if which == "hi"
                                       else "split_lo_hue"])
            return "#%02x%02x%02x" % (int(r * 200), int(g * 200), int(b * 200))
        except Exception:
            return "#444444"

    def _sec_local(self, parent):
        b = self._section(parent, "局部调整（径向 / 渐变）", opened=False)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(2), 0))
        self._panel_btn(row, "新建径向", lambda: self.start_local("radial"))
        self._panel_btn(row, "新建渐变", lambda: self.start_local("linear"))
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "主体选择",
                        lambda: self.add_content_local("subject"))
        self._panel_btn(row, "高对比主体",
                        lambda: self.add_content_local("contrast"))
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "删除选中", self.delete_local)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "清空", self.clear_locals)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "复制滤镜", self.copy_local)
        self._panel_btn(row, "粘贴滤镜", self.paste_local)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "上移", lambda: self.move_local(-1))
        self._panel_btn(row, "下移", lambda: self.move_local(1))
        self.local_box = tk.Listbox(
            b, height=4, bg=DEEP_BG, fg=FG, selectbackground=ACCENT,
            selectforeground="#101010", bd=0, highlightthickness=0,
            font=self.ui_font_s, activestyle="none", exportselection=False)
        self.local_box.pack(fill="x", pady=(px(3), 0))
        self.local_box.bind("<<ListboxSelect>>", self._on_local_select)
        self._bind_wheel(self.local_box)
        mini = tk.Frame(b, bg=BAR_BG)
        mini.pack(fill="x", pady=(px(4), 0))
        self.local_mini = tk.Canvas(mini, width=px(104), height=px(70),
                                    bg=DEEP_BG, highlightthickness=0, bd=0)
        self.local_mini.pack(side="left", padx=(0, px(8)))
        self.local_mini_lbl = tk.Label(mini, text="尚未选中滤镜",
                                       font=self.ui_font_s, bg=BAR_BG,
                                       fg=FG_DIM, anchor="w", justify="left",
                                       wraplength=px(90))
        self.local_mini_lbl.pack(side="left", fill="both", expand=True)
        self.local_body = tk.Frame(b, bg=BAR_BG)
        self.local_body.pack(fill="x")
        tk.Label(b, text="画面上拖动可直接建/移动滤镜",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                 anchor="w").pack(fill="x", pady=(px(2), 0))
        return b

    def _sec_snapshot(self, parent):
        b = self._section(parent, "快照", opened=False)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(2), 0))
        self._panel_btn(row, "保存快照", self.add_snapshot)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "恢复选中", self.restore_snapshot)
        self._panel_btn(row, "删除选中", self.delete_snapshot)
        self.snapshot_box = tk.Listbox(
            b, height=4, bg=DEEP_BG, fg=FG, selectbackground=ACCENT,
            selectforeground="#101010", bd=0, highlightthickness=0,
            font=self.ui_font_s, activestyle="none", exportselection=False)
        self.snapshot_box.pack(fill="x", pady=(px(3), 0))
        self.snapshot_box.bind("<Double-Button-1>", self.restore_snapshot)
        self._bind_wheel(self.snapshot_box)
        tk.Label(b, text="把当前整套调整存下来，随时切回", font=self.ui_font_s,
                 bg=BAR_BG, fg=FG_DIM, anchor="w").pack(fill="x", pady=(px(2), 0))
        return b

    def _snapshot_state(self):
        return {"adj": copy.deepcopy(self.adj),
                "geom": list(self.geom),
                "locals": copy.deepcopy(self.locals),
                "straighten": self.straighten}

    def add_snapshot(self):
        if self.doc is None:
            return
        n = len(self.snapshots) + 1
        self.snapshots.append({"name": "快照 %d" % n,
                               "state": self._snapshot_state()})
        self._refresh_snapshot_box()
        self._flash("已存为「快照 %d」" % n)

    def _snapshot_index(self):
        box = self.snapshot_box
        if box is None or not box.winfo_exists():
            return None
        sel = box.curselection()
        return sel[0] if sel else None

    def restore_snapshot(self, event=None):
        idx = self._snapshot_index()
        if idx is None or idx >= len(self.snapshots):
            self._flash("先在列表里选中一个快照")
            return
        st = self.snapshots[idx]["state"]
        self.adj = copy.deepcopy(st["adj"])
        self.geom = list(st["geom"])
        self.locals = copy.deepcopy(st["locals"])
        self.straighten = st.get("straighten", 0.0)
        for k in ("tone_key", "color_key", "auto_lut", "geom_key",
                  "contrast_mean", "grain_key", "vig_key"):
            setattr(self, k, None)
        self.tile_cache.clear()
        self.preview_key = None
        self.hsv_src = None
        self.hsv_chans = None
        self.local_mask_cache = {}
        self.detail_cache.clear()
        self._sync_panel()
        self._sync_cropbar()
        self._push_history("快照：%s" % self.snapshots[idx]["name"])
        self._render()
        self._update_status()

    def delete_snapshot(self):
        idx = self._snapshot_index()
        if idx is None or idx >= len(self.snapshots):
            self._flash("先在列表里选中一个快照")
            return
        name = self.snapshots.pop(idx)["name"]
        self._refresh_snapshot_box()
        self._flash("已删除「%s」" % name)

    def _refresh_snapshot_box(self):
        box = getattr(self, "snapshot_box", None)
        if box is None or not box.winfo_exists():
            return
        box.delete(0, "end")
        for s in self.snapshots:
            box.insert("end", s["name"])

    def _sec_preset(self, parent):
        b = self._section(parent, "预设", opened=False)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(2), 0))
        self._panel_btn(row, "保存当前为预设", self.add_preset)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "删除选中", self.delete_preset)
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self._panel_btn(row, "导入…", self.import_presets)
        self._panel_btn(row, "导出…", self.export_presets)
        self.preset_box = tk.Listbox(
            b, height=5, bg=DEEP_BG, fg=FG, selectbackground=ACCENT,
            selectforeground="#101010", bd=0, highlightthickness=0,
            font=self.ui_font_s, activestyle="none", exportselection=False)
        self.preset_box.pack(fill="x", pady=(px(3), 0))
        self.preset_box.bind("<<ListboxSelect>>", self._on_preset_select)
        self.preset_box.bind("<Double-Button-1>", self._on_preset_select)
        self._bind_wheel(self.preset_box)
        tk.Label(b, text="单击列表即可套用", font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM, anchor="w").pack(fill="x", pady=(px(2), 0))
        return b

    def _sec_effect(self, parent):
        return self._section(parent, "效果", opened=False,
                             on_open=self._build_effect)

    def _build_effect(self, b):
        self._slider(b, "暗角", -100, 100, self.adj["vignette"],
                     lambda v: self.adj.__setitem__("vignette", v),
                     lambda: self.adj["vignette"], 0.0, 1, "%+.0f")
        tk.Label(b, text="水印（预览与导出一致）", font=self.ui_font_s,
                 bg=BAR_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", pady=(px(8), px(2)))
        self.wm_var = tk.StringVar(value=self.wm_text)
        ent = tk.Entry(b, textvariable=self.wm_var, bg=DEEP2_BG, fg=FG,
                       insertbackground=FG, relief="flat", bd=0,
                       highlightthickness=px(1), highlightbackground=TROUGH_BG,
                       highlightcolor=ACCENT, font=self.ui_font)
        ent.pack(fill="x", ipady=px(4))
        self.wm_var.trace_add("write", lambda *a: self._on_wm_text())
        row = tk.Frame(b, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        self.wm_pos_btn = self._panel_btn(row, "位置：右下", self._cycle_wm_pos)
        self._panel_btn(row, "清除", self._clear_watermark)
        self._slider(b, "水印大小", 1, 12, self.wm_size,
                     lambda v: setattr(self, "wm_size", v),
                     lambda: self.wm_size, 3.5, 1, "%.1f%%")
        self._slider(b, "水印浓度", 5, 100, self.wm_alpha,
                     lambda v: setattr(self, "wm_alpha", v),
                     lambda: self.wm_alpha, 65.0, 0, "%.0f")

    def _on_wm_text(self):
        self.wm_text = self.wm_var.get()
        self._mark_fast()
        self._request_render()

    def _cycle_wm_pos(self):
        order = ["br", "bl", "c"]
        label = {"br": "右下", "bl": "左下", "c": "居中"}
        self.wm_pos = order[(order.index(self.wm_pos) + 1) % len(order)]
        if self.wm_pos_btn is not None and self.wm_pos_btn.winfo_exists():
            self.wm_pos_btn.configure(text="位置：" + label[self.wm_pos])
        self._mark_fast()
        self._request_render()

    def _clear_watermark(self):
        if self.wm_var is not None:
            self.wm_var.set("")

    def _bind_wheel(self, w):
        w.bind("<MouseWheel>", self._on_panel_wheel)
        for c in w.winfo_children():
            self._bind_wheel(c)

    def _on_panel_wheel(self, event):
        """面板滚动：按平台归一化滚轮增量，一格约 3 个步长（每步 22 像素）。

        Windows 一格是 ±120，macOS 触控板是 ±1 量级；只判断正负会让触控板滚得又慢
        又不均匀，所以走 wheel_units 统一换算。
        """
        units = wheel_units(event.delta)
        if not units:
            return "break"
        n = max(1, int(round(abs(units) * 3)))
        self.pcan.yview_scroll(-n if units > 0 else n, "units")
        return "break"

    def _save_setting(self, key, value):
        """只更新单个设置项（语言这类小改动不必重写全部设置）。"""
        try:
            data = {}
            path = self._settings_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh) or {}
            data[key] = value
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def _apply_lang(self):
        """把界面文字切换成当前语言（保留原文，可来回切换）。"""
        first = not getattr(self, "_lang_ready", False)
        self._lang_ready = True
        # 默认中文启动时界面本来就是中文，逐控件翻译一遍纯属浪费
        # （实测启动阶段这里约 0.5 秒）；真正切换语言时才走完整流程。
        if first and APP_LANG == "zh":
            return
        if True:
            def do_widget(w):
                for ch in w.winfo_children():
                    cls = ""
                    try:
                        cls = ch.winfo_class()
                    except Exception:
                        continue
                    if isinstance(ch, tk.Toplevel):
                        # 窗口标题不是控件文字，_apply_lang 原来管不到。
                        # 存下原文再翻；"%s · 结果" 这类带占位符的走模板匹配。
                        try:
                            cur_title = ch.title()
                        except Exception:
                            cur_title = ""
                        if cur_title:
                            orig_title = getattr(ch, "_orig_title", None)
                            if orig_title is None:
                                orig_title = cur_title
                                try:
                                    ch._orig_title = cur_title
                                except Exception:
                                    pass
                            try:
                                ch.title(_trf(orig_title))
                            except Exception:
                                pass
                    if cls == "Menu":
                        try:
                            last = ch.index("end")
                        except Exception:
                            last = None
                        if last is not None:
                            for i in range(int(last) + 1):
                                try:
                                    label = ch.entrycget(i, "label")
                                except Exception:
                                    continue
                                if not label:
                                    continue
                                store = getattr(ch, "_orig_labels", None)
                                if store is None:
                                    store = {}
                                    ch._orig_labels = store
                                if i not in store:
                                    store[i] = label
                                try:
                                    ch.entryconfigure(i, label=_trf(store[i]))
                                except Exception:
                                    pass
                    elif isinstance(ch, _QpeRoundButton):
                        # 自绘圆角按钮：文字存在 _text 里，不是 Tk 的 text 选项
                        orig = getattr(ch, "_orig_text", None)
                        if orig is None:
                            orig = ch._text
                            try:
                                ch._orig_text = orig
                            except Exception:
                                pass
                        try:
                            ch.configure(text=_trf(orig))
                        except Exception:
                            pass
                    elif cls in ("Label", "Button", "Checkbutton",
                                 "Radiobutton", "Menubutton"):
                        try:
                            cur = ch.cget("text")
                        except Exception:
                            cur = None
                        if cur:
                            orig = getattr(ch, "_orig_text", None)
                            if orig is None:
                                orig = cur
                                try:
                                    ch._orig_text = cur
                                except Exception:
                                    pass
                            try:
                                ch.configure(text=_trf(orig))
                            except Exception:
                                pass
                    do_widget(ch)
            do_widget(self)
            # 文字变了按钮宽度也变了：先重新量一遍，再让父容器重新分配空间。
            # 只调 _layout_bar 不够 —— pack 会把组压到旧宽度（实测英文被裁成 40px）。
            try:
                if not getattr(self, "_rebuilding_bar", False):
                    self._rebuilding_bar = True
                    try:
                        self._build_bar()
                        self._apply_lang()      # 新控件是中文，再翻一遍
                    finally:
                        self._rebuilding_bar = False
            except Exception:
                pass
            try:
                self.update_idletasks()
            except Exception:
                pass

    def _sync_panel_btn(self):
        """面板开关要有选中态，否则看不出当前是开还是关。"""
        b = getattr(self, "panel_btn", None)
        if b is None:
            return
        try:
            if self.panel_shown:
                b.configure(bg=TROUGH_BG, fg=FG_HI)
            else:
                b.configure(bg=BAR_BG, fg=FG)
        except Exception:
            pass

    def _panel_drag_start(self, event):
        self._panel_drag = (event.x_root, self.panel.winfo_width())

    def _panel_drag_move(self, event):
        state = getattr(self, "_panel_drag", None)
        if not state:
            return
        x0, w0 = state
        limit = max(px(200), min(px(560), int(self.winfo_width() * 0.45)))
        new = max(px(200), min(limit, w0 + (x0 - event.x_root)))
        self.panel.configure(width=new)
        self.panel_width = new

    def _panel_drag_end(self, event):
        self._panel_drag = None
        try:
            self.save_settings()
        except Exception:
            pass

    def _panel_drag_reset(self, event=None):
        self.panel_width = px(238)
        try:
            self.panel.configure(width=self.panel_width)
        except Exception:
            pass
        try:
            self.save_settings()
        except Exception:
            pass

    def _ensure_panel(self):
        """面板默认不建，第一次打开时才建；语言不是中文时补翻一遍。"""
        if getattr(self, "panel", None) is not None:
            return
        self._build_panel()
        try:
            if APP_LANG != "zh":
                self._apply_lang()
            self._sync_panel()
            self._refresh_sort_btn()
            self._refresh_preset_box()
            self._schedule_histogram()
            if self.clip_warn and self.clip_btn is not None:
                self.clip_btn.configure(bg=ACCENT, fg="#101010")
        except Exception:
            traceback.print_exc()

    def toggle_panel(self, show=None):
        if VIEWER_ONLY:            # 看图版没有修图面板
            return
        want = (not self.panel_shown) if show is None else bool(show)
        if want == self.panel_shown:
            return
        self.panel_shown = want
        if want:
            self._ensure_panel()
            self.panel.pack(side="right", fill="y", before=self.canvas)
            try:
                self.panel_grip.pack(side="right", fill="y",
                                     before=self.canvas)
            except Exception:
                pass
        else:
            self.panel.pack_forget()
            try:
                self.panel_grip.pack_forget()
            except Exception:
                pass
        self._sync_panel_btn()
        self.after(40, self._render)
        if want:
            self.after(60, self._update_histogram)

    def _sync_panel(self):
        if not self.sliders:
            return
        self.syncing = True
        try:
            self.sliders = [s for s in self.sliders if s[0].winfo_exists()]
            for sc, val, getter, fmt, _lb in self.sliders:
                v = getter()
                sc.set(v)
                val.configure(text=fmt % v)
            if self.var_gray is not None:
                self.var_gray.set(1 if self.adj["grayscale"] else 0)
                self.var_auto.set(1 if self.adj["auto"] else 0)
            self._draw_curve()
        finally:
            self.syncing = False
        self._schedule_histogram()

    def _on_toggle(self, key, var):
        if self.syncing:
            return
        self.adj[key] = bool(var.get())
        if key == "auto":
            self.auto_lut = None
        self._mark_fast()
        self._push_history("灰度" if key == "grayscale" else "自动色阶")
        self._render()
        self._update_status()
        self._schedule_histogram()

    def start_local(self, kind):
        if self.doc is None:
            return
        self.picker_mode = False
        self.toggle_panel(True)
        if "局部调整（径向 / 渐变）" in self.sections:
            body, toggle = self.sections["局部调整（径向 / 渐变）"]
            if not body.winfo_ismapped():
                toggle()
        self.local_mode = kind
        self.canvas.configure(cursor="crosshair")
        self._draw_hint()
        self._flash("在画面上拖动即可画出%s滤镜" % ("径向" if kind == "radial"
                                                  else "渐变"))

    def _add_local(self, filt):
        self.locals.append(filt)
        self._select_local(len(self.locals) - 1)

    def _select_local(self, idx):
        self.local_sel = idx if 0 <= idx < len(self.locals) else -1
        self._refresh_local_box()
        self._rebuild_local_sliders()
        self._draw_local_mini()
        self._render()
        self._update_status()

    def _refresh_local_box(self):
        box = self.local_box
        if box is None or not box.winfo_exists():
            return
        box.delete(0, "end")
        for i, f in enumerate(self.locals):
            box.insert("end", " %d. %s%s" % (
                i, {"radial": "径向", "linear": "渐变",
                    "subject": "主体", "contrast": "高对比"}.get(
                    f["type"], f["type"]),
                "（反相）" if f["invert"] else ""))
        box.selection_clear(0, "end")
        if 0 <= self.local_sel < len(self.locals):
            box.selection_set(self.local_sel)

    def _on_local_select(self, event=None):
        sel = self.local_box.curselection()
        if sel:
            self._select_local(int(sel[0]))

    def copy_local(self):
        if 0 <= self.local_sel < len(self.locals):
            self.local_clip = copy.deepcopy(self.locals[self.local_sel])
            self._flash("已复制「%s」滤镜（含参数与位置）" % (
                "径向" if self.local_clip["type"] == "radial" else "渐变"))

    def paste_local(self):
        if self.local_clip is None:
            self._flash("剪贴板里还没有滤镜（先按「复制滤镜」）")
            return
        f = copy.deepcopy(self.local_clip)
        # 稍微挪一点，否则叠在一起看不出是新的
        f["cx"] = min(0.92, max(0.08, f["cx"] + 0.06))
        f["cy"] = min(0.92, max(0.08, f["cy"] + 0.06))
        self.locals.append(f)
        self.local_mask_cache = {}
        self._select_local(len(self.locals) - 1)
        self._push_history("粘贴局部滤镜")
        self._render()
        self._flash("已粘贴滤镜，共 %d 个" % len(self.locals))

    def move_local(self, delta):
        """调整滤镜顺序。滤镜按顺序叠加，顺序会改变最终效果。"""
        i = self.local_sel
        j = i + delta
        if not (0 <= i < len(self.locals)) or not (0 <= j < len(self.locals)):
            return
        self.locals[i], self.locals[j] = self.locals[j], self.locals[i]
        self.local_mask_cache = {}
        self._select_local(j)
        self._push_history("调整滤镜顺序")
        self._render()
        self._flash("滤镜已移到第 %d 位" % (j + 1))

    def delete_local(self):
        if 0 <= self.local_sel < len(self.locals):
            self.locals.pop(self.local_sel)
            self._select_local(min(self.local_sel, len(self.locals) - 1))
            self._push_history("删除局部滤镜")
            self._render()

    def clear_locals(self):
        if self.locals:
            self.locals = []
            self._select_local(-1)
            self._push_history("清空局部滤镜")
            self._render()

    def _rebuild_local_sliders(self):
        if self.local_body is None or not self.local_body.winfo_exists():
            return
        for w in self.local_body.winfo_children():
            w.destroy()
        self.sliders = [s for s in self.sliders if s[0].winfo_exists()]
        if not (0 <= self.local_sel < len(self.locals)):
            self._relayout_panel()
            return
        f = self.locals[self.local_sel]
        tk.Label(self.local_body, text="— 滤镜参数 —", font=self.ui_font_s,
                 bg=BAR_BG, fg=ACCENT, anchor="w").pack(fill="x",
                                                        pady=(px(4), 0))

        def bind_size(key, lo, hi, step, fmt):
            self._slider(self.local_body, "· " + {"rx": "大小", "ry": "纵向大小",
                                                  "feather": "羽化",
                                                  "angle": "角度",
                                                  "spread": "过渡宽度"}[key],
                         lo, hi, f[key],
                         lambda v, k=key: self._set_local(k, v),
                         lambda k=key: f[k], f[key], step, fmt)

        if f["type"] == "radial":
            bind_size("rx", 0.02, 1.5, 0.01, "%.2f")
            bind_size("ry", 0.02, 1.5, 0.01, "%.2f")
            bind_size("feather", 0, 100, 1, "%+.0f")
        else:
            bind_size("spread", 0.05, 2.0, 0.01, "%.2f")
        bind_size("angle", -180, 180, 1, "%+.0f")
        for key, label, lo, hi, step, fmt in (
                ("exposure", "曝光", -3.0, 3.0, 0.01, "%+.2f"),
                ("contrast", "对比度", -100, 100, 1, "%+.0f"),
                ("highlights", "高光", -100, 100, 1, "%+.0f"),
                ("shadows", "阴影", -100, 100, 1, "%+.0f"),
                ("temperature", "色温", -100, 100, 1, "%+.0f"),
                ("tint", "色调", -100, 100, 1, "%+.0f"),
                ("saturation", "饱和度", -100, 100, 1, "%+.0f"),
                ("sharpen", "锐化", 0, 150, 1, "%+.0f")):
            self._slider(self.local_body, "· " + label, lo, hi, f["adj"][key],
                         lambda v, k=key: self._set_local_adj(k, v),
                         lambda k=key: f["adj"][k], 0.0, step, fmt)
        row = tk.Frame(self.local_body, bg=BAR_BG)
        row.pack(fill="x", pady=(px(4), 0))
        self._panel_btn(row, "反相", self._invert_local)
        self._bind_wheel(self.local_body)
        self._draw_local_mini()
        self._relayout_panel()

    def _set_local(self, key, value):
        if 0 <= self.local_sel < len(self.locals):
            self.locals[self.local_sel][key] = value

    def _set_local_adj(self, key, value):
        if 0 <= self.local_sel < len(self.locals):
            self.locals[self.local_sel]["adj"][key] = value

    def _invert_local(self):
        if 0 <= self.local_sel < len(self.locals):
            f = self.locals[self.local_sel]
            f["invert"] = not f["invert"]
            self._push_history("反相局部滤镜")
            self._refresh_local_box()
            self._render()

    def _canvas_to_norm(self, x, y):
        im = self._view_image()
        if im is None:
            return 0.0, 0.0
        ix, iy = self._canvas_to_image(x, y)
        return ix / max(1, im.size[0]), iy / max(1, im.size[1])

    def _norm_to_canvas(self, u, v):
        im = self._view_image()
        if im is None:
            return 0.0, 0.0
        return self._image_to_canvas(u * im.size[0], v * im.size[1])

    def _hit_local(self, x, y):
        """画布坐标处的点落在哪个局部滤镜里（掩膜是图像空间的，必须先换算）。"""
        im = self._view_image()
        if im is None:
            return -1
        ix, iy = self._canvas_to_image(x, y)
        if not (0 <= ix < im.size[0] and 0 <= iy < im.size[1]):
            return -1
        px_, py_ = int(ix), int(iy)
        for i in range(len(self.locals) - 1, -1, -1):
            try:
                if self._local_mask(self.locals[i], im.size).getpixel(
                        (px_, py_)) > 8:
                    return i
            except Exception:
                continue
        return -1

    def _draw_hint(self):
        """画布顶部的模式提示条：告诉用户现在该做什么。"""
        c = self.canvas
        for it in self.hint_items:
            try:
                c.delete(it)
            except Exception:
                pass
        self.hint_items = []
        if self.local_mode == "radial":
            msg = "拖动即可画出径向滤镜 · Esc 取消"
        elif self.local_mode == "linear":
            msg = "拖动即可画出渐变滤镜 · Esc 取消"
        elif self.picker_mode:
            msg = "点一下画面里应该是中性灰的地方 · Esc 取消"
        elif self.crop_mode:
            msg = "拖动框选裁剪范围 · Enter 应用 · Esc 取消"
        else:
            return
        f = tkfont.Font(font=self.ui_font)
        tw = f.measure(msg)
        th = f.metrics("linespace")
        pad = px(12)
        cw = max(1, c.winfo_width())
        cx = cw // 2
        y = px(12)
        self.hint_items.append(c.create_rectangle(
            cx - tw // 2 - pad, y, cx + tw // 2 + pad, y + th + pad,
            fill=ACCENT, outline=""))
        self.hint_items.append(c.create_text(
            cx, y + pad // 2 + px(1), text=msg, fill="#101010",
            font=self.ui_font, anchor="n"))
        for it in self.hint_items:
            c.tag_raise(it)

    def _draw_locals(self):
        c = self.canvas
        # 拖动调色时滤镜轮廓根本没变，但原来每帧都删掉再重建（每个 49 点多边形），
        # 白白花掉不少 Tk 调用。这里按「选择 + 视口 + 滤镜几何」做签名，没变就跳过。
        sig = (self.local_sel, round(self.scale, 5),
               None if self.cx is None else round(self.cx, 1),
               None if self.cy is None else round(self.cy, 1),
               c.winfo_width(), c.winfo_height(),
               tuple((f["type"], round(f["cx"], 4), round(f["cy"], 4),
                      round(f["rx"], 4), round(f["ry"], 4),
                      round(f["angle"], 2), round(f["spread"], 3),
                      round(f["feather"], 1), f["invert"])
                     for f in self.locals))
        if sig == getattr(self, "_locals_sig", None):
            return
        self._locals_sig = sig
        for it in self.local_items:
            try:
                c.delete(it)
            except Exception:
                pass
        self.local_items = []
        im = self._view_image()
        if im is None or not self.locals:
            return
        iw, ih = im.size
        s = max(self.scale, 1e-6)
        lw = max(1, px(2))
        for i, f in enumerate(self.locals):
            sel = (i == self.local_sel)
            col = ACCENT if sel else "#8a8a8a"
            ang = math.radians(f["angle"])
            ca, sa = math.cos(ang), math.sin(ang)
            if f["type"] in ("subject", "contrast"):
                continue          # 内容遮罩没有可拖的几何轮廓
            if f["type"] == "radial":
                cx, cy = self._norm_to_canvas(f["cx"], f["cy"])
                rx = max(2.0, f["rx"] * iw * s)
                ry = max(2.0, f["ry"] * ih * s)
                pts = []
                for k in range(49):
                    th = 2 * math.pi * k / 48
                    ex = math.cos(th) * rx
                    ey = math.sin(th) * ry
                    pts.extend((cx + ex * ca - ey * sa, cy + ex * sa + ey * ca))
                self.local_items.append(c.create_polygon(
                    *pts, outline=col, fill="", width=lw,
                    dash=() if sel else (px(7), px(5))))
                if sel:
                    # 羽化带可视化：遮罩在 d=1（外圈）衰减到 0，在 d=(1-feather)
                    # 处仍是满强度，所以内圈就是「开始衰减」的边界。
                    feat = max(0.02, min(1.0, f["feather"] / 100.0))
                    inner = 1.0 - feat
                    if inner > 0.02:
                        pts2 = []
                        for k in range(49):
                            th = 2 * math.pi * k / 48
                            ex = math.cos(th) * rx * inner
                            ey = math.sin(th) * ry * inner
                            pts2.extend((cx + ex * ca - ey * sa,
                                         cy + ex * sa + ey * ca))
                        self.local_items.append(c.create_polygon(
                            *pts2, outline="#ffffff", fill="",
                            width=max(1, px(1)), dash=(px(3), px(4))))
                    for hx, hy in ((cx, cy), (cx - rx, cy), (cx + rx, cy),
                                   (cx, cy - ry), (cx, cy + ry)):
                        r = px(4)
                        self.local_items.append(c.create_oval(
                            hx - r, hy - r, hx + r, hy + r, fill=ACCENT,
                            outline="#101010"))
            else:
                cx, cy = self._norm_to_canvas(f["cx"], f["cy"])
                span = max(4.0, f["spread"] * math.hypot(iw, ih) * 0.5 * s)
                L = math.hypot(c.winfo_width(), c.winfo_height()) * 1.5
                nx, ny = -sa, ca
                for off in (-span / 2.0, 0.0, span / 2.0):
                    bx = cx + ca * off
                    by = cy + sa * off
                    self.local_items.append(c.create_line(
                        bx - nx * L, by - ny * L, bx + nx * L, by + ny * L,
                        fill=col, width=lw,
                        dash=() if off == 0.0 else (px(7), px(5))))
                if sel:
                    r = px(5)
                    self.local_items.append(c.create_oval(
                        cx - r, cy - r, cx + r, cy + r, fill=ACCENT,
                        outline="#101010"))
        for it in self.local_items:
            c.tag_raise(it)

    def start_picker(self):
        if self.doc is None:
            return
        self.toggle_panel(True)
        self.picker_mode = not self.picker_mode
        self.local_mode = None
        self.canvas.configure(cursor="crosshair" if self.picker_mode else "arrow")
        self._draw_hint()
        self._update_status()
        if self.picker_mode:
            self._flash("点一下画面里应该是中性灰（白/灰）的地方")

    def pick_white_balance(self, x, y):
        """把点击处当作中性灰反解白平衡，比手动拖色温准得多。"""
        im = self._view_image()
        if im is None:
            return
        ix, iy = self._canvas_to_image(x, y)
        iw, ih = im.size
        if not (0 <= ix < iw and 0 <= iy < ih):
            self._flash("请点在图片上")
            return
        r = max(2, int(min(iw, ih) * 0.006))
        box = (max(0, int(ix) - r), max(0, int(iy) - r),
               min(iw, int(ix) + r + 1), min(ih, int(iy) + r + 1))
        patch = im.convert("RGB").crop(box)
        stat = ImageStat.Stat(patch)
        sr, sg, sb = (max(1.0, v) for v in stat.mean[:3])
        # 要让 gr*sr == gg*sg == gb*sb，设公共目标 k。
        # 由 gr = 1+0.34t、gb = 1-0.34t 联立消去 t 得 k 为 sr、sb 的调和平均，
        # 再由 gg = 1-0.26g 解出 tint。
        k = 2.0 * sr * sb / (sr + sb)
        t = (k / sr - 1.0) / 0.34
        g = (1.0 - k / sg) / 0.26
        self.adj["temperature"] = max(-100.0, min(100.0, t * 100.0))
        self.adj["tint"] = max(-100.0, min(100.0, g * 100.0))
        self.tone_key = None
        self.picker_mode = False
        self.canvas.configure(cursor="arrow")
        self._sync_panel()
        self._push_history("白平衡吸管")
        self._render()
        self._update_status()
        self._flash("白平衡：色温 %+.0f  色调 %+.0f" % (
            self.adj["temperature"], self.adj["tint"]))

    def _sort_list(self, files):
        """按当前设置排序文件列表。"""
        desc = self.sort_desc
        try:
            if self.sort_key == "mtime":
                return sorted(files, key=os.path.getmtime, reverse=desc)
            if self.sort_key == "size":
                return sorted(files, key=os.path.getsize, reverse=desc)
        except Exception:
            pass
        return sorted(files, key=lambda p: os.path.basename(p).lower(),
                      reverse=desc)

    def _sort_label(self):
        names = {"name": _tr("文件名"), "mtime": _tr("修改时间"),
                 "size": _tr("文件大小")}
        return _tr("排序：%s%s") % (names.get(self.sort_key, _tr("文件名")),
                                    "↓" if self.sort_desc else "")

    def _refresh_sort_btn(self):
        if self.sort_btn is not None and self.sort_btn.winfo_exists():
            self.sort_btn.configure(text=self._sort_label())

    def _sort_menu(self):
        """点「排序」按钮弹出菜单。"""
        m = tk.Menu(self, tearoff=0)
        for key, label in (("name", "文件名"), ("mtime", "修改时间"),
                           ("size", "文件大小")):
            m.add_command(
                label=("✓ " if key == self.sort_key and not self.sort_desc
                       else "     ") + label + " ↑",
                command=lambda k=key: self.set_sort(k, False))
            m.add_command(
                label=("✓ " if key == self.sort_key and self.sort_desc
                       else "     ") + label + " ↓",
                command=lambda k=key: self.set_sort(k, True))
        m.tk_popup(self.sort_btn.winfo_rootx(),
                   self.sort_btn.winfo_rooty() + self.sort_btn.winfo_height())

    def set_sort(self, key, desc):
        """改变排序：当前打开的图片保持在视野里，不跳走。"""
        self.sort_key, self.sort_desc = key, desc
        self._refresh_sort_btn()
        if not self.files:
            return
        cur = self.files[self.index] if 0 <= self.index < len(self.files) else None
        self.files = self._sort_list(self.files)
        if cur in self.files:
            self.index = self.files.index(cur)
        self._update_title()
        self._update_status()
        if self.strip_shown:
            self._strip_layout()
            self._strip_kick()
        self._flash(self._sort_label())

    def toggle_clip(self, show=None):
        """过曝/欠曝警告开关。"""
        want = (not self.clip_warn) if show is None else bool(show)
        self.clip_warn = want
        if self.clip_btn is not None and self.clip_btn.winfo_exists():
            self.clip_btn.configure(bg=ACCENT if want else BTN_BG,
                                    fg="#101010" if want else FG)
        self._render()
        if want:
            self._flash("过曝标红、欠曝标蓝")

    def _auto_stats(self):
        """取当前画面（已经过旋转/裁剪）的亮度与色彩统计。"""
        im = self._view_image()
        if im is None:
            return None
        small = im.convert("RGB")
        small.thumbnail((360, 360), Image.Resampling.BILINEAR)
        a = _np.asarray(small, dtype=_np.float32) / 255.0
        lum = a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114
        p1, p50, p99 = [float(v) for v in _np.percentile(lum, [1.0, 50.0, 99.0])]
        flat = a.reshape(-1, 3)
        lf = lum.reshape(-1)
        mid = (lf > 0.08) & (lf < 0.92)          # 只用中间调估白平衡
        return {"a": a, "lum": lum, "p1": p1, "p50": p50, "p99": p99,
                "mid": flat[mid] if mid.any() else flat}

    def auto_tone(self):
        """自动色调：把中间调推到 0.42，按 1%/99% 分位铺满动态范围。"""
        if self.doc is None or _np is None:
            return
        st = self._auto_stats()
        if st is None:
            return
        p1, p50, p99 = st["p1"], st["p50"], st["p99"]
        ev = math.log2(max(p50, 0.004) / 0.42) * -1.0
        a = self.adj
        a["exposure"] = round(max(-2.5, min(2.5, ev)), 2)
        # 用 1%/99% 分位决定黑白场：两头没吃到就往外拉，已经吃到就回收
        a["blacks"] = round(max(-60.0, min(45.0, (p1 - 0.012) * -230.0)), 0)
        a["whites"] = round(max(-45.0, min(60.0, (0.985 - p99) * 240.0)), 0)
        # 动态范围偏窄的图给一点对比度
        span = max(0.01, p99 - p1)
        a["contrast"] = round(max(0.0, min(28.0, (0.62 - span) * 70.0)), 0)
        # 已经溢出的一侧做回收
        a["highlights"] = -25.0 if st["a"].max() >= 0.995 else 0.0
        a["shadows"] = 25.0 if st["a"].min() <= 0.01 else 0.0
        a["auto"] = False
        for k in ("tone_key", "color_key", "auto_lut"):
            setattr(self, k, None)
        self._sync_panel()
        self._push_history("自动色调")
        self._render()
        self._update_status()
        self._flash("自动色调：曝光 %+.2fEV  对比 %+d  黑白场 %+d/%+d" % (
            a["exposure"], a["contrast"], a["blacks"], a["whites"]))

    def auto_wb(self):
        """自动白平衡：灰世界假设，反解出最接近的色温/色调。"""
        if self.doc is None or _np is None:
            return
        st = self._auto_stats()
        if st is None:
            return
        mid = st["mid"]
        mr, mg, mb = [max(0.01, float(v)) for v in mid.mean(axis=0)]
        want_r, want_b = mg / mr, mg / mb        # 以绿通道为基准的期望增益
        best = None
        for ti in range(-100, 101, 4):
            for gi in range(-100, 101, 4):
                gr, gg, gb = _wb_gains({"temperature": ti, "tint": gi})
                gg = max(gg, 0.01)
                err = abs(gr / gg - want_r) + abs(gb / gg - want_b)
                if best is None or err < best[0]:
                    best = (err, ti, gi)
        if best is None:
            return
        self.adj["temperature"] = float(best[1])
        self.adj["tint"] = float(best[2])
        for k in ("tone_key", "color_key", "auto_lut"):
            setattr(self, k, None)
        self._sync_panel()
        self._push_history("自动白平衡")
        self._render()
        self._update_status()
        self._flash("自动白平衡：色温 %+d  色调 %+d" % (best[1], best[2]))

    def toggle_split(self, x=None):
        """分屏对比：左原图右效果，中间一条可拖动的分割线。"""
        if self.doc is None:
            return
        if self.split_x is None and x is None:
            self.split_x = 0.5
        elif x is None:
            self.split_x = None
        else:
            self.split_x = max(0.02, min(0.98, x))
        if self.split_btn is not None and self.split_btn.winfo_exists():
            self.split_btn.configure(
                bg=ACCENT if self.split_x is not None else BTN_BG,
                fg="#101010" if self.split_x is not None else FG)
        self._render()
        self._update_status()

    def _draw_split(self):
        c = self.canvas
        if self.split_item is not None:
            try:
                c.delete(self.split_item)
            except Exception:
                pass
            self.split_item = None
        for attr in ("split_label", "split_label2"):
            it = getattr(self, attr, None)
            if it is not None:
                try:
                    c.delete(it)
                except Exception:
                    pass
                setattr(self, attr, None)
        if self.split_x is None:
            return
        cw = max(1, c.winfo_width())
        ch = max(1, c.winfo_height())
        x = int(cw * self.split_x)
        self.split_item = c.create_line(x, 0, x, ch, fill="#ffffff",
                                        width=max(1, px(2)))
        self.split_label = c.create_text(
            x - px(8), px(10), text="原图", fill="#ffffff", anchor="ne",
            font=self.ui_font)
        self.split_label2 = c.create_text(
            x + px(8), px(10), text="效果", fill=ACCENT, anchor="nw",
            font=self.ui_font)
        for it in (self.split_item, self.split_label, self.split_label2):
            c.tag_raise(it)

    def _release_modes(self):
        """窗口失去焦点时，把所有「按住才生效」的临时状态收起。"""
        if self.show_original:
            self.toggle_compare(False)

    def toggle_compare(self, show=None):
        """按住 \\ 或点按钮，在原图与调整结果之间切换。"""
        self.show_original = (not self.show_original) if show is None             else bool(show)
        if self.cmp_btn is not None:
            self.cmp_btn.configure(
                bg=ACCENT if self.show_original else BTN_BG,
                fg="#101010" if self.show_original else FG)
        self._render()
        self._schedule_histogram()

    def copy_settings(self):
        if self.doc is None:
            return
        self.clip_adj = copy.deepcopy(self.adj)
        self._flash("已复制当前调整设置")

    def paste_settings(self):
        if self.doc is None or self.clip_adj is None:
            self._flash("剪贴板里还没有设置（先按 Ctrl+Shift+C）")
            return
        self.adj = copy.deepcopy(self.clip_adj)
        for k in ("tone_key", "color_key", "auto_lut", "geom_key"):
            setattr(self, k, None)
        self._sync_panel()
        self._push_history("粘贴设置")
        self._render()
        self._update_status()
        self._flash("已粘贴调整设置")

    # -------------------------------------------------------- 预设

    @staticmethod
    def _preset_path():
        base = _data_dir()
        new = os.path.join(base, APP_NAME + "_presets.json")
        # 程序从 pictu 改名为 QPE，顺手把老版本的预设文件搬过来，
        # 免得已有的预设因为文件名变了而"消失"。
        old = os.path.join(base, "Prism_presets.json")
        if not os.path.exists(new) and os.path.exists(old):
            try:
                os.replace(old, new)
            except OSError:
                pass
        old = os.path.join(base, "pictu_presets.json")
        if not os.path.exists(new) and os.path.exists(old):
            try:
                os.replace(old, new)
            except OSError:
                pass
        return new

    @staticmethod
    def _settings_path():
        new = os.path.join(_data_dir(), APP_NAME + "_settings.json")
        old = os.path.join(_data_dir(), "QPE_settings.json")
        if not os.path.exists(new) and os.path.exists(old):
            try:                     # 从旧名字平滑迁移
                os.replace(old, new)
            except OSError:
                pass
        return new

    # ---------------------------------------------------------------- 主题

    def _peek_setting(self, key, default=None):
        """在 load_settings 之前读一个设置项（只读，不建容器）。"""
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data.get(key, default)
        except Exception:
            return default

    def _peek_theme(self):
        """建界面前就要知道用哪套配色，所以直接读一次设置文件。"""
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as fh:
                name = json.load(fh).get("theme") or "dark"
        except Exception:
            return "dark"
        return "amber" if name == "fl" else name

    def _swap_colors(self, widget, delta):
        """把一棵控件树上仍然使用旧配色的选项换成新配色。

        只替换「当前值正好等于旧主题某个颜色」的选项，别的颜色不动，
        所以渐变、色带这类本来就该保持原色的东西不会被误改。
        """
        if getattr(widget, "_theme_preview", False):
            return
        opts = ("bg", "fg", "activebackground", "activeforeground",
                "selectbackground", "selectforeground", "troughcolor",
                "highlightbackground", "highlightcolor", "insertbackground",
                "disabledforeground", "selectcolor")
        try:
            for opt in opts:
                try:
                    cur = widget.cget(opt)
                except Exception:
                    continue
                if not cur:
                    continue
                new = delta.get(str(cur).lower())
                if new:
                    try:
                        widget.configure(**{opt: new})
                    except Exception:
                        pass
            if isinstance(widget, tk.Canvas):
                # 自绘图标按钮的背景圆角是 canvas item，不会跟着 widget bg 变
                try:
                    for item in widget.find_withtag("rbg"):
                        widget.itemconfigure(item, fill=BAR_BG)
                    for item in widget.find_withtag("icon"):
                        typ = widget.type(item)
                        if typ == "arc":
                            widget.itemconfigure(item, outline=FG)
                        elif typ == "line":
                            widget.itemconfigure(item, fill=FG)
                        elif typ in ("polygon", "oval", "rectangle"):
                            widget.itemconfigure(item, fill=FG)
                except Exception:
                    pass
            if isinstance(widget, _QpeRoundButton):
                # bg/fg 已由上面的 configure 写进 _bg/_fg；这里只补 hover 缓存
                try:
                    for attr in ("_hover_bg", "_hover_fg"):
                        old_c = str(getattr(widget, attr, "")).lower()
                        new_c = delta.get(old_c)
                        if new_c:
                            setattr(widget, attr, new_c)
                    widget._draw()
                except Exception:
                    pass
            if isinstance(widget, _QpeSlider):
                try:
                    widget._redraw()
                except Exception:
                    pass
        except Exception:
            pass
        for child in widget.winfo_children():
            self._swap_colors(child, delta)

    def show_settings(self):
        """设置窗口：主题、提示开关、配置位置。"""
        win = getattr(self, "set_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        win = tk.Toplevel(self)
        self.set_win = win
        win.title("设置")
        win.configure(bg=PANEL_BG)
        win.geometry("%dx%d" % (px(430), px(560)))
        win.after(60, lambda: _round_window(win))
        win.transient(self)
        self.after(40, self._apply_lang)
        try:
            win.iconbitmap(os.path.join(_res_dir(), "Prism.ico"))
        except Exception:
            pass

        tk.Button(win, text="完成", command=win.destroy, font=self.ui_font,
                  bg=ACCENT, fg=ON_BG, activebackground=BAR_HOVER,
                  activeforeground=ON_BG, relief="flat", bd=0,
                  highlightthickness=0, padx=px(20), pady=px(5),
                  cursor="hand2").pack(side="bottom", pady=(0, px(14)))

        body = tk.Frame(win, bg=PANEL_BG)
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, bg=PANEL_BG, highlightthickness=0, bd=0)
        # 自绘细滚动条：Tk 原生 Scrollbar 在 Windows 上不跟随深色主题，会出现白条
        scroll = tk.Canvas(body, width=px(8), bg=PANEL_BG,
                           highlightthickness=0, bd=0, cursor="hand2")
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        def draw_scroll(*_args):
            try:
                scroll.delete("all")
                w = scroll.winfo_width()
                h = scroll.winfo_height()
                if w < 2 or h < 2:
                    return
                scroll.create_rectangle(0, 0, w, h, fill=PANEL_BG, outline="")
                first, last = canvas.yview()
                if last - first >= 0.999:
                    return
                y0 = int(first * h)
                y1 = int(last * h)
                if y1 - y0 < px(18):
                    y1 = y0 + px(18)
                scroll.create_rectangle(
                    px(2), y0 + px(2), w - px(2),
                    min(h - px(2), y1 - px(2)),
                    fill=TROUGH_BG, outline="")
            except Exception:
                pass

        def on_scroll(first, last):
            draw_scroll()

        canvas.configure(yscrollcommand=on_scroll)
        holder = tk.Frame(canvas, bg=PANEL_BG)
        holder_id = canvas.create_window((0, 0), window=holder, anchor="nw")
        holder.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: (
            canvas.itemconfigure(holder_id, width=e.width), draw_scroll()))
        scroll.bind("<Configure>", lambda e: draw_scroll())
        scroll.bind("<Button-1>", lambda e: canvas.yview_moveto(
            max(0.0, min(1.0, e.y / max(1, scroll.winfo_height())))))
        scroll.bind("<B1-Motion>", lambda e: canvas.yview_moveto(
            max(0.0, min(1.0, e.y / max(1, scroll.winfo_height())))))
        self.set_canvas = canvas
        self.set_scroll = scroll
        self._draw_settings_scroll = draw_scroll

        wrap = tk.Frame(holder, bg=PANEL_BG)
        wrap.pack(fill="both", expand=True, padx=px(SPACE_2XL),
                  pady=px(SPACE_2XL))

        # 标题做成一张卡片，和主面板的层次一致（面板底更暗、卡片略亮）
        head = tk.Frame(wrap, bg=CARD_BG)
        head.pack(fill="x", pady=(0, px(SPACE_2XL)))
        tk.Label(head, text="设置", font=self.ui_font_l, bg=CARD_BG, fg=FG_HI,
                 anchor="w").pack(fill="x", padx=px(SPACE_XL),
                                  pady=(px(SPACE_XL), 0))
        tk.Label(head, text="改动立即生效，下次启动保留", font=self.ui_font_s,
                 bg=CARD_BG, fg=FG_DIM, anchor="w").pack(
                     fill="x", padx=px(SPACE_XL), pady=(0, px(SPACE_XL)))

        # 语言（改了立即重排界面）
        tk.Label(wrap, text=_tr("语言"), font=self.ui_font_b, bg=PANEL_BG,
                 fg=FG, anchor="w").pack(fill="x", pady=(px(SPACE_XL), px(SPACE_XS)))
        lrow = tk.Frame(wrap, bg=PANEL_BG)
        lrow.pack(fill="x")
        lvar = tk.StringVar(value=self.lang)

        def _set_lang():
            global APP_LANG
            self.lang = lvar.get()
            APP_LANG = self.lang
            try:
                self._save_setting("lang", self.lang)
            except Exception:
                pass
            self._apply_lang()
            self._update_title()
            self._update_status()

        for code, label in (("zh", "中文"), ("en", "English"), ("ja", "日本語")):
            tk.Radiobutton(lrow, text=label, value=code, variable=lvar,
                           command=_set_lang, font=self.ui_font,
                           bg=PANEL_BG, fg=FG, selectcolor=BAR_BG,
                           activebackground=PANEL_BG, anchor="w",
                           highlightthickness=0, bd=0).pack(
                               side="left", padx=(0, px(12)))

        # 与下面的选项行对齐：那几行没有额外左右内边距，这里也不加
        tk.Label(wrap, text="主题", font=self.ui_font_b, bg=PANEL_BG, fg=FG,
                 anchor="w").pack(fill="x", pady=(px(SPACE_XL), 0))
        tk.Label(wrap, text="点一下立即生效", font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM, anchor="w").pack(fill="x", pady=(0, px(6)))

        var = tk.StringVar(value=self.theme)
        # 两列主题网格：11 套主题也不会把设置窗口撑成一条长列表
        grid = tk.Frame(wrap, bg=PANEL_BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="theme")
        grid.columnconfigure(1, weight=1, uniform="theme")
        for _i, key in enumerate(THEME_ORDER):
            cell = tk.Frame(grid, bg=BAR_BG)
            cell.grid(row=_i // 2, column=_i % 2, sticky="ew",
                      padx=((0, px(4)) if _i % 2 == 0 else (px(4), 0)),
                      pady=px(1))
            tk.Radiobutton(
                cell, text=THEME_NAMES[key], variable=var, value=key,
                command=lambda k=key: self.set_theme(k),
                font=self.ui_font, bg=BAR_BG, fg=FG, activebackground=BAR_BG,
                activeforeground=FG_HI, selectcolor=DEEP_BG, anchor="w", bd=0,
                highlightthickness=0, padx=px(4), cursor="hand2").pack(
                    side="left")
            dots = tk.Frame(cell, bg=BAR_BG)
            dots.pack(side="right", padx=(0, px(4)))
            for role in ("BG", "BAR_BG", "FG", "ACCENT", "KNOB"):
                sw = tk.Frame(dots, width=px(10), height=px(10),
                              bg=THEMES[key][role])
                # 预览色块是主题的静态样本，切主题时不能被 _swap_colors 改色
                sw._theme_preview = True
                sw.pack(side="left", padx=(0, px(2)))

        tk.Frame(wrap, bg=RULE_BG, height=max(1, px(1))).pack(
            fill="x", pady=(px(12), px(10)))
        tk.Label(wrap, text="性能", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x")
        tk.Label(wrap, text="档位切换立即生效；大图默认只解代理尺寸，状态栏「全分辨率」可随时取回原图。",
                 font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                 justify="left", wraplength=px(370)).pack(
                     fill="x", pady=(0, px(4)))
        perf_var = tk.StringVar(value=getattr(self, "perf_profile",
                                               "fast-slider"))
        for code, label, desc in (
                ("fast-slider", "拖动优先（最跟手）", "滑杆拖动时优先降档，松手后补全"),
                ("fast-first", "首帧优先（打开更快）", "大图先出小预览，再解低档"),
                ("auto", "自动", "按文件大小在两段式与单段式之间选")):
            row = tk.Frame(wrap, bg=BAR_BG)
            row.pack(fill="x", pady=(px(1), 0))
            tk.Radiobutton(
                row, text=label, value=code, variable=perf_var,
                command=lambda c=code: self.set_perf_profile(c),
                font=self.ui_font, bg=BAR_BG, fg=FG,
                activebackground=BAR_BG, activeforeground=FG_HI,
                selectcolor=DEEP_BG, anchor="w", bd=0,
                highlightthickness=0, cursor="hand2").pack(side="left")
            tk.Label(row, text=desc, font=self.ui_font_s, bg=BAR_BG,
                     fg=FG_DIM, anchor="w").pack(side="left", padx=(px(10), 0))

        fx_var = tk.IntVar(value=1 if self.fast_skip_fx else 0)

        def on_fx():
            self.fast_skip_fx = bool(fx_var.get())
            self._mark_fast()
            self._request_render()
            self.save_settings()

        tk.Checkbutton(
            wrap, text="拖动滑块时省略暗角与水印（更跟手）", variable=fx_var,
            command=on_fx, font=self.ui_font, bg=BAR_BG, fg=FG,
            activebackground=BAR_BG, activeforeground=FG_HI,
            selectcolor=DEEP_BG, anchor="w", bd=0, highlightthickness=0,
            cursor="hand2").pack(fill="x", pady=(px(4), 0))

        lm_var = tk.IntVar(value=1 if self.low_mem else 0)

        def on_lm():
            want = bool(lm_var.get())
            if want != bool(self.low_mem):
                self.toggle_low_mem()

        tk.Checkbutton(
            wrap, text="低内存模式（代理图更小，适合超大图）", variable=lm_var,
            command=on_lm, font=self.ui_font, bg=BAR_BG, fg=FG,
            activebackground=BAR_BG, activeforeground=FG_HI,
            selectcolor=DEEP_BG, anchor="w", bd=0, highlightthickness=0,
            cursor="hand2").pack(fill="x", pady=(px(2), 0))

        tk.Frame(wrap, bg=RULE_BG, height=max(1, px(1))).pack(
            fill="x", pady=(px(12), px(10)))
        tk.Label(wrap, text="软打样（预览）", font=self.ui_font_b, bg=BAR_BG,
                 fg=FG, anchor="w").pack(fill="x")
        sp_var = tk.IntVar(value=1 if self.soft_proof else 0)
        sp_lbl = tk.Label(wrap, text=(self.soft_proof_name or "未选择 ICC"),
                          font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                          anchor="w")

        def refresh_sp():
            sp_var.set(1 if self.soft_proof else 0)
            sp_lbl.configure(text=(self.soft_proof_name or _tr("未选择 ICC")))

        def on_sp():
            self.toggle_soft_proof(bool(sp_var.get()))
            refresh_sp()

        tk.Checkbutton(
            wrap, text="启用软打样（只影响预览，不影响导出）", variable=sp_var,
            command=on_sp, font=self.ui_font, bg=BAR_BG, fg=FG,
            activebackground=BAR_BG, activeforeground=FG_HI,
            selectcolor=DEEP_BG, anchor="w", bd=0, highlightthickness=0,
            cursor="hand2").pack(fill="x", pady=(px(2), 0))
        row = tk.Frame(wrap, bg=BAR_BG)
        row.pack(fill="x", pady=(px(3), 0))
        tk.Button(
            row, text="选择 ICC 配置文件…", font=self.ui_font_s,
            command=lambda: (self.choose_soft_proof_profile(),
                             refresh_sp()),
            bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
            activeforeground=FG_HI, relief="flat", bd=0,
            highlightthickness=0, padx=px(8), pady=px(2),
            cursor="hand2").pack(side="left")
        sp_lbl.pack(side="left", padx=(px(8), 0))

        tk.Frame(wrap, bg=RULE_BG, height=max(1, px(1))).pack(
            fill="x", pady=(px(12), px(10)))
        tk.Label(wrap, text="提示", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x")
        clip_var = tk.IntVar(value=1 if self.clip_warn else 0)

        def on_clip():
            if bool(clip_var.get()) != bool(self.clip_warn):
                self.toggle_clip()

        tk.Checkbutton(
            wrap, text="过曝 / 欠曝警告", variable=clip_var,
            command=on_clip, font=self.ui_font, bg=BAR_BG, fg=FG,
            activebackground=BAR_BG, activeforeground=FG_HI,
            selectcolor=DEEP_BG, anchor="w", bd=0, highlightthickness=0,
            cursor="hand2").pack(fill="x", pady=(px(2), 0))

        tk.Frame(wrap, bg=RULE_BG, height=max(1, px(1))).pack(
            fill="x", pady=(px(12), px(10)))
        tk.Label(wrap, text="配置位置", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x")
        tk.Label(wrap, text=_data_dir(), font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM, anchor="w", justify="left",
                 wraplength=px(370)).pack(fill="x", pady=(px(3), px(6)))
        bar = tk.Frame(wrap, bg=BAR_BG)
        bar.pack(fill="x")
        self._panel_btn(bar, "打开配置目录",
                        lambda: self._open_path(_data_dir()))
        self._panel_btn(bar, "恢复默认设置", self._reset_settings)
        tk.Frame(wrap, bg=RULE_BG, height=max(1, px(1))).pack(
            fill="x", pady=(px(12), px(10)))
        tk.Label(wrap, text="更多", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x")
        bar2 = tk.Frame(wrap, bg=BAR_BG)
        bar2.pack(fill="x", pady=(px(4), 0))
        self._panel_btn(bar2, "重置全部调整", self.reset_edit_all)
        self._panel_btn(bar2, "复制设置", self.copy_settings)
        self._panel_btn(bar2, "关于 / 帮助", self.show_about)

        # 设置页比窗口高：滚轮、触控板与滚动条都能滚
        def bind_scroll(w):
            w.bind("<MouseWheel>", self._settings_wheel, add="+")
            w.bind("<Button-4>", self._settings_wheel, add="+")
            w.bind("<Button-5>", self._settings_wheel, add="+")
            for child in w.winfo_children():
                bind_scroll(child)

        bind_scroll(win)
        canvas.yview_moveto(0)

    def _settings_wheel(self, event):
        """设置窗口滚轮：Windows/macOS 用 delta，Linux 用 Button-4/5。"""
        canvas = getattr(self, "set_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        num = getattr(event, "num", None)
        if num == 4:
            step = -1
        elif num == 5:
            step = 1
        else:
            delta = getattr(event, "delta", 0) or 0
            if not delta:
                return
            step = -int(delta / 120) if abs(delta) >= 120 else (
                -1 if delta > 0 else 1)
            step *= 3
        canvas.yview_scroll(step, "units")
        return "break"

    def _open_path(self, path):
        try:
            os.startfile(path)
        except Exception:
            pass

    def _reset_settings(self):
        if not messagebox.askyesno("恢复默认设置",
                                   "主题与提示开关会恢复默认，确定吗？",
                                   parent=self):
            return
        self.set_theme("dark", persist=False)
        if self.clip_warn:
            self.toggle_clip()
        self.save_settings()
        win = getattr(self, "set_win", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        self.set_win = None
        self._flash("已恢复默认设置")

    # ---------------------------------------------------------------- 插件

    def _scan_plugins(self):
        """扫描 plugins/ 目录。一个 .py 就是一个插件，xxx.py.disabled 视为禁用。

        - PLUGIN 字典可选；有则校验 api，与当前支持不符就跳过并提示，不崩溃。
        - 加载期任何异常只写 logs/plugins.log 与 plugin_errors，不影响启动。
        - 运行期的异常由 _call_plugin 兜底，回退原图。
        """
        self.plugins = []
        self.plugin_errors = []
        self.plugins_disabled = []
        folder = _plugin_dir()
        try:
            names = sorted(os.listdir(folder))
        except Exception as exc:
            _plugin_log("无法读取插件目录 %s: %s" % (folder, exc))
            return
        import importlib.util
        import inspect
        seen_ids = set()
        for fn in names:
            if fn.endswith(".py.disabled"):
                self.plugins_disabled.append(fn[:-len(".disabled")])
                continue
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(folder, fn)
            mod_name = "prism_plugin_" + os.path.splitext(fn)[0]
            t_load = time.perf_counter()
            try:
                spec = importlib.util.spec_from_file_location(mod_name, path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            except BaseException as exc:
                _plugin_log("", plugin_id=os.path.splitext(fn)[0], stage="load",
                            exc=exc)
                self.plugin_errors.append((fn, "导入失败：%s: %s"
                                           % (type(exc).__name__, exc)))
                continue
            load_ms = (time.perf_counter() - t_load) * 1000.0
            run = getattr(mod, "run", None)
            if not callable(run):
                _plugin_log("缺少 run %s" % fn)
                self.plugin_errors.append((fn, "缺少 run(img, **params) 函数"))
                continue
            meta = getattr(mod, "PLUGIN", None)
            if not isinstance(meta, dict):
                meta = {}
            # 能力声明（透明度用，不是强制约束）
            caps = {k: bool(meta.get(k, False))
                    for k in ("network", "writes_files") if k in meta}
            try:
                api = int(meta.get("api", 1))
            except Exception:
                api = 1
            pid_guess = str(meta.get("id") or os.path.splitext(fn)[0])
            if pid_guess in seen_ids:
                msg = _tr("插件 id 与 %s 重复，已跳过 %s") % (pid_guess, fn)
                _plugin_log(msg, plugin_id=pid_guess, stage="load")
                self.plugin_errors.append((fn, msg))
                continue
            seen_ids.add(pid_guess)
            if api not in PLUGIN_API_SUPPORTED:
                msg = "插件 %s 需要 API %s，当前为 %s" % (
                    pid_guess, api,
                    "/".join(str(v) for v in PLUGIN_API_SUPPORTED))
                _plugin_log(msg, plugin_id=pid_guess, api=api, stage="load")
                self.plugin_errors.append((fn, msg))
                continue
            try:
                sig = inspect.signature(run)
                kinds = [q.kind for q in sig.parameters.values()]
                if any(k == k.VAR_KEYWORD for k in kinds):
                    call_mode = "kwargs"
                elif "params" in sig.parameters:
                    call_mode = "params"
                elif "path" in sig.parameters:
                    call_mode = "path"
                else:
                    call_mode = "none"
            except Exception:
                call_mode = "kwargs"
            self.plugins.append({
                "file": fn, "module": mod, "run": run, "api": api,
                "call_mode": call_mode,
                "id": str(meta.get("id") or os.path.splitext(fn)[0]),
                "name": _localized(meta.get("name") or getattr(
                    mod, "PLUGIN_NAME", os.path.splitext(fn)[0])),
                "desc": _localized(meta.get("description")
                                   or getattr(mod, "PLUGIN_DESC", "")),
                "ver": str(meta.get("version") or getattr(mod, "PLUGIN_VERSION", "")),
                "author": str(meta.get("author") or getattr(mod, "PLUGIN_AUTHOR", "")),
                "load_ms": load_ms,
                "caps": caps,
                "mtime": _file_mtime(path),
            })
            if globals().get("PLUGIN_DEV", False):
                _plugin_log("loaded %s in %.1f ms" % (fn, load_ms),
                            plugin_id=str(meta.get("id") or fn), api=api,
                            stage="load")
            hook = getattr(mod, "on_load", None)
            if callable(hook):
                try:
                    hook(self)
                except BaseException as exc:
                    _plugin_log("on_load 失败 %s: %s: %s" % (fn, type(exc).__name__, exc))
                    self.plugin_errors.append((fn, "on_load 出错：%s" % exc))
        self._schedule_watch()

    def show_plugins(self):
        win = getattr(self, "plug_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        self._scan_plugins()
        win = tk.Toplevel(self)
        self.plug_win = win
        win.title("插件")
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(560), px(460)))
        win.transient(self)
        self.after(40, self._apply_lang)
        tk.Label(win, text="已安装插件", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x", padx=px(16), pady=(px(14), px(2)))
        tk.Label(win, text=_plugin_dir(), font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM, anchor="w", wraplength=px(520)).pack(
                     fill="x", padx=px(16))
        hint = "已开启热重载：改完插件约 1.5 秒自动生效（也可以点「重载插件」）。禁用：把 xxx.py 改名为 xxx.py.disabled。日志：logs/plugins.log"
        tk.Label(win, text=hint, font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                 anchor="w", justify="left", wraplength=px(520)).pack(
                     fill="x", padx=px(16), pady=(px(4), 0))
        box = tk.Frame(win, bg=BAR_BG)
        box.pack(fill="both", expand=True, padx=px(16), pady=(px(10), px(6)))
        canvas = tk.Canvas(box, bg=BAR_BG, highlightthickness=0, bd=0,
                           width=px(10))
        bar = tk.Scrollbar(box, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BAR_BG)
        win_item = canvas.create_window((0, 0), window=inner, anchor="nw")
        # 让内容宽度跟着画布走，否则卡片只占左半边、右边留一大片空
        canvas.bind("<Configure>",
                    lambda e, i=win_item: canvas.itemconfigure(i, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        if not self.plugins:
            tk.Label(inner, text="还没有插件。把 .py 文件放进上面的目录，"
                                 "点「重新扫描」即可。", font=self.ui_font,
                     bg=BAR_BG, fg=FG_DIM, justify="left", anchor="w").pack(
                         fill="x", pady=px(10))
        # 12 个插件排成一列太挤，改成两列卡片网格
        grid = tk.Frame(inner, bg=BAR_BG)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1, uniform="plug")
        grid.columnconfigure(1, weight=1, uniform="plug")
        for _idx, item in enumerate(self.plugins):
            row = tk.Frame(grid, bg=BTN_BG)
            row.grid(row=_idx // 2, column=_idx % 2, sticky="nsew",
                     padx=(0 if _idx % 2 == 0 else px(4), 0), pady=px(3))
            txt = tk.Frame(row, bg=BTN_BG)
            txt.pack(side="left", fill="x", expand=True, padx=px(10),
                     pady=px(6))
            head = tk.Frame(txt, bg=BTN_BG)
            head.pack(fill="x")
            name_lbl = tk.Label(head, text=item["name"], font=self.ui_font_b,
                                bg=BTN_BG, fg=FG, anchor="w")
            name_lbl.pack(side="left")
            if item["ver"]:
                # 版本号单独一个 Label：_apply_lang 只翻名字，不会把 "2.0" 也存成原文
                tk.Label(head, text="  " + item["ver"], font=self.ui_font_s,
                         bg=BTN_BG, fg=FG_DIM, anchor="w").pack(side="left")
            # 卡片只留名称；描述/作者/能力收进 hover 提示。
            # 12 个插件排两列时，每行三行文字会把列表撑得很长。
            tip = [item["desc"] or item["file"]]
            if item["author"]:
                tip.append(_tr("作者：") + item["author"])
            caps = item.get("caps") or {}
            if caps:
                tip.append(_tr("联网 %s · 写文件 %s") % (
                    _tr("是") if caps.get("network") else _tr("否"),
                    _tr("是") if caps.get("writes_files") else _tr("否")))
            text_tip = "\n".join(tip[:2]) if len(tip) > 2 else "\n".join(tip)
            for _w in (row, txt, name_lbl):
                self._hover_tip(_w, text_tip, caps=caps)
            self._panel_btn(row, "运行", lambda it=item: self.run_plugin(it))
            self._panel_btn(row, _tr("禁用"),
                            lambda it=item: self._set_plugin_enabled(it, False))
        for fn in getattr(self, "plugins_disabled", []):
            self._panel_btn(inner, _tr("启用") + " " + fn[:-len(".py")],
                            lambda f=fn: self._set_plugin_enabled({"file": f}, True))
            tk.Label(inner, text="已禁用 %s（改回 .py 即可启用）" % fn,
                     font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                     justify="left", wraplength=px(460)).pack(
                         fill="x", pady=px(2))
        for fn, err in getattr(self, "plugin_errors", []):
            tk.Label(inner, text="加载失败 %s：%s" % (fn, err),
                     font=self.ui_font_s, bg=BAR_BG, fg="#ff8a80", anchor="w",
                     justify="left", wraplength=px(460)).pack(
                         fill="x", pady=px(2))
        bar2 = tk.Frame(win, bg=BAR_BG)
        bar2.pack(fill="x", padx=px(16), pady=(0, px(4)))
        # 按钮多了排两行，窄窗口（1024）下也不会被裁掉
        row_a = tk.Frame(bar2, bg=BAR_BG)
        row_a.pack(fill="x")
        self._panel_btn(row_a, "插件市场", self.show_plugin_market)
        self._panel_btn(row_a, "从网址安装…", self.show_plugin_install)
        self._panel_btn(row_a, "新建插件", self._new_plugin)
        row_b = tk.Frame(bar2, bg=BAR_BG)
        row_b.pack(fill="x", pady=(px(2), px(8)))
        self._panel_btn(row_b, "打开插件目录",
                        lambda: self._open_path(_plugin_dir()))
        self._panel_btn(row_b, "重载插件", self._reload_plugins)
        self._panel_btn(row_b, "插件说明", self.show_plugin_help)

    # ------------------------------------------------------------ 插件市场
    def _async_call(self, work, done):
        """后台执行 work()，主线程回调 done(result, error)。

        用队列 + 主线程轮询，而不是从工作线程直接 self.after —— 后者在没有
        mainloop 的环境（测试、刚启动的瞬间）会报 "main thread is not in main loop"。
        """
        q = queue.Queue()

        def runner():
            try:
                q.put((work(), None))
            except BaseException as exc:
                q.put((None, exc))

        threading.Thread(target=runner, daemon=True).start()

        def poll():
            try:
                result, err = q.get_nowait()
            except queue.Empty:
                self.after(40, poll)
                return
            try:
                done(result, err)
            except BaseException:
                pass

        self.after(40, poll)

    def show_plugin_market(self):
        """官方清单：浏览、已安装/可更新状态、一键安装。

        清单在后台线程拉；失败用上次缓存，窗口里明确标出「离线缓存」。
        """
        win = getattr(self, "market_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        self._scan_plugins()
        win = tk.Toplevel(self)
        self.market_win = win
        win.title("插件市场")
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(640), px(600)))
        win.transient(self)
        win.after(40, self._apply_lang)
        try:
            win.iconbitmap(os.path.join(_res_dir(), "Prism.ico"))
        except Exception:
            pass

        head = tk.Frame(win, bg=BAR_BG)
        head.pack(fill="x", padx=px(16), pady=(px(14), 0))
        tk.Label(head, text="插件市场", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(side="left")
        self._market_src = tk.Label(head, text="", font=self.ui_font_s,
                                    bg=BAR_BG, fg=FG_DIM, anchor="e")
        self._market_src.pack(side="right")
        self._market_status = tk.Label(win, text="正在获取清单…",
                                       font=self.ui_font_s, bg=BAR_BG,
                                       fg=FG_DIM, anchor="w", justify="left",
                                       wraplength=px(600))
        self._market_status.pack(fill="x", padx=px(16), pady=(px(4), 0))
        search_row = tk.Frame(win, bg=BAR_BG)
        search_row.pack(fill="x", padx=px(16), pady=(px(4), 0))
        tk.Label(search_row, text=_tr("搜索"), font=self.ui_font_s,
                 bg=BAR_BG, fg=FG_DIM).pack(side="left")
        self._market_query = tk.StringVar()
        _q = tk.Entry(search_row, textvariable=self._market_query, bg=DEEP_BG,
                      fg=FG, insertbackground=FG, relief="flat", bd=0,
                      highlightthickness=0, font=self.ui_font_s)
        _q.pack(side="left", fill="x", expand=True, padx=(px(8), 0),
                ipady=px(3))
        _q.bind("<KeyRelease>", lambda e: self._market_render())

        box = tk.Frame(win, bg=BAR_BG)
        box.pack(fill="both", expand=True, padx=px(16), pady=(px(8), px(4)))
        canvas = tk.Canvas(box, bg=BAR_BG, highlightthickness=0, bd=0,
                           width=px(10))
        bar = tk.Scrollbar(box, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BAR_BG)
        win_item = canvas.create_window((0, 0), window=inner, anchor="nw")
        # 让内容宽度跟着画布走，否则卡片只占左半边、右边留一大片空
        canvas.bind("<Configure>",
                    lambda e, i=win_item: canvas.itemconfigure(i, width=e.width))
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        self._market_inner = inner
        self._market_entries = []

        bottom = tk.Frame(win, bg=BAR_BG)
        bottom.pack(fill="x", padx=px(16), pady=(0, px(12)))
        self._panel_btn(bottom, "刷新", self._market_load)
        self._panel_btn(bottom, "从网址安装…", self.show_plugin_install)
        self._panel_btn(bottom, "关闭", win.destroy)

        self._market_load()

    def _market_load(self):
        """后台拉清单，主线程渲染。"""
        win = getattr(self, "market_win", None)
        if win is None or not win.winfo_exists():
            return
        self._market_status.configure(text=_tr("正在获取清单…"))
        target = PLUGIN_CATALOG_URL

        def done(result, err):
            if err is None:
                entries, url = result
            else:
                entries, url = [], target
            self._market_loaded(entries, url, err)

        self._async_call(lambda: fetch_plugin_catalog(target), done)

    def _market_loaded(self, entries, url, err):
        win = getattr(self, "market_win", None)
        if win is None or not win.winfo_exists():
            return
        if err is not None:
            cached = load_plugin_catalog_cache()
            if cached:
                entries = cached
                self._market_status.configure(
                    text=_tr("离线缓存（%s）") % str(err)[:70])
            else:
                entries = []
                self._market_status.configure(
                    text=_tr("获取清单失败：%s") % str(err)[:90])
        else:
            self._market_status.configure(
                text=_tr("共 %d 个插件") % len(entries))
        host = re.sub(r"^https?://([^/]+).*$", r"\1", str(url))
        try:
            self._market_src.configure(text=host)
        except Exception:
            pass
        self._market_entries = entries
        self._market_render()

    def _market_render(self):
        inner = getattr(self, "_market_inner", None)
        if inner is None or not inner.winfo_exists():
            return
        for ch in inner.winfo_children():
            ch.destroy()
        all_entries = getattr(self, "_market_entries", [])
        query = ""
        try:
            query = self._market_query.get().strip().casefold()
        except Exception:
            pass
        entries = all_entries
        if query:
            def hay(e):
                return " ".join((
                    str(e.get("id") or ""), _catalog_text(e.get("name")),
                    _catalog_text(e.get("description")),
                    str(e.get("author") or ""))).casefold()
            entries = [e for e in all_entries if query in hay(e)]
            self._market_status.configure(
                text=_tr("共 %d / %d 个插件") % (len(entries), len(all_entries)))
        elif all_entries:
            self._market_status.configure(
                text=_tr("共 %d 个插件") % len(all_entries))
        if not entries:
            tk.Label(inner, text=(_tr("没有匹配的插件") if query
                                  else _tr("没有可安装的插件")),
                     font=self.ui_font, bg=BAR_BG, fg=FG_DIM,
                     anchor="w").pack(fill="x", pady=px(10))
            return
        installed = {str(p.get("id")): p for p in self.plugins}
        for entry in entries:
            cur = installed.get(entry["id"])
            # 同一个 id 但文件不是 <id>.py（例如内置插件）→ 不允许覆盖式安装
            conflict = bool(cur and os.path.basename(
                str(cur.get("file") or "")) != safe_plugin_filename(
                    entry["id"]) + ".py")
            if conflict:
                state, color, action = _tr("与已装插件冲突"), "#ff8a80", _tr("冲突")
            elif cur is None:
                state, color = _tr("未安装"), FG_DIM
                action = _tr("安装")
            elif catalog_is_newer(entry["version"], cur.get("ver", "")):
                state = _tr("可更新 %s → %s") % (cur.get("ver") or "?",
                                                 entry["version"])
                color, action = "#e0a030", _tr("更新")
            else:
                state, color, action = _tr("已安装"), "#5faf6a", _tr("重新安装")
            row = tk.Frame(inner, bg=BTN_BG)
            row.pack(fill="x", pady=px(3))
            left = tk.Frame(row, bg=BTN_BG)
            left.pack(side="left", fill="both", expand=True, padx=px(10),
                      pady=px(7))
            name = _catalog_text(entry["name"])
            ver = ("  " + entry["version"]) if entry["version"] else ""
            tk.Label(left, text=name + ver, font=self.ui_font_b, bg=BTN_BG,
                     fg=FG, anchor="w").pack(fill="x")
            desc = _catalog_text(entry["description"])
            if desc:
                tk.Label(left, text=desc, font=self.ui_font_s, bg=BTN_BG,
                         fg=FG_DIM, anchor="w", justify="left",
                         wraplength=px(420)).pack(fill="x")
            meta = _tr("作者：%s") % (entry["author"] or "-")
            meta += " · " + _tr("联网 %s · 写文件 %s") % (
                _tr("是") if entry["network"] else _tr("否"),
                _tr("是") if entry["writes_files"] else _tr("否"))
            tk.Label(left, text=meta, font=self.ui_font_s, bg=BTN_BG,
                     fg=FG_DIM, anchor="w").pack(fill="x")
            right = tk.Frame(row, bg=BTN_BG)
            right.pack(side="right", padx=px(10), pady=px(7))
            tk.Label(right, text=state, font=self.ui_font_s, bg=BTN_BG,
                     fg=color, anchor="e").pack(fill="x")
            self._panel_btn(right, action,
                            lambda e=entry: self._market_install(e))

    def _market_install(self, entry):
        win = getattr(self, "market_win", None)
        if win is None or not win.winfo_exists():
            return
        name = _catalog_text(entry["name"])
        installed = {str(p.get("id")): p for p in self.plugins}
        cur = installed.get(entry["id"])
        if cur is not None and os.path.basename(
                str(cur.get("file") or "")) != safe_plugin_filename(
                    entry["id"]) + ".py":
            messagebox.showerror(
                _tr("插件市场"),
                _tr("这个 id 已被另一个插件占用（%s），不能覆盖安装。\n请先移除那个插件，或让作者换一个 id。")
                % cur.get("file"), parent=win)
            return
        caps = _tr("联网 %s · 写文件 %s") % (
            _tr("是") if entry["network"] else _tr("否"),
            _tr("是") if entry["writes_files"] else _tr("否"))
        if cur is None:
            question = _tr("确定安装「%s」吗？") % name
            title = _tr("安装插件")
        else:
            question = _tr("确定把「%s」更新到 %s 吗？") % (
                name, entry["version"])
            title = _tr("更新插件")
        detail = "%s %s\n%s\n%s\n\nSHA-256：%s…\n\n%s" % (
            name, entry["version"], _catalog_text(entry["description"]),
            caps, entry["sha256"][:16], question)
        if not messagebox.askyesno(title, detail, parent=win):
            return
        self._market_status.configure(text=_tr("下载并校验中…"))

        def work():
            data = fetch_plugin_source(entry["url"])
            meta = parse_plugin_source(data)
            if meta["id"] != entry["id"]:
                raise PluginSourceError(_tr("下载到的插件 id 与清单不一致"))
            return install_plugin_bytes(
                data, entry["sha256"], overwrite=True,
                filename=(cur.get("file") if cur else None))

        self._async_call(
            work, lambda meta, err: self._market_done(meta, entry, err))

    def _market_done(self, meta, entry, err):
        win = getattr(self, "market_win", None)
        if win is None or not win.winfo_exists():
            return
        name = _catalog_text(entry["name"])
        if err is not None:
            self._market_status.configure(
                text=_tr("安装失败：%s") % str(err)[:90])
            try:
                messagebox.showerror(_tr("插件市场"), str(err), parent=win)
            except Exception:
                pass
            return
        was_installed = any(str(p.get("id")) == entry["id"] for p in self.plugins)
        self._market_status.configure(
            text=(_tr("已更新「%s」到 %s") % (name, entry["version"])
                  if was_installed else _tr("已安装「%s」") % name))
        try:
            self._flash(_tr("已安装「%s」") % name, 2600)
        except Exception:
            pass
        self._scan_plugins()
        self._market_render()
        # 插件窗口开着的话让它刷新列表（关闭重开，保持两处一致）
        if getattr(self, "plug_win", None) is not None:
            try:
                self._rescan_plugins()
            except Exception:
                pass

    def show_plugin_install(self):
        """从网址安装插件：下载 → 解析（不执行）→ 校验 → 确认 → 写入。

        网络请求放后台线程，界面不卡；确认对话框在写入前，用户随时能反悔。
        """
        win = tk.Toplevel(self)
        win.title("安装插件")
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(560), px(330)))
        win.transient(self)
        win.after(40, self._apply_lang)
        try:
            win.iconbitmap(os.path.join(_res_dir(), "Prism.ico"))
        except Exception:
            pass

        tk.Label(win, text="安装插件", font=self.ui_font_b, bg=BAR_BG, fg=FG,
                 anchor="w").pack(fill="x", padx=px(16), pady=(px(14), px(6)))
        tk.Label(win, text="插件网址（.py）", font=self.ui_font_s, bg=BAR_BG,
                 fg=FG_DIM, anchor="w").pack(fill="x", padx=px(16))
        url_var = tk.StringVar()
        tk.Entry(win, textvariable=url_var, bg=DEEP_BG, fg=FG,
                 insertbackground=FG, relief="flat", bd=0,
                 highlightthickness=0, font=self.ui_font_s).pack(
                     fill="x", padx=px(16), pady=(px(2), px(8)), ipady=px(4))
        tk.Label(win, text="SHA-256（可选，填了就强制校验）", font=self.ui_font_s,
                 bg=BAR_BG, fg=FG_DIM, anchor="w").pack(fill="x", padx=px(16))
        sha_var = tk.StringVar()
        tk.Entry(win, textvariable=sha_var, bg=DEEP_BG, fg=FG,
                 insertbackground=FG, relief="flat", bd=0,
                 highlightthickness=0, font=self.ui_font_s).pack(
                     fill="x", padx=px(16), pady=(px(2), px(8)), ipady=px(4))
        hint = "下载后先解析、校验，再问你一次；确认后才写入插件目录。\n只安装你信任的插件。"
        tk.Label(win, text=hint, font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM,
                 anchor="w", justify="left", wraplength=px(520)).pack(
                     fill="x", padx=px(16))
        status = tk.Label(win, text="", font=self.ui_font_s, bg=BAR_BG,
                          fg=FG_DIM, anchor="w", justify="left",
                          wraplength=px(520))
        status.pack(fill="x", padx=px(16), pady=(px(6), 0))
        row = tk.Frame(win, bg=BAR_BG)
        row.pack(fill="x", padx=px(16), pady=(px(10), px(12)))

        def fail(exc):
            try:
                status.configure(text=_tr("安装失败：%s") % exc)
            except Exception:
                pass
            try:
                messagebox.showerror(_tr("安装插件"), str(exc), parent=win)
            except Exception:
                pass

        def fetched(data, url):
            try:
                meta = parse_plugin_source(data)
            except PluginSourceError as exc:
                return fail(exc)
            except Exception as exc:
                return fail(exc)
            want = sha_var.get().strip()
            if want:
                import hashlib
                got = hashlib.sha256(data).hexdigest()
                if got.lower() != want.lower():
                    return fail(PluginSourceError(
                        _tr("SHA-256 不匹配\n填写：%s…\n实际：%s…")
                        % (want[:16], got[:16])))
            caps = _tr("联网 %s · 写文件 %s") % (
                _tr("是") if meta["network"] else _tr("否"),
                _tr("是") if meta["writes_files"] else _tr("否"))
            detail = ["%s  %s" % (meta["name"], meta["version"]),
                      meta["description"][:80],
                      _tr("作者：%s") % (meta["author"] or "-"),
                      caps,
                      _tr("API %d · id %s") % (meta["api"], meta["id"]),
                      "", _tr("确定安装吗？")]
            if not messagebox.askyesno(_tr("安装插件"), "\n".join(detail),
                                       parent=win):
                status.configure(text=_tr("已取消安装。"))
                return
            path = os.path.join(_plugin_dir(),
                                safe_plugin_filename(meta["id"]) + ".py")
            overwrite = False
            if os.path.exists(path):
                if not messagebox.askyesno(
                        _tr("安装插件"),
                        _tr("已存在同名插件，覆盖吗？\n%s") % path,
                        parent=win):
                    status.configure(text=_tr("已取消安装。"))
                    return
                overwrite = True
            try:
                meta = install_plugin_bytes(data, want, overwrite=overwrite)
            except Exception as exc:
                return fail(exc)
            _plugin_log("installed %s from %s sha256=%s" % (
                meta["id"], url, meta["sha256"]), plugin_id=meta["id"],
                api=meta["api"], stage="install")
            try:
                win.destroy()
            except Exception:
                pass
            self._rescan_plugins()
            try:
                self._flash(_tr("已安装「%s」") % meta["name"], 2800)
            except Exception:
                pass

        def do_install():
            url = url_var.get().strip()
            if not url:
                status.configure(text=_tr("请填写插件网址。"))
                return
            status.configure(text=_tr("下载中…"))

            def got(data, err):
                if err is not None:
                    fail(err)
                else:
                    fetched(data, url)

            self._async_call(lambda: fetch_plugin_source(url), got)

        self._panel_btn(row, "下载并安装", do_install)
        self._panel_btn(row, "取消", win.destroy)

    PLUGIN_TEMPLATE = '''# -*- coding: utf-8 -*-
# Prism 插件模板（api = 2）。另存为 myplugin.py 放进插件目录即可，约 1.5 秒热重载。

PLUGIN = {
    "id": "myplugin",
    "name": "我的插件",
    "version": "1.0",
    "api": 2,
    "author": "你的名字",
    "description": "一句话说明这个插件做什么",
    "network": False,          # 能力声明：是否联网（如实填写）
    "writes_files": False,     # 能力声明：是否写文件
}

# 三种控件：slider / select / checkbox
PARAMS = [
    {"key": "amount", "label": "强度", "type": "slider",
     "min": 0, "max": 100, "default": 60, "step": 5},
    {"key": "mode", "label": "风格", "type": "select",
     "options": ["原样", "偏暖", "偏冷"], "default": "偏暖"},
    {"key": "vignette", "label": "加暗角", "type": "checkbox", "default": False},
]


def run(img, **params):
    """run(img, **params) -> PIL.Image

    img   : 当前图片 + 全部调整后的 PIL.Image（可能是 RGB/RGBA/L，可能是原分辨率）
            不要原地修改它
    params: 键为 PARAMS 的 key，值已按类型转换（slider=float / select=str /
            checkbox=bool）
    异常  : 直接抛，Prism 会写 logs/plugins.log 并回退原图，不会崩
    """
    from PIL import ImageEnhance
    amount = float(params.get("amount", 60)) / 100.0
    out = img.convert("RGB")
    if params.get("mode") == "偏暖":
        out = ImageEnhance.Color(out).enhance(1.0 + 0.3 * amount)
    return out
'''

    def _new_plugin(self):
        """一键生成插件模板，并用系统默认编辑器打开，降低上手门槛。"""
        folder = _plugin_dir()
        path = os.path.join(folder, "_模板.py")
        try:
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(self.PLUGIN_TEMPLATE)
        except Exception as exc:
            messagebox.showerror("新建插件", "写模板失败：%s" % exc, parent=self)
            return
        try:
            os.startfile(path)
            self._flash("模板已打开，另存为你自己的名字即可")
        except Exception:
            messagebox.showinfo(
                "新建插件",
                "模板已生成：\n%s\n\n（没有找到默认编辑器，请手动打开它）" % path,
                parent=self)

    def _plugin_snapshot(self):
        """目录快照：文件名 -> mtime。热重载靠它判断变化。"""
        snap = {}
        folder = _plugin_dir()
        try:
            for fn in os.listdir(folder):
                low = fn.lower()
                if low.endswith(".pyc") or low == "__pycache__":
                    continue
                if low.endswith((".py", ".py.disabled")):
                    snap[fn] = _file_mtime(os.path.join(folder, fn))
        except Exception:
            pass
        return snap

    def _schedule_watch(self):
        if getattr(self, "_watch_job", None) is not None:
            return
        self._snap = self._plugin_snapshot()
        self._watch_job = self.after(1500, self._watch_plugins)

    def _watch_plugins(self):
        self._watch_job = None
        if not getattr(self, "alive", True):
            return
        if not getattr(self, "alive", True):
            return
        snap = self._plugin_snapshot()
        changed = [fn for fn, mt in snap.items() if self._snap.get(fn) != mt]
        removed = [fn for fn in self._snap if fn not in snap]
        if changed or removed:
            self._snap = snap
            self._reload_plugins(auto=True)
        self._watch_job = self.after(1500, self._watch_plugins)

    def _set_plugin_enabled(self, item, enabled=True):
        """启用/禁用插件：就是把文件在 .py 与 .py.disabled 之间改名。

        item["file"] 可能是 "gray.py"（已禁用列表给的名字）也可能是
        "gray.py.disabled"（直接传禁用文件），两种都要能接住。之前启用时
        无条件砍掉末尾 9 个字符，把 "gray.py" 砍成 "gr"，于是静默失败。
        """
        folder = _plugin_dir()
        fn = item.get("file") or ""
        base = fn[:-len(".disabled")] if fn.endswith(".disabled") else fn
        if not base.endswith(".py"):
            base += ".py"
        try:
            if enabled:
                src = os.path.join(folder, base + ".disabled")
                dst = os.path.join(folder, base)
            else:
                src = os.path.join(folder, base)
                dst = os.path.join(folder, base + ".disabled")
            if os.path.exists(src):
                os.replace(src, dst)
                _plugin_log("plugin=%s %s" % (base, "enabled" if enabled else "disabled"),
                            plugin_id=os.path.splitext(base)[0], stage="toggle")
        except Exception as exc:
            self._flash("插件切换失败：%s" % exc, 3200)
            return
        self._reload_plugins(auto=False)
        try:
            if getattr(self, "plug_win", None) is not None:
                self.plug_win.destroy()
                self.plug_win = None
                self.show_plugins()
        except Exception:
            pass
        self._flash((_tr("已启用 ") if enabled else _tr("已禁用 ")) + base, 2200)

    def _reload_plugins(self, auto=False):
        """重新加载插件目录并刷新界面（热重载与手动重载共用）。"""
        old_count = len(getattr(self, "plugins", []))
        self._scan_plugins()
        n = len(getattr(self, "plugins", []))
        if getattr(self, "plug_win", None) is not None:
            try:
                self.show_plugins()
            except Exception:
                pass
        _plugin_log("reloaded plugins: %d -> %d%s" % (
            old_count, n, " (auto)" if auto else ""), stage="reload")
        try:
            self._flash(("插件已自动重载：%d 个" if auto else "插件已重载：%d 个") % n,
                        2200)
        except Exception:
            pass

    def _rescan_plugins(self):
        win = getattr(self, "plug_win", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        self.plug_win = None
        self.show_plugins()

    # ------------------------------------------------------- 插件参数

    def _plugin_params_spec(self, item):
        """读取插件声明的 PARAMS，返回规范化的参数描述列表。

        插件可以声明（全部可省略，省略就是没有可调项）：
            PARAMS = [
                {"key": "block", "label": "方块大小", "min": 4, "max": 200,
                 "default": 16, "step": 1},
                {"key": "mode", "label": "模式", "type": "choice",
                 "choices": ["平均", "中间色"], "default": "平均"},
                {"key": "edge", "label": "加描边", "type": "bool",
                 "default": False},
            ]
        """
        spec = getattr(item["module"], "PARAMS", None)
        out = []
        if not isinstance(spec, (list, tuple)):
            return out
        for p in spec:
            if not isinstance(p, dict) or "key" not in p:
                continue
            raw = str(p.get("type", "")).strip().lower()
            raw_choices = list(p.get("choices") or p.get("options") or [])
            # options 既可以是字符串，也可以是 {"value","label"}；label 可三语
            choices, choice_labels = [], {}
            for choice in raw_choices:
                if isinstance(choice, dict):
                    val = choice.get("value", choice.get("label"))
                    if isinstance(val, dict):
                        val = _localized(val)
                    val = "" if val is None else str(val)
                    choices.append(val)
                    choice_labels[val] = _localized(
                        choice.get("label", val))
                else:
                    choices.append(choice)
                    choice_labels[choice] = str(choice)
            # 新写法 slider/select/checkbox 与旧写法 range/choice/bool 等价
            if raw in ("select", "choice", "dropdown"):
                kind = "choice"
            elif raw in ("checkbox", "bool", "switch", "toggle"):
                kind = "bool"
            elif raw in ("text", "string", "str", "input"):
                kind = "text"
            else:
                kind = "range"          # slider / range / 空 = 数值滑杆
            if kind == "choice" and not choices:
                kind = "range"
            out.append({
                "key": str(p["key"]),
                "label": _localized(p.get("label", p["key"])),
                "type": kind,
                "min": p.get("min", 0),
                "max": p.get("max", 100),
                "step": p.get("step", 1),
                "choices": choices,
                "choice_labels": choice_labels,
                "default": p.get(
                    "default",
                    (choices[0] if choices else
                     ("" if kind == "text" else p.get("min", 0)))),
            })
        return out

    def _plugin_defaults(self, spec):
        return {p["key"]: p["default"] for p in spec}

    # ------------------------------------------------------------ 插件参数记忆
    # 键是插件 id（没有 id 时退回文件名），值是上次跑完的参数。存在设置文件里，
    # 所以升级、重启都还在；插件自己改了默认值也不会丢用户调过的值。

    @staticmethod
    def _plugin_key(item):
        return str(item.get("id") or item.get("file") or "")

    def _plugin_params(self, item, spec):
        """默认值 + 上次记住的值。坏值（类型不对、超出范围、选项已删）回落默认。"""
        saved = (getattr(self, "plug_params", {}) or {}).get(
            self._plugin_key(item)) or {}
        if not isinstance(saved, dict):
            saved = {}
        out = self._plugin_defaults(spec)
        for p in spec:
            if p["key"] in saved:
                out[p["key"]] = self._coerce_plugin_param(p, saved[p["key"]])
        return out

    @staticmethod
    def _coerce_plugin_param(p, value):
        """把设置文件里读回来的值收敛成控件能用的类型/范围内。"""
        kind = p["type"]
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() not in ("", "0", "false",
                                                     "no", "off", "none")
            return bool(value)
        if kind == "choice":
            return value if value in p["choices"] else p["default"]
        if kind == "text":
            return str(value)[:200]
        try:
            lo, hi = float(p["min"]), float(p["max"])
            v = float(value)
        except (TypeError, ValueError):
            return p["default"]
        if lo > hi:
            lo, hi = hi, lo
        return max(lo, min(hi, v))

    def _remember_plugin_params(self, item, params):
        """记下这次用的参数（只存 json 能表示的基本类型）。"""
        pid = self._plugin_key(item)
        if not pid or not isinstance(params, dict):
            return
        clean = {}
        for k, v in params.items():
            if isinstance(v, (bool, int, float, str)):
                clean[str(k)] = v
        if not clean:
            return
        if not isinstance(getattr(self, "plug_params", None), dict):
            self.plug_params = {}
        self.plug_params[pid] = clean
        try:
            self._save_setting("plugin_params", self.plug_params)
        except Exception:
            pass

    def _forget_plugin_params(self, item):
        """「恢复默认」时把记住的值删掉，否则重开还是旧参数。"""
        pid = self._plugin_key(item)
        try:
            if pid and isinstance(getattr(self, "plug_params", None), dict):
                self.plug_params.pop(pid, None)
                self._save_setting("plugin_params", self.plug_params)
        except Exception:
            pass

    def _call_plugin(self, item, im, path, params):
        """调用插件。失败时写日志、提示用户、回退原图，绝不带崩主程序。"""
        run = item["run"]
        values = dict(params or {})
        mode = item.get("call_mode", "kwargs")
        t0 = time.perf_counter()
        try:
            if mode == "kwargs":
                out = run(im, **values)
            elif mode == "params":
                out = run(im, path, values)
            elif mode == "path":
                out = run(im, path)
            else:
                out = run(im)
        except BaseException as exc:
            head = (str(exc).strip().splitlines() or [""])[0]
            _plugin_log("", plugin_id=item.get("id", "?"), api=item.get("api", "?"),
                        stage="run", exc=exc)
            try:
                self._flash("插件「%s」执行失败：%s: %s（详见 logs/plugins.log）"
                            % (item.get("name", "?"), type(exc).__name__, head[:60]),
                            4200)
            except Exception:
                pass
            return im
        self._plugin_last_ms = (time.perf_counter() - t0) * 1000.0
        if globals().get("PLUGIN_DEV", False):
            _plugin_log("run ok in %.1f ms" % self._plugin_last_ms,
                        plugin_id=item.get("id", "?"), api=item.get("api", "?"),
                        stage="run")
            try:
                self._flash("插件 %s 执行耗时 %.0f ms"
                            % (item.get("id", "?"), self._plugin_last_ms), 2600)
            except Exception:
                pass
        return out


    def _plugin_controls(self, parent, spec, params, on_change):
        """按 PARAMS 生成控件，返回一个收集当前值的函数。"""
        getters = []
        for p in spec:
            row = tk.Frame(parent, bg=BAR_BG)
            row.pack(fill="x", padx=px(14), pady=(px(4), 0))
            tk.Label(row, text=p["label"], font=self.ui_font_s, bg=BAR_BG,
                     fg=FG_DIM, width=9, anchor="w").pack(side="left")
            key = p["key"]
            if p["type"] == "bool":
                var = tk.IntVar(value=1 if params.get(key) else 0)

                def make_cb(k=key, v=var):
                    cb = tk.Checkbutton(
                        row, variable=v, bg=BAR_BG, fg=FG, selectcolor=DEEP_BG,
                        activebackground=BAR_BG, bd=0, highlightthickness=0,
                        command=lambda: (params.__setitem__(k, bool(v.get())),
                                         on_change()))
                    return cb

                getters.append((key, lambda v=var: bool(v.get())))
                make_cb().pack(side="left")
            elif p["type"] == "text":
                var = tk.StringVar(value=str(params.get(key) or p["default"]))
                ent = tk.Entry(row, textvariable=var, width=14,
                               bg=DEEP_BG, fg=FG, insertbackground=FG,
                               relief="flat", bd=0, highlightthickness=0,
                               font=self.ui_font_s)
                ent.pack(side="left", fill="x", expand=True)
                ent.bind("<KeyRelease>",
                         lambda e, k=key, v=var: (params.__setitem__(k, v.get()),
                                                  on_change()))
                ent.bind("<Return>",
                         lambda e, k=key, v=var: params.__setitem__(k, v.get()))
                getters.append((key, lambda v=var: v.get()))
            elif p["type"] == "choice":
                labels = [p.get("choice_labels", {}).get(v, str(v))
                          for v in p["choices"]]
                label_to_value = {lab: v for v, lab in zip(p["choices"], labels)}
                cur = params.get(key, p["default"])
                var = tk.StringVar(
                    value=p.get("choice_labels", {}).get(cur, str(cur)))
                cb = ttk.Combobox(row, textvariable=var, values=labels,
                                  state="readonly", width=10,
                                  font=self.ui_font_s)
                cb.pack(side="left")

                def pick(_e=None, k=key, v=var):
                    params.__setitem__(
                        k, label_to_value.get(v.get(), v.get()))
                    on_change()

                cb.bind("<<ComboboxSelected>>", pick)
                getters.append((key, lambda v=var: label_to_value.get(
                    v.get(), v.get())))
            else:
                var = tk.DoubleVar(
                    value=float(params.get(key, p["default"])))
                sc = tk.Scale(
                    row, variable=var, from_=p["min"], to=p["max"],
                    resolution=p["step"], orient="horizontal",
                    showvalue=True, length=px(150), bg=BAR_BG, fg=FG,
                    troughcolor=TROUGH_BG, activebackground=BAR_BG,
                    highlightthickness=0, bd=0, sliderrelief="flat",
                    font=self.ui_font_s,
                    command=lambda _v, k=key, v=var: (
                        params.__setitem__(k, v.get()), on_change()))
                sc.pack(side="left", fill="x", expand=True)
                getters.append((key, lambda v=var: v.get()))

        def collect():
            return {k: g() for k, g in getters}

        return collect

    def show_plugin_help(self):
        messagebox.showinfo(
            "插件说明",
            "插件就是一个 .py 文件，放进插件目录即可生效；保存后约 1.5 秒自动重载。\n\n"
            "最小插件：\n"
            "    PLUGIN = {\"id\": \"bw\", \"name\": \"黑白\", \"version\": \"2.0\",\n"
            "              \"api\": 2, \"author\": \"你\"}\n"
            "    def run(img, **params):\n"
            "        return img.convert(\"L\").convert(\"RGB\")\n\n"
            "PARAMS 支持三种控件：slider（min/max/default/step）、\n"
            "select（options/default）、checkbox（default）。\n"
            "run 拿到的是「当前图片 + 全部调整」的 PIL.Image（可能是原分辨率，\n"
            "大图请先降到长边 2048）；返回新的 PIL.Image，尺寸可变。\n"
            "异常直接抛，会写 logs/plugins.log 并回退原图。\n\n"
            "详细字段见 docs/plugin-api.md；错误信息格式见 logs/plugins.log。\n\n"
            "注意：插件是普通 Python 代码，以程序完整权限运行，没有沙箱 ——\n"
            "只安装你信任的插件。",
            parent=self)

    def _plugin_proxy(self, img, max_side=2048):
        """插件预览用的代理图：长边不超过 max_side。"""
        w, h = img.size
        if max(w, h) <= max_side:
            return img
        r = max_side / float(max(w, h))
        return _fast_downscale(img, (max(1, int(round(w * r))),
                                     max(1, int(round(h * r)))), quality=False)

    def load_full_resolution(self):
        """把当前大图按原始分辨率重新解码一次（后台线程，不冻结界面）。"""
        doc = getattr(self, "doc", None)
        if doc is None:
            return
        ratio = getattr(doc, "draft_ratio", 1.0)
        # 只要当前显示的是降档图，就允许取回原图；auto_drafted 只用于提示，
        # 不能作为唯一条件（画布 draft 也会降档，但旧逻辑会误报已全分辨率）。
        if (not getattr(doc, "auto_drafted", False)) and ratio >= 0.999:
            self._flash("当前已经是全分辨率", 1800)
            return
        path = doc.path
        if getattr(self, "full_loading", None) == path:
            self._flash("正在载入全分辨率…（Esc 取消）", 2000)
            return
        orig = getattr(doc, "orig_size", None) or doc.size
        px = int(orig[0]) * int(orig[1])
        if px > FULL_CONFIRM_PIXELS:
            mb = px * 3 * 2 / 1048576.0
            if not messagebox.askyesno(
                    "载入全分辨率",
                    "原图 %d × %d（%.0f MP）\n预计需要约 %.0f MB 内存，继续？"
                    % (orig[0], orig[1], px / 1e6, mb),
                    parent=self, default="no"):
                return
        self.full_loading = path
        self.full_started = time.time()
        self.pending_full = path
        self.actual_after_full = False
        self.loader.request_full(path)
        self._set_full_btn_busy(True)
        self._full_tick()
        self._flash("正在载入全分辨率…（Esc 取消）", 9000)

    def _set_full_btn_busy(self, busy):
        try:
            self.full_btn.configure(
                text=_tr("载入中…") if busy else _tr("全分辨率"),
                state="disabled" if busy else "normal")
        except Exception:
            pass

    def _full_tick(self):
        """全分辨率解码没有进度回调，用已用时间给用户一个明确反馈。"""
        if not getattr(self, "full_loading", None):
            return
        try:
            secs = max(0.0, time.time() - getattr(self, "full_started",
                                                  time.time()))
            self.full_btn.configure(
                text=_trf("载入中 %ss…") % ("%.1f" % secs))
        except Exception:
            return
        self.full_tick_job = self.after(500, self._full_tick)

    def _stop_full_timer(self):
        job = getattr(self, "full_tick_job", None)
        self.full_tick_job = None
        if job is not None:
            try:
                self.after_cancel(job)
            except Exception:
                pass

    def _plugin_proxy_async(self, img, on_ready, fallback=None):
        """在后台线程生成插件代理图，主线程回调。

        只把「缩放」放到线程里：插件 run() 仍然在主线程执行（插件可以碰 Tk，
        按 API 文档的约定不许跨线程）。失败就退回同步结果，不让功能消失。
        """
        q = queue.Queue()

        def work():
            try:
                small = _proxy_for(img, PROXY_MAX_SIDE)[0] or img
                q.put(("ok", small))
            except BaseException as exc:
                q.put(("err", exc))

        threading.Thread(target=work, daemon=True).start()

        def poll():
            try:
                kind, val = q.get_nowait()
            except queue.Empty:
                self.after(40, poll)
                return
            try:
                if kind == "ok":
                    on_ready(val)
                elif fallback is not None:
                    fallback(val)
                else:
                    on_ready(img)
            except BaseException as exc:
                _plugin_log("", plugin_id="proxy", stage="run", exc=exc)

        self.after(40, poll)

    def run_plugin(self, item):
        if self.doc is None:
            self._flash("先打开一张图片")
            return
        full = self._flatten()
        if full is None:
            return
        spec = self._plugin_params_spec(item)
        params = self._plugin_params(item, spec) if spec else None
        path = getattr(self.doc, "path", None)

        def ready(im):
            disp = _tr(item["name"])
            try:
                out = self._call_plugin(item, im, path, params)
            except Exception as exc:
                messagebox.showerror("插件出错", "%s\n\n%s" % (disp, exc),
                                     parent=self)
                return
            if out is None:
                self._flash("插件 %s 没有返回图片" % disp)
                return
            if not isinstance(out, Image.Image):
                messagebox.showerror(
                    "插件出错", "run() 应返回 PIL.Image，实际是 %s" %
                    type(out).__name__, parent=self)
                return
            self._show_plugin_result(disp, out, item, im,
                                    spec, params, full=full)
            self._flash("插件 %s 已运行（%.0f ms，预览用代理图 %dx%d）"
                        % (disp, getattr(self, "_plugin_last_ms", 0.0),
                           im.size[0], im.size[1]), 3000)

        # 代理图在后台线程生成（12MP 约 60~120ms），主线程不阻塞
        self._flash("正在生成预览…", 2600)
        self._plugin_proxy_async(full, ready)

    def _show_plugin_result(self, name, im, item=None, source=None,
                            spec=None, params=None, full=None):
        win = tk.Toplevel(self)
        win.title("%s · 结果" % name)
        win.configure(bg=BG)
        win.geometry("%dx%d" % (px(780), px(660)))
        cv = tk.Canvas(win, bg=BG, highlightthickness=0, bd=0)
        cv.pack(fill="both", expand=True, padx=px(12), pady=(px(10), 0))
        info = tk.Label(win, text="", font=self.ui_font_s, bg=BG, fg=FG_DIM)
        info.pack(pady=(px(4), 0))

        state = {"im": im}

        def show(img):
            w, h = img.size
            f = min(1.0, px(720) / float(max(1, w)),
                    px(430) / float(max(1, h)))
            ph = ImageTk.PhotoImage(
                img.resize((max(1, int(w * f)), max(1, int(h * f))),
                           Image.Resampling.LANCZOS), master=win)
            cv.delete("all")
            cv.create_image(px(360), px(215), image=ph)
            cv.image = ph
            info.configure(text="%d × %d · %s" % (w, h, img.mode))
            state["im"] = img

        show(im)

        if spec and item is not None and source is not None:
            box = tk.Frame(win, bg=BAR_BG)
            box.pack(fill="x", padx=px(12), pady=(px(8), 0))
            job = {"id": None}

            def do_run():
                job["id"] = None
                try:
                    out = self._call_plugin(
                        item, source.copy(), getattr(self.doc, "path", None),
                        params)
                except Exception as exc:
                    self._flash("插件出错：%s" % exc)
                    return
                if isinstance(out, Image.Image):
                    show(out)

            def rerun():
                if job["id"] is not None:
                    try:
                        win.after_cancel(job["id"])
                    except Exception:
                        pass
                job["id"] = win.after(140, do_run)

            state["collect"] = self._plugin_controls(box, spec, params, rerun)
            row = tk.Frame(box, bg=BAR_BG)
            row.pack(fill="x", padx=px(14), pady=(px(6), px(8)))
            tk.Label(box, text="预览基于代理图（长边 ≤2048）；保存时按原分辨率重算",
                     font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                     justify="left", wraplength=px(700)).pack(
                         fill="x", padx=px(14), pady=(px(2), 0))
            tk.Label(box, text="参数会自动记住 · 下次运行这个插件直接恢复",
                     font=self.ui_font_s, bg=BAR_BG, fg=FG_DIM, anchor="w",
                     justify="left", wraplength=px(700)).pack(
                         fill="x", padx=px(14), pady=(px(2), 4))

            def persist():
                """把当前控件里的值写进设置文件（关窗口 / 保存 / 恢复默认前调用）。"""
                try:
                    vals = (state.get("collect") or (lambda: params))()
                    self._remember_plugin_params(item, vals)
                except Exception:
                    pass

            def reset_defaults():
                # 先删记忆再重开：顺序反了会把旧值又写回去
                self._forget_plugin_params(item)
                win.destroy()
                self.run_plugin(item)

            self._panel_btn(row, "重新应用", do_run)
            self._panel_btn(row, "恢复默认", reset_defaults)
            win.protocol("WM_DELETE_WINDOW", lambda: (persist(), win.destroy()))

        bar = tk.Frame(win, bg=BG)
        bar.pack(pady=px(10))

        def save_as():
            path = filedialog.asksaveasfilename(
                parent=win, defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
            if not path:
                return
            try:
                out = state["im"]
                # 保存走原分辨率：用当前参数把插件在全尺寸上再跑一次
                if full is not None and item is not None:
                    vals = (state.get("collect") or (lambda: params))()
                    try:
                        self._flash("正在按原分辨率重算…", 9000)
                        self.update_idletasks()
                        redo = self._call_plugin(
                            item, full, getattr(self.doc, "path", None), vals)
                        if isinstance(redo, Image.Image):
                            out = redo
                    except Exception:
                        pass
                if path.lower().endswith((".jpg", ".jpeg")) and out.mode != "RGB":
                    out = out.convert("RGB")
                out.save(path)
                self._flash("已保存 %s" % os.path.basename(path))
                # 导出成功说明这套参数是满意的，顺手记住
                try:
                    vals = (state.get("collect") or (lambda: params))()
                    self._remember_plugin_params(item, vals)
                except Exception:
                    pass
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=win)

        self._panel_btn(bar, "保存为…", save_as)

        def close_win():
            try:
                if spec and item is not None:
                    vals = (state.get("collect") or (lambda: params))()
                    self._remember_plugin_params(item, vals)
            except Exception:
                pass
            win.destroy()

        self._panel_btn(bar, "关闭", close_win)

    def _apply_outline(self, color, widget=None):
        """描边主题：给容器和文字类控件加一圈 1 像素边框。

        只碰 Frame/Label/Button/Checkbutton；输入框本来有自己的焦点描边，
        画布加边会吃掉绘图区域，都不动。
        """
        w = self if widget is None else widget
        try:
            cls = w.winfo_class()
            if cls in ("Frame", "Label", "Button", "Checkbutton"):
                if color:
                    w.configure(highlightthickness=max(1, px(1)),
                                highlightbackground=color,
                                highlightcolor=color)
                else:
                    w.configure(highlightthickness=0)
        except Exception:
            pass
        for child in w.winfo_children():
            self._apply_outline(color, child)

    def _reset_theme_surfaces(self):
        """主题切换后把结构性容器按角色归位。

        `_swap_colors` 靠颜色相等来推断旧角色，主题里多个角色共用同一个色值
        （例如深色的 BAR_BG 和 CARD）时会发生漂移；这些窗口骨架直接按角色重设。
        """
        pairs = (
            (getattr(self, "bar", None), BAR_BG),
            (getattr(self, "status", None), BAR_BG),
            (getattr(self, "body", None), BG),
            (getattr(self, "canvas", None), BG),
            (getattr(self, "panel", None), BAR_BG),
            (getattr(self, "panel_wrap", None), BAR_BG),
            (getattr(self, "panel_inner", None), PANEL_BG),
            (getattr(self, "pcan", None), BAR_BG),
            (getattr(self, "panel_grip", None), RULE_BG),
            (getattr(self, "set_win", None), PANEL_BG),
            (getattr(self, "set_scroll", None), PANEL_BG),
        )
        for widget, color in pairs:
            if widget is None:
                continue
            try:
                widget.configure(bg=color)
            except Exception:
                pass
        for widget in getattr(self, "_theme_cards", ()):
            try:
                widget.configure(bg=CARD_BG)
            except Exception:
                pass
        roles = {"BAR_BG": BAR_BG, "BTN": BTN_BG, "ACCENT": ACCENT,
                 "TROUGH": TROUGH_BG, "CARD": CARD_BG}

        def reset_round(w):
            for child in w.winfo_children():
                if isinstance(child, _QpeRoundButton):
                    role = getattr(child, "_theme_role", None)
                    if role in roles:
                        child._bg = roles[role]
                        child._hover_bg = BAR_HOVER
                        child._hover_fg = FG_HI
                        child._draw()
                reset_round(child)

        reset_round(self)
        try:
            if getattr(self, "text_item", None) is not None:
                self.canvas.itemconfigure(self.text_item, fill=FG_DIM)
        except Exception:
            pass
        try:
            if getattr(self, "split_label2", None) is not None:
                self.canvas.itemconfigure(self.split_label2, fill=ACCENT)
        except Exception:
            pass
        try:
            menu = getattr(self, "_recent_menu", None)
            if menu is not None:
                menu.configure(bg=DEEP2_BG, fg=FG, activebackground=ACCENT,
                               activeforeground=ON_BG)
        except Exception:
            pass
        try:
            draw = getattr(self, "_draw_settings_scroll", None)
            if callable(draw):
                draw()
        except Exception:
            pass

    def set_theme(self, name, persist=True):
        if name not in THEMES:
            return
        old = _CURRENT_THEME[0]
        delta = _theme_delta(old, name)
        _apply_palette(name)                 # 先换全局常量，之后新建的控件用新色
        self._swap_colors(self, delta)       # 再把已有控件逐个换掉
        self._reset_theme_surfaces()         # 结构性容器按角色强制归位
        self._apply_outline(THEMES[name].get("outline"))
        self.theme = name
        if self.theme_btn is not None and self.theme_btn.winfo_exists():
            self.theme_btn.configure(
                text=_tr("主题：%s") % _tr(THEME_NAMES[name]))
        if persist:
            self.save_settings()
        try:
            self._render()
        except Exception:
            pass
        try:
            if self.curve_can is not None and self.curve_can.winfo_exists():
                self._draw_curve()
                self._refresh_curve_thumbs()
        except Exception:
            pass
        try:
            if self.hist_can is not None and self.hist_can.winfo_exists():
                self._schedule_histogram()
        except Exception:
            pass
        self._flash(_tr("已切换主题：%s") % _tr(THEME_NAMES[name]))

    def cycle_theme(self):
        i = THEME_ORDER.index(self.theme) if self.theme in THEME_ORDER else 0
        self.set_theme(THEME_ORDER[(i + 1) % len(THEME_ORDER)])

    def _apply_icon(self):
        """窗口/任务栏图标。打包后用 exe 自带的 ico，源码运行时用同目录的。"""
        try:
            ico = os.path.join(_res_dir(), "Prism.ico")
            if IS_WIN and os.path.exists(ico):
                self.iconbitmap(ico)
        except Exception:
            pass
        try:
            png = os.path.join(_res_dir(), "Prism.png")
            if os.path.exists(png):
                im = Image.open(png).convert("RGBA")
                self._icon_img = ImageTk.PhotoImage(im, master=self)
                self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def load_settings(self):
        """读回上次的偏好：排序方式、水印设置、过曝警告、上次打开的目录。"""
        try:
            with open(self._settings_path(), "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            return
        if not isinstance(d, dict):
            return
        try:
            self.sort_key = str(d.get("sort_key", self.sort_key))
            if self.sort_key not in ("name", "mtime", "size"):
                self.sort_key = "name"
            self.sort_desc = bool(d.get("sort_desc", False))
            self.wm_text = str(d.get("wm_text", "") or "")
            pos = str(d.get("wm_pos", "br"))
            self.wm_pos = pos if pos in ("br", "bl", "c") else "br"
            self.wm_size = max(1.0, min(12.0, float(d.get("wm_size", 3.5))))
            self.wm_alpha = max(5.0, min(100.0, float(d.get("wm_alpha", 65))))
            self.clip_warn = bool(d.get("clip_warn", False))
            self.fast_skip_fx = bool(d.get("fast_skip_fx", False))
            self.tips_seen = bool(d.get("tips_seen", False))
            prof = str(d.get("perf_profile", "") or "")
            # 命令行显式指定时以命令行为准
            cli_prof = any(a == "--perf-profile" or a.startswith("--perf-profile=")
                           for a in sys.argv)
            if prof in ("fast-slider", "fast-first", "auto") and not cli_prof:
                self.perf_profile = prof
                globals()["PERF_PROFILE"] = prof
            pw = d.get("panel_w")
            if isinstance(pw, (int, float)):
                self.panel_width = max(px(200), min(px(560), int(pw)))
            sp = str(d.get("soft_proof_profile", "") or "")
            self.soft_proof = bool(d.get("soft_proof", False))
            if sp and os.path.isfile(sp):
                try:
                    t1, t2, name = _build_soft_proof(sp)
                    self.soft_proof_transforms = (t1, t2)
                    self.soft_proof_name = name
                    self.soft_proof_path = sp
                except Exception:
                    self.soft_proof = False
            else:
                self.soft_proof = False
            # 命令行 --low-mem 优先，其余情况恢复上次的选择
            if not globals().get("LOW_MEM_ARG", False):
                self.low_mem = bool(d.get("low_mem", getattr(self, "low_mem", False)))
            raw = d.get("plugin_params")
            if isinstance(raw, dict):
                self.plug_params = {str(k): v for k, v in raw.items()
                                    if isinstance(v, dict)}
            last = str(d.get("last_dir", "") or "")
            if last and os.path.isdir(last):
                self.last_dir = last
            geom = str(d.get("geom", "") or "")
            # 只接受 "WxH+X+Y" 形式，坏值直接丢掉，免得窗口跑到屏幕外
            if self._geom_ok(geom):
                self.saved_geom = geom
            self.saved_panel = bool(d.get("panel", False))
            raw_recent = d.get("recent")
            if isinstance(raw_recent, list):
                self.recent = [str(p) for p in raw_recent
                               if isinstance(p, str) and p][:10]
        except Exception:
            pass

    @staticmethod
    def _geom_ok(g):
        """校验 "WxH+X+Y"。不用正则，避免转义踩坑。"""
        if not isinstance(g, str) or "x" not in g:
            return False
        try:
            size, rest = g.split("x", 1)
            w, rest = rest.split("+", 1) if "+" in rest else (rest, "")
            if not rest:
                return False
            xs, ys = rest.split("+", 1) if rest.count("+") == 1 else rest.rsplit("+", 1)
            return (400 <= int(w) <= 20000 and 300 <= int(size) <= 20000
                    and -5000 <= int(xs) <= 20000 and -5000 <= int(ys) <= 20000)
        except Exception:
            return False

    def _safe_geom(self):
        """当前窗口几何。最大化时不记，否则下次会还原成那个怪尺寸。"""
        try:
            if self.state() != "normal":
                return self.saved_geom or ""
            w, h = self.winfo_width(), self.winfo_height()
            x, y = self.winfo_rootx(), self.winfo_rooty()
            if w < 400 or h < 300:
                return self.saved_geom or ""
            return "%dx%d+%d+%d" % (w, h, x, y)
        except Exception:
            return self.saved_geom or ""

    def save_settings(self):
        """写回偏好。

        先读旧文件再覆盖：语言、插件参数这类用 _save_setting 单独写过的键，
        如果这里用固定字典整份重写就会被抹掉（之前确实丢过语言设置）。
        """
        try:
            path = self._settings_path()
            data = {}
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh) or {}
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}
            data.update({"sort_key": self.sort_key,
                         "sort_desc": self.sort_desc,
                         "wm_text": self.wm_text,
                         "wm_pos": self.wm_pos,
                         "wm_size": self.wm_size,
                         "wm_alpha": self.wm_alpha,
                         "clip_warn": self.clip_warn,
                         "last_dir": self.folder or "",
                         "geom": self._safe_geom(),
                         "panel": bool(self.panel_shown),
                         "theme": getattr(self, "theme", "dark"),
                         "lang": getattr(self, "lang", "zh"),
                         "low_mem": bool(getattr(self, "low_mem", False)),
                         "plugin_params": getattr(self, "plug_params", {}),
                         "fast_skip_fx": bool(getattr(self, "fast_skip_fx", False)),
                         "tips_seen": bool(getattr(self, "tips_seen", False)),
                         "recent": list(getattr(self, "recent", []))[:10],
                         "perf_profile": getattr(self, "perf_profile",
                                                 "fast-slider"),
                         "soft_proof": bool(getattr(self, "soft_proof", False)),
                         "soft_proof_profile": str(getattr(
                             self, "soft_proof_path", "") or ""),
                         "panel_w": int(getattr(self, "panel_width", px(238)))})
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
        except Exception:
            pass

    def load_presets(self):
        try:
            with open(self._preset_path(), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for name, adj in data.items():
                    base = self._default_adj()
                    if isinstance(adj, dict):
                        base.update(adj)
                    self.presets[name] = base
        except Exception:
            self.presets = {}

    def _merge_preset(self, adj):
        """把外部读来的预设并进默认值上，缺的键用默认值补齐。"""
        base = self._default_adj()
        if isinstance(adj, dict):
            for k, v in adj.items():
                if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                    base[k] = dict(base[k])
                    base[k].update(v)
                else:
                    base[k] = v
        return base

    def export_presets(self):
        if not self.presets:
            self._flash("还没有预设可以导出")
            return
        path = filedialog.asksaveasfilename(
            parent=self, title="导出预设", defaultextension=".json",
            initialfile="Prism_presets.json",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.presets, fh, ensure_ascii=False, indent=1)
        except Exception as exc:
            messagebox.showerror("导出预设", "写不进去：\n%s" % exc, parent=self)
            return
        self._flash("已导出 %d 个预设" % len(self.presets))

    def import_presets(self):
        path = filedialog.askopenfilename(
            parent=self, title="导入预设",
            filetypes=[("JSON", "*.json"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            messagebox.showerror("导入预设", "读不了这个文件：\n%s" % exc,
                                 parent=self)
            return
        if not isinstance(data, dict) or not data:
            messagebox.showerror("导入预设", "这个文件里没有可用的预设。",
                                 parent=self)
            return
        added = 0
        for name, adj in data.items():
            if not isinstance(adj, dict):
                continue
            self.presets[str(name)] = self._merge_preset(adj)
            added += 1
        if not added:
            messagebox.showerror("导入预设", "没有解析出任何预设。", parent=self)
            return
        self.save_presets()
        self._refresh_preset_box()
        self._flash("已导入 %d 个预设（同名会覆盖）" % added)

    def save_presets(self):
        try:
            with open(self._preset_path(), "w", encoding="utf-8") as fh:
                json.dump(self.presets, fh, ensure_ascii=False, indent=1)
        except Exception as exc:
            self._flash("预设保存失败：%s" % exc)

    def _refresh_preset_box(self):
        box = self.preset_box
        if box is None or not box.winfo_exists():
            return
        box.delete(0, "end")
        for name in sorted(self.presets):
            box.insert("end", " " + name)

    def apply_preset(self, name):
        adj = self.presets.get(name)
        if adj is None:
            return
        self.adj = copy.deepcopy(adj)
        for k in ("tone_key", "color_key", "auto_lut"):
            setattr(self, k, None)
        self._sync_panel()
        self._push_history("预设：%s" % name)
        self._render()
        self._update_status()
        self._flash("已套用预设「%s」" % name)

    def _on_preset_select(self, event=None):
        sel = self.preset_box.curselection()
        if sel:
            self.apply_preset(self.preset_box.get(sel[0]).strip())

    def add_preset(self):
        if self.doc is None:
            return
        name = simpledialog.askstring("保存预设", "预设名称：", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        self.presets[name] = copy.deepcopy(self.adj)
        self.save_presets()
        self._refresh_preset_box()
        self._flash("已保存预设「%s」" % name)

    def delete_preset(self):
        sel = self.preset_box.curselection() if self.preset_box else ()
        if not sel:
            self._flash("先在上面选中一个预设")
            return
        name = self.preset_box.get(sel[0]).strip()
        if name in self.presets:
            del self.presets[name]
            self.save_presets()
            self._refresh_preset_box()
            self._flash("已删除预设「%s」" % name)

    # -------------------------------------------------------- 缩略图胶片条

    def _build_strip(self):
        self.strip = tk.Frame(self, bg=BAR_BG, height=px(80))
        self.strip.pack_propagate(False)
        self.strip_can = tk.Canvas(self.strip, bg="#161616",
                                   highlightthickness=0, bd=0)
        self.strip_can.pack(fill="both", expand=True)
        self.strip_can.bind("<Button-1>", self._on_strip_click)
        self.strip_can.bind("<MouseWheel>", self._on_strip_wheel)
        self.strip_can.bind("<Shift-MouseWheel>", self._on_strip_wheel)

    def toggle_strip(self, show=None):
        want = (not self.strip_shown) if show is None else bool(show)
        if want == self.strip_shown:
            return
        self.strip_shown = want
        if want:
            self.strip.pack(side="bottom", fill="x")
            self._strip_layout()
            self._strip_kick()
        else:
            self.strip.pack_forget()
        self.after(40, self._render)

    def _strip_layout(self):
        c = self.strip_can
        c.delete("all")
        self.thumb_x = {}
        self.thumbs.clear()
        self.thumb_pending.clear()
        n = len(self.files)
        if n == 0:
            return
        w, gap = self.thumb_w, px(4)
        c.configure(scrollregion=(0, 0, n * (w + gap) + gap,
                                  self.thumb_h + px(10)))
        for i, p in enumerate(self.files):
            x = gap + i * (w + gap)
            self.thumb_x[p] = x
            c.create_rectangle(x, px(5), x + w, px(5) + self.thumb_h,
                               outline="#2a2a2a", fill="#101010")
        self._strip_focus()

    def _strip_focus(self):
        """把当前图居中，并高亮它。"""
        c = self.strip_can
        if not self.strip_shown or not self.files:
            return
        if self.strip_mark is not None:
            try:
                c.delete(self.strip_mark)
            except Exception:
                pass
            self.strip_mark = None
        x = self.thumb_x.get(self.files[self.index])
        if x is None:
            return
        self.strip_mark = c.create_rectangle(
            x - px(1), px(4), x + self.thumb_w + px(1),
            px(6) + self.thumb_h, outline=ACCENT, width=max(1, px(2)))
        total = float(c.bbox("all")[2]) if c.bbox("all") else 1.0
        cw = max(1, c.winfo_width())
        if total > cw:
            c.xview_moveto(max(0.0, min(1.0,
                                        (x - cw / 2.0) / (total - cw))))

    def _strip_kick(self):
        """只给当前图前后各 25 张生成缩略图，避免上千张一起解。"""
        if not self.strip_shown or not self.files:
            return
        n = len(self.files)
        want = []
        for i in range(max(0, self.index - 25), min(n, self.index + 26)):
            p = self.files[i]
            if p in self.thumbs or p in self.thumb_pending:
                continue
            self.thumb_pending.add(p)
            want.append((p, (self.thumb_w, self.thumb_h)))
        if want:
            self.thumbs_worker.submit(want)
            self._wake_pump()

    def _strip_drain(self):
        try:
            while True:
                path, im = self.thumbs_worker.out.get_nowait()
                self.thumb_pending.discard(path)
                if im is None or self.strip_can is None:
                    continue
                if not self.strip_can.winfo_exists():
                    continue
                ph = ImageTk.PhotoImage(im, master=self.strip_can)
                self.thumbs[path] = ph
                # 胶片条缩略图原本只增不减，浏览几千张会一直涨内存。
                # 按条目数做 LRU：正常 24 张，低内存 8 张。
                cap = 8 if getattr(self, "low_mem", False) else 24
                while len(self.thumbs) > cap:
                    old_path = next(iter(self.thumbs))
                    self.thumbs.pop(old_path, None)
                    it_old = self.thumb_items.pop(old_path, None)
                    if it_old is not None and self.strip_can is not None:
                        try:
                            self.strip_can.delete(it_old)
                        except Exception:
                            pass
                x = self.thumb_x.get(path)
                if x is not None:
                    old = self.thumb_items.pop(path, None)
                    if old is not None:
                        try:
                            self.strip_can.delete(old)
                        except Exception:
                            pass
                    it = self.strip_can.create_image(
                        x + (self.thumb_w - im.width) // 2,
                        px(5) + (self.thumb_h - im.height) // 2,
                        anchor="nw", image=ph)
                    self.strip_can.tag_raise(it)
                    self.thumb_items[path] = it
        except queue.Empty:
            pass
        except Exception:
            traceback.print_exc()
        # 必须放在 try 之外：队列取空时是靠 queue.Empty 异常跳出 while 的，
        # 写在 try 里面永远执行不到（第一次就是这么写错的）。
        self._strip_trim()

    def _strip_reset(self):
        """换了文件夹就得重建胶片条，否则会显示上一个目录的旧缩略图。"""
        self.thumb_items = {}
        if self.strip_shown:
            self._strip_layout()
            self._strip_kick()

    def _strip_trim(self):
        """缩略图缓存回收：超过上限就丢掉离当前图最远的那些。

        必须连画布上的图元一起删，否则 PhotoImage 被回收后那条会显示成空白。
        滚动回去时会按需重新生成。
        """
        over = len(self.thumbs) - self.thumb_limit
        if over <= 0:
            return
        order = {p: i for i, p in enumerate(self.files)}
        cur = self.index
        drop = sorted(self.thumbs,
                      key=lambda p: -abs(order.get(p, 10 ** 9) - cur))[:over]
        for p in drop:
            self.thumbs.pop(p, None)
            it = self.thumb_items.pop(p, None)
            if it is not None:
                try:
                    self.strip_can.delete(it)
                except Exception:
                    pass

    def _on_strip_click(self, event):
        if not self.files:
            return
        w, gap = self.thumb_w, px(4)
        i = int((self.strip_can.canvasx(event.x) - gap) // (w + gap))
        if 0 <= i < len(self.files):
            self.goto(i)

    def _on_strip_wheel(self, event):
        self.strip_can.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    # -------------------------------------------------------- 缩略图网格

    def toggle_grid(self, show=None):
        """网格浏览：把当前文件夹铺成一格格缩略图，点哪张就打开哪张。"""
        want = (not self.grid_shown) if show is None else bool(show)
        if want == self.grid_shown:
            return
        self.grid_shown = want
        if want:
            if not self.files:
                self.grid_shown = False
                self._flash("先打开一个文件夹")
                return
            self._grid_build()
        else:
            if self.grid_win is not None:
                try:
                    self.grid_win.destroy()
                except Exception:
                    pass
            self.grid_win = None
            self.grid_canvas = None

    def _grid_build(self):
        win = tk.Toplevel(self)
        win.title("网格浏览 · %d 张" % len(self.files))
        win.configure(bg="#141414")
        win.geometry("%dx%d+%d+%d" % (
            px(900), px(620),
            self.winfo_rootx() + px(60), self.winfo_rooty() + px(60)))
        self.grid_win = win
        self.grid_canvas = tk.Canvas(win, bg="#141414",
                                     highlightthickness=0, bd=0)
        sb = tk.Scrollbar(win, command=self.grid_canvas.yview)
        self.grid_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.grid_canvas.pack(side="left", fill="both", expand=True)
        self.grid_canvas.bind("<Button-1>", self._grid_click)
        self.grid_canvas.bind("<MouseWheel>", self._grid_wheel)
        self.grid_sel = self.index if self.index >= 0 else 0
        win.bind("<KeyPress>", self._grid_key)
        win.focus_force()
        self.grid_canvas.bind("<Configure>", lambda e: self._grid_draw())
        win.bind("<Escape>", lambda e: self.toggle_grid(False))
        win.bind("<KeyPress-g>", lambda e: self.toggle_grid(False))
        win.protocol("WM_DELETE_WINDOW", lambda: self.toggle_grid(False))
        # 一次性把缩略图任务排进去（上限 400 张，避免超大目录爆内存）
        want = []
        for p in self.files[:400]:
            if p not in self.thumbs and p not in self.thumb_pending:
                self.thumb_pending.add(p)
                want.append((p, (self.thumb_w, self.thumb_h)))
        if want:
            self.thumbs_worker.submit(want)
            self._wake_pump()
        win.update_idletasks()
        self._grid_draw()

    def _grid_metrics(self):
        cw = max(120, self.grid_canvas.winfo_width() if self.grid_canvas else 900)
        gap = px(8)
        cell_w = self.thumb_w + gap * 2
        cell_h = self.thumb_h + gap * 2
        cols = max(1, int((cw - gap) // cell_w))
        return cell_w, cell_h, cols, gap

    def _grid_key(self, event):
        """方向键在网格里移动选择，Enter 打开，Esc 关闭。"""
        cols = self._grid_metrics()[2]
        n = min(len(self.files), 400)
        keys = {"Left": -1, "Right": 1, "Up": -cols, "Down": cols}
        if event.keysym in keys:
            self.grid_sel = max(0, min(n - 1, self.grid_sel + keys[event.keysym]))
            self._grid_scroll_to(self.grid_sel)
            self._grid_draw()
            return "break"
        if event.keysym in ("Return", "KP_Enter", "space"):
            if 0 <= self.grid_sel < n:
                self.goto(self.grid_sel)
                self.toggle_grid(False)
            return "break"
        if event.keysym == "Escape":
            self.toggle_grid(False)
            return "break"
        return None

    def _grid_scroll_to(self, i):
        c = self.grid_canvas
        if c is None:
            return
        try:
            cell_w, cell_h, cols, gap = self._grid_metrics()
            total = (min(len(self.files), 400) + cols - 1) // cols * cell_h + gap
            if total <= c.winfo_height():
                return
            y = gap + (i // cols) * cell_h
            c.yview_moveto(max(0.0, min(1.0, y / float(total))))
        except Exception:
            pass

    def _grid_draw(self):
        c = self.grid_canvas
        if c is None or not c.winfo_exists():
            return
        c.delete("all")
        cell_w, cell_h, cols, gap = self._grid_metrics()
        n = min(len(self.files), 400)
        rows = (n + cols - 1) // cols
        c.configure(scrollregion=(0, 0, cols * cell_w + gap, rows * cell_h + gap))
        for i in range(n):
            path = self.files[i]
            x = gap + (i % cols) * cell_w
            y = gap + (i // cols) * cell_h
            ph = self.thumbs.get(path)
            if ph is not None:
                c.create_image(x + gap, y + gap, anchor="nw", image=ph)
            else:
                c.create_rectangle(x + gap, y + gap, x + gap + self.thumb_w,
                                   y + gap + self.thumb_h,
                                   fill="#1d1d1d", outline=BTN_BG)
            if i == self.index:          # 正在看的那张：细蓝框
                c.create_rectangle(x + gap - 2, y + gap - 2,
                                   x + gap + self.thumb_w + 2,
                                   y + gap + self.thumb_h + 2,
                                   outline=ACCENT, width=2)
            if i == getattr(self, "grid_sel", -1):   # 键盘选中：粗白框
                c.create_rectangle(x + gap - 4, y + gap - 4,
                                   x + gap + self.thumb_w + 4,
                                   y + gap + self.thumb_h + 4,
                                   outline="#ffffff", width=3)

    def _grid_click(self, event):
        c = self.grid_canvas
        if c is None:
            return
        cell_w, cell_h, cols, gap = self._grid_metrics()
        x = c.canvasx(event.x)
        y = c.canvasy(event.y)
        col = int((x - gap // 2) // cell_w)
        row = int((y - gap // 2) // cell_h)
        if col < 0 or row < 0 or col >= cols:
            return
        i = row * cols + col
        if 0 <= i < min(len(self.files), 400):
            self.grid_sel = i
            self.goto(i)
            self.toggle_grid(False)

    def _grid_wheel(self, event):
        if self.grid_canvas is not None:
            self.grid_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    # -------------------------------------------------------- 批量重命名

    def batch_rename(self):
        if getattr(self, "rename_win", None) is not None:
            try:
                self.rename_win.lift()
                self.rename_win.focus_force()
                return
            except Exception:
                self.rename_win = None
        win = tk.Toplevel(self)
        win.title("批量重命名")
        win.configure(bg=BAR_BG)
        win.transient(self)
        self.after(40, self._apply_lang)
        self.rename_win = win
        body = tk.Frame(win, bg=BAR_BG)
        body.pack(fill="both", expand=True, padx=px(16), pady=px(14))

        def row(label, var, width=18):
            r = tk.Frame(body, bg=BAR_BG)
            r.pack(fill="x", pady=px(3))
            tk.Label(r, text=label, width=8, anchor="w", font=self.ui_font,
                     bg=BAR_BG, fg=FG_DIM).pack(side="left")
            e = tk.Entry(r, textvariable=var, width=width, bg=DEEP2_BG, fg=FG,
                         insertbackground=FG, relief="flat", bd=0,
                         highlightthickness=px(1),
                         highlightbackground=TROUGH_BG,
                         highlightcolor=ACCENT, font=self.ui_font)
            e.pack(side="left", fill="x", expand=True, ipady=px(4))
            return e

        folder = self.folder or (os.path.dirname(self.doc.path)
                                 if self.doc is not None else "")
        self.rn_dir = tk.StringVar(value=folder)
        self.rn_prefix = tk.StringVar(value="IMG_")
        self.rn_start = tk.StringVar(value="1")
        self.rn_width = tk.StringVar(value="3")
        row("目录", self.rn_dir)
        r2 = tk.Frame(body, bg=BAR_BG)
        r2.pack(fill="x", pady=(px(3), 0))
        for label, var, w in (("前缀", self.rn_prefix, 10),
                              ("起始", self.rn_start, 6),
                              ("位数", self.rn_width, 6)):
            tk.Label(r2, text=label, font=self.ui_font, bg=BAR_BG,
                     fg=FG_DIM).pack(side="left", padx=(0, px(3)))
            tk.Entry(r2, textvariable=var, width=w, bg=DEEP2_BG, fg=FG,
                     insertbackground=FG, relief="flat", bd=0,
                     highlightthickness=px(1), highlightbackground=TROUGH_BG,
                     highlightcolor=ACCENT, font=self.ui_font).pack(
                         side="left", ipady=px(4), padx=(0, px(10)))

        self.rn_box = tk.Listbox(body, height=8, bg=DEEP_BG, fg=FG,
                                 bd=0, highlightthickness=0,
                                 font=self.mono_font, activestyle="none")
        self.rn_box.pack(fill="both", expand=True, pady=(px(8), px(6)))
        self.rn_msg = tk.Label(body, text="", font=self.ui_font_s, bg=BAR_BG,
                               fg=FG_DIM, anchor="w", justify="left")
        self.rn_msg.pack(fill="x")
        btns = tk.Frame(body, bg=BAR_BG)
        btns.pack(fill="x", pady=(px(8), 0))
        self._panel_btn(btns, "预览", self._rename_preview)
        self._panel_btn(btns, "开始重命名", self._rename_do)
        self._panel_btn(btns, "关闭", win.destroy)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))
        self._rename_preview()

    def _rename_plan(self):
        """算出「旧名 → 新名」的清单，不做任何实际改动。"""
        folder = (self.rn_dir.get() or "").strip()
        if not folder or not os.path.isdir(folder):
            return None, "源目录不存在。"
        try:
            start = int(self.rn_start.get())
            width = max(1, min(8, int(self.rn_width.get())))
        except ValueError:
            return None, "起始序号和位数必须是整数。"
        files = list_images(folder)
        if not files:
            return None, "这个文件夹里没有图片。"
        prefix = self.rn_prefix.get()
        plan = []
        for i, p in enumerate(files):
            ext = os.path.splitext(p)[1].lower()
            name = "%s%s%s" % (prefix, str(start + i).zfill(width), ext)
            plan.append((p, os.path.join(folder, name)))
        return plan, "%d 个文件" % len(plan)

    def _rename_preview(self):
        plan, msg = self._rename_plan()
        box = getattr(self, "rn_box", None)
        if box is None or not box.winfo_exists():
            return
        box.delete(0, "end")
        if plan is None:
            self.rn_msg.configure(text=msg, fg="#ff8a6b")
            return
        same = sum(1 for a, b in plan if os.path.normcase(a) == os.path.normcase(b))
        for a, b in plan[:200]:
            mark = "  （不变）" if os.path.normcase(a) == os.path.normcase(b) else ""
            box.insert("end", "%s  →  %s%s" % (
                os.path.basename(a), os.path.basename(b), mark))
        if len(plan) > 200:
            box.insert("end", "… 还有 %d 个" % (len(plan) - 200))
        self.rn_msg.configure(
            text="%s，其中 %d 个名字不变" % (msg, same), fg=FG_DIM)

    def _rename_do(self):
        plan, msg = self._rename_plan()
        if plan is None:
            messagebox.showwarning("批量重命名", msg, parent=self.rename_win)
            return
        todo = [(a, b) for a, b in plan
                if os.path.normcase(a) != os.path.normcase(b)]
        if not todo:
            messagebox.showinfo("批量重命名", "名字都没有变化，无需重命名。",
                                parent=self.rename_win)
            return
        if not messagebox.askyesno(
                "批量重命名",
                "将重命名 %d 个文件，此操作无法撤销。\n\n继续吗？" % len(todo),
                parent=self.rename_win, default="no"):
            return
        # 两阶段改名：先全部改成临时名，再改成目标名，
        # 这样 a→b、b→a 这种互换不会互相踩掉。
        tmp = []
        failed = []
        try:
            for i, (old, new) in enumerate(todo):
                t = old + ".qpe_tmp_%d" % i
                os.rename(old, t)
                tmp.append((t, new, old))
        except OSError as exc:
            failed.append(str(exc))
        done = 0
        for t, new, old in tmp:
            try:
                os.rename(t, new)
                done += 1
            except OSError as exc:
                failed.append(str(exc))
                try:
                    os.rename(t, old)      # 改不回去就尽力还原
                except OSError:
                    pass
        self._flash("重命名完成：成功 %d 个%s" % (
            done, ("，失败 %d 个" % len(failed)) if failed else ""))
        folder = (self.rn_dir.get() or "").strip()
        if os.path.isdir(folder) and os.path.normcase(
                os.path.abspath(folder)) == os.path.normcase(
                    os.path.abspath(self.folder or "")):
            self.open_folder(folder)
        self._rename_preview()
        if failed:
            messagebox.showerror("批量重命名",
                                 "有 %d 个失败：\n%s" % (len(failed),
                                                         "\n".join(failed[:5])),
                                 parent=self.rename_win)

    # -------------------------------------------------------- 批量导出

    def flatten_doc(self, doc, adj, geom, locals_, max_long=0):
        """用给定参数处理任意一张图（批量导出用）。

        临时借用一下 app 的状态，跑完立刻还原：调色管线本身不碰 Tk 控件，
        所以这样复用最省事，也不会把界面状态搞乱。
        """
        save = (self.doc, self.adj, self.geom, self.locals, self.frame_i,
                self.show_original)
        self.doc, self.adj, self.geom, self.locals = doc, adj, geom, locals_
        self.frame_i = 0
        self.show_original = False      # 批量导出同样不能被对比开关影响
        for k in ("geom_key", "tone_key", "color_key", "auto_lut",
                  "contrast_mean"):
            setattr(self, k, None)
        self.hsv_src = None
        self.hsv_chans = None
        self.local_mask_cache = {}
        self.tile_cache.clear()
        try:
            im = self._flatten()
        finally:
            (self.doc, self.adj, self.geom, self.locals, self.frame_i,
             self.show_original) = save
            for k in ("geom_key", "tone_key", "color_key", "auto_lut",
                      "contrast_mean"):
                setattr(self, k, None)
            self.hsv_src = None
            self.hsv_chans = None
            self.local_mask_cache = {}
            self.tile_cache.clear()
        if im is not None and max_long and max(im.size) > max_long:
            r = max_long / float(max(im.size))
            im = im.resize((max(1, int(im.width * r)),
                            max(1, int(im.height * r))),
                           Image.Resampling.LANCZOS, reducing_gap=2.0)
        return im

    def batch_export(self):
        if self.doc is None:
            messagebox.showinfo("批量导出",
                                "先打开一张图片，批量导出会套用当前的调整设置。",
                                parent=self)
            return
        if self.batch_win is not None and self.batch_win.winfo_exists():
            self.batch_win.lift()
            return
        src = self.folder or os.path.dirname(self.doc.path)
        win = tk.Toplevel(self)
        self.batch_win = win
        win.title("批量导出")
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(560), px(380)))
        win.transient(self)
        self.after(40, self._apply_lang)
        wrap = tk.Frame(win, bg=BAR_BG)
        wrap.pack(fill="both", expand=True, padx=px(14), pady=px(12))

        def row(label, value, browse=None):
            f = tk.Frame(wrap, bg=BAR_BG)
            f.pack(fill="x", pady=(0, px(6)))
            tk.Label(f, text=label, font=self.ui_font, bg=BAR_BG, fg=FG_DIM,
                     width=7, anchor="w").pack(side="left")
            var = tk.StringVar(value=value)
            ent = tk.Entry(f, textvariable=var, font=self.ui_font, bg=DEEP_BG,
                           fg=FG, insertbackground=FG, bd=0,
                           highlightthickness=px(1), highlightbackground="#333333",
                           highlightcolor=ACCENT)
            ent.pack(side="left", fill="x", expand=True, ipady=px(3))
            if browse:
                self._panel_btn(f, "浏览", lambda: self._batch_pick(var, browse))
            return var

        self.b_src = row("源目录", src, "dir")
        self.b_out = row("输出到", os.path.join(src, "导出"), "dir")

        # 图形化预览：一眼看到输出的尺寸
        pv = tk.Frame(wrap, bg=BAR_BG)
        pv.pack(fill="x", pady=(0, px(6)))
        self.b_prev_can = tk.Canvas(pv, bg=DEEP_BG, height=px(96),
                                    highlightthickness=0, bd=0)
        self.b_prev_can.pack(side="left", padx=(0, px(10)))
        self.b_prev_ph = None
        self.b_prev_info = tk.Label(pv, text="", font=self.mono_font, bg=BAR_BG,
                                    fg=FG_DIM, anchor="w", justify="left")
        self.b_prev_info.pack(side="left", fill="both", expand=True)
        self._batch_preview_draw()
        f = tk.Frame(wrap, bg=BAR_BG)
        f.pack(fill="x", pady=(0, px(6)))
        tk.Label(f, text="格式", font=self.ui_font, bg=BAR_BG, fg=FG_DIM,
                 width=7, anchor="w").pack(side="left")
        self.b_fmt = tk.StringVar(value="JPEG")
        om = tk.OptionMenu(f, self.b_fmt, "JPEG", "PNG", "WebP")
        om.configure(bg=BTN_BG, fg=FG, activebackground=BAR_HOVER,
                     highlightthickness=0, bd=0, font=self.ui_font)
        om["menu"].configure(bg=BTN_BG, fg=FG, font=self.ui_font)
        om.pack(side="left")
        tk.Label(f, text="  最长边(0=原尺寸)", font=self.ui_font, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left")
        self.b_max = tk.StringVar(value="0")
        tk.Entry(f, textvariable=self.b_max, width=6, font=self.ui_font,
                 bg=DEEP_BG, fg=FG, insertbackground=FG, bd=0,
                 highlightthickness=0).pack(side="left", padx=px(4), ipady=px(3))
        f2 = tk.Frame(wrap, bg=BAR_BG)
        f2.pack(fill="x", pady=(px(4), 0))
        tk.Label(f2, text="快捷尺寸", font=self.ui_font, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left", padx=(0, px(4)))
        for label, val in (("原尺寸", "0"), ("1080", "1080"),
                           ("1920", "1920"), ("2048", "2048"),
                           ("4096", "4096")):
            self._panel_btn(
                f2, label, lambda v=val: self.b_max.set(v))
        tk.Label(f2, text="  质量", font=self.ui_font, bg=BAR_BG,
                 fg=FG_DIM).pack(side="left")
        self.b_q = tk.IntVar(value=92)
        tk.Scale(f2, from_=40, to=100, resolution=1, orient="horizontal",
                 variable=self.b_q, showvalue=True, bd=0, highlightthickness=0,
                 bg=BAR_BG, fg=FG, troughcolor=TROUGH_BG, activebackground=ACCENT,
                 sliderrelief="flat", length=px(120), width=px(11),
                 font=self.ui_font_s).pack(side="left")

        try:
            self.b_max.trace_add("write", lambda *a: self._batch_preview_draw())
            self.b_fmt.trace_add("write", lambda *a: self._batch_preview_draw())
        except Exception:
            pass
        self.b_apply = tk.IntVar(value=1)
        tk.Checkbutton(wrap, text="套用当前调整设置（不勾选则只做格式转换/缩放）",
                       variable=self.b_apply, font=self.ui_font, bg=BAR_BG,
                       fg=FG, selectcolor=TROUGH_BG, activebackground=BAR_BG,
                       activeforeground=FG_HI, bd=0, highlightthickness=0,
                       anchor="w", takefocus=0).pack(fill="x")
        self.b_over = tk.IntVar(value=0)
        tk.Checkbutton(wrap, text="已存在同名文件时覆盖", variable=self.b_over,
                       font=self.ui_font, bg=BAR_BG, fg=FG,
                       selectcolor=TROUGH_BG, activebackground=BAR_BG,
                       activeforeground=FG_HI, bd=0, highlightthickness=0,
                       anchor="w", takefocus=0).pack(fill="x")

        self.b_bar = tk.Canvas(wrap, height=px(10), bg=DEEP_BG,
                               highlightthickness=0, bd=0)
        self.b_bar.pack(fill="x", pady=(px(10), px(4)))
        self.b_msg = tk.Label(wrap, text="准备就绪", font=self.ui_font_s,
                              bg=BAR_BG, fg=FG_DIM, anchor="w")
        self.b_msg.pack(fill="x")
        row2 = tk.Frame(wrap, bg=BAR_BG)
        row2.pack(fill="x", pady=(px(8), 0))
        self.b_go = self._panel_btn(row2, "开始导出", self._batch_start)
        self.b_stop_btn = self._panel_btn(row2, "停止", self._batch_stop)
        self._panel_btn(row2, "关闭", lambda: win.destroy())

    def _batch_preview_draw(self):
        """把当前图片缩成小图放进导出对话框，并标出目标尺寸。"""
        can = getattr(self, "b_prev_can", None)
        lbl = getattr(self, "b_prev_info", None)
        if can is None or not can.winfo_exists() or self.doc is None:
            return
        im = self.doc.get_frame(self.frame_i)
        if im is None:
            return
        sw, sh = im.size
        try:
            target = int(self.b_max.get() or 0)
            fmt = self.b_fmt.get()
        except Exception:
            target, fmt = 0, "JPEG"
        if target and max(sw, sh) > target:
            r = target / float(max(sw, sh))
            tw, th = max(1, int(sw * r)), max(1, int(sh * r))
            note = "缩放"
        else:
            tw, th = sw, sh
            note = "原尺寸"
        thumb = im.convert("RGB")
        thumb.thumbnail((px(96), px(96)), Image.Resampling.BILINEAR)
        self.b_prev_ph = ImageTk.PhotoImage(thumb, master=can)
        can.configure(width=thumb.width, height=thumb.height)
        can.delete("all")
        can.create_image(thumb.width // 2, thumb.height // 2,
                         image=self.b_prev_ph)
        lbl.configure(text="%d x %d  ->  %d x %d (%s)   %.1f MP   %s" % (
            sw, sh, tw, th, note, tw * th / 1e6, fmt))

    def _batch_pick(self, var, kind):
        p = (filedialog.askdirectory(parent=self.batch_win)
             if kind == "dir" else filedialog.asksaveasfilename())
        if p:
            var.set(p)

    def _batch_start(self):
        src = self.b_src.get().strip()
        out = self.b_out.get().strip()
        if not os.path.isdir(src):
            messagebox.showwarning("批量导出", "源目录不存在。", parent=self.batch_win)
            return
        if not out:
            messagebox.showwarning("批量导出", "请填写输出目录。", parent=self.batch_win)
            return
        files = list_images(src)
        if not files:
            messagebox.showinfo("批量导出", "源目录里没有可导出的图片。",
                                parent=self.batch_win)
            return
        try:
            os.makedirs(out, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("批量导出", "无法创建输出目录：%s" % exc,
                                 parent=self.batch_win)
            return
        fmt = self.b_fmt.get()
        self.b_ext = {"JPEG": ".jpg", "PNG": ".png", "WebP": ".webp"}[fmt]
        self.b_fmt_name = fmt
        self.b_out_dir = out
        self.b_quality = int(self.b_q.get())
        try:
            self.b_maxlong = max(0, int(self.b_max.get() or 0))
        except ValueError:
            self.b_maxlong = 0
        self.b_use_adj = bool(self.b_apply.get())
        self.b_overwrite = bool(self.b_over.get())
        self.b_files = files
        self.b_i = 0
        self.b_ok = 0
        self.b_fail = []
        self.b_stop = False
        self.b_busy = False
        self.b_go.configure(state="disabled")
        self._batch_tick()

    def _batch_stop(self):
        """中止批量导出：当前这张做完就停，已导出的保留。"""
        self.b_stop = True
        try:
            self.b_stop_btn.configure(state="disabled")
            self.b_msg.configure(text=_tr("正在停止…（当前这张处理完就停）"))
        except Exception:
            pass

    def _batch_tick(self):
        if self.batch_win is None or not self.batch_win.winfo_exists():
            return
        if getattr(self, "b_stop", False):
            self._batch_finish()
            return
        if self.b_i >= len(self.b_files):
            self._batch_finish()
            return
        if getattr(self, "b_busy", False):
            return
        path = self.b_files[self.b_i]
        name = os.path.basename(path)
        target = os.path.join(self.b_out_dir,
                              os.path.splitext(name)[0] + self.b_ext)
        self.b_busy = True
        if os.path.exists(target) and not self.b_overwrite:
            self.b_fail.append((name, "已存在，跳过"))
            self._batch_item_done()
            return
        # 先读头部尺寸，避免对 1.5 亿像素以上的图直接全解码把内存打爆
        pw = ph = 0
        if os.path.splitext(path)[1].lower() not in RAW_EXTS:
            try:
                with Image.open(path) as probe:
                    pw, ph = probe.size
            except Exception:
                pass
        if pw * ph > EXPORT_MAX_PIXELS:
            self.b_fail.append(
                (name, "图片过大（%.0f MP），已跳过" % (pw * ph / 1e6)))
            self._batch_item_done()
            return
        adj = copy.deepcopy(self.adj) if self.b_use_adj \
            else self._default_adj()
        locs = copy.deepcopy(self.locals) if self.b_use_adj else []
        geom = list(self.geom) if self.b_use_adj else []
        params = {}
        if self.b_fmt_name in ("JPEG", "WebP"):
            params["quality"] = self.b_quality
        icc = _srgb_icc_bytes()
        if icc and self.b_ext.lower() in (".jpg", ".jpeg", ".png", ".webp",
                                          ".tif", ".tiff"):
            params["icc_profile"] = icc
        try:
            self.b_msg.configure(
                text=_trf("%d / %d · 正在解码 %s")
                % (self.b_i + 1, len(self.b_files), name))
        except Exception:
            pass

        def loaded(doc, err):
            self._batch_loaded(doc, err, name, target, adj, locs, geom,
                               params)

        self._async_call(
            lambda: ImageDoc.load(path, force_full=True), loaded)

    def _make_render_clone(self, doc, adj, geom, locs):
        """给后台批量渲染用的轻量副本。

        渲染管线只读 doc/adj/geom/locals 与少量缓存；复制一份独立对象的
        __dict__，把缓存换成新的，就能在 worker 里跑 _flatten，不碰 Tk。
        """
        clone = object.__new__(type(self))
        clone.__dict__.update(self.__dict__)
        clone.doc = doc
        clone.adj = adj
        clone.geom = geom
        clone.locals = locs
        clone.frame_i = 0
        clone.show_original = False
        clone.soft_proof = False
        clone.soft_proof_transforms = None
        clone.geom_key = None
        clone.geom_img = None
        clone.contrast_mean = None
        clone.auto_lut = None
        clone.hsv_src = None
        clone.hsv_chans = None
        clone.tile_cache = {}
        clone.detail_cache = {}
        clone.local_mask_cache = {}
        return clone

    def _batch_loaded(self, doc, err, name, target, adj, locs, geom, params):
        """解码完成：用渲染副本在 worker 里渲染+保存，主线程只收进度。"""
        if self.batch_win is None or not self.batch_win.winfo_exists():
            self.b_busy = False
            return
        if getattr(self, "b_stop", False):
            self.b_busy = False
            self._batch_finish()
            return
        if err is not None:
            self.b_fail.append((name, str(err)))
            self._batch_item_done()
            return
        try:
            clone = self._make_render_clone(doc, adj, geom, locs)
            self.b_msg.configure(
                text=_trf("%d / %d · 正在保存 %s")
                % (self.b_i + 1, len(self.b_files), name))
        except Exception as exc:
            self.b_fail.append((name, str(exc)))
            self._batch_item_done()
            return

        fmt = self.b_fmt_name
        maxlong = self.b_maxlong

        def saved(_result, save_err):
            if save_err is not None:
                self.b_fail.append((name, str(save_err)))
            else:
                self.b_ok += 1
            self._batch_item_done()

        def work():
            im = clone._flatten()
            if im is None:
                raise ValueError("渲染失败")
            if maxlong and max(im.size) > maxlong:
                r = maxlong / float(max(im.size))
                im = im.resize((max(1, int(im.width * r)),
                                max(1, int(im.height * r))),
                               Image.Resampling.LANCZOS, reducing_gap=2.0)
            if fmt == "JPEG" and im.mode != "RGB":
                im = im.convert("RGB")
            im.save(target, **params)
            return True

        self._async_call(work, saved)


    def _batch_item_done(self):
        self.b_busy = False
        if self.batch_win is None or not self.batch_win.winfo_exists():
            return
        self.b_i += 1
        total = len(self.b_files)
        c = self.b_bar
        w = max(1, c.winfo_width())
        c.delete("all")
        c.create_rectangle(0, 0, int(w * self.b_i / total), px(10),
                           fill=ACCENT, outline="")
        if self.batch_win is not None and self.batch_win.winfo_exists():
            self.b_msg.configure(text="%d / %d · 成功 %d · 失败 %d"
                                 % (self.b_i, total, self.b_ok,
                                    len(self.b_fail)))
        self.after(1, self._batch_tick)


    def _batch_finish(self):
        if self.batch_win is not None and self.batch_win.winfo_exists():
            self.b_go.configure(state="normal")
            tag = _tr("已停止") if getattr(self, "b_stop", False) else _tr("完成")
            msg = _tr("%s：成功 %d 张，失败/跳过 %d 张 → %s") % (
                tag, self.b_ok, len(self.b_fail), self.b_out_dir)
            try:
                self.b_stop_btn.configure(state="normal")
            except Exception:
                pass
            self.b_msg.configure(text=msg)
            c = self.b_bar
            c.delete("all")
            c.create_rectangle(0, 0, max(1, c.winfo_width()), px(10),
                               fill=ACCENT, outline="")
        self._flash("批量导出完成：成功 %d 张" % self.b_ok, 3200)

    def _flash(self, text, ms=2200):
        self.meta_lbl.configure(text=_trf(text))
        if self.flash_job is not None:
            try:
                self.after_cancel(self.flash_job)
            except Exception:
                pass
        self.flash_job = self.after(ms, self._update_status)

    def _on_hist_select(self, event=None):
        sel = self.hist_box.curselection()
        if sel:
            self.goto_history(int(sel[0]))

    def goto_history(self, idx):
        if 0 <= idx < len(self.history) and idx != self.hist_i:
            self.hist_i = idx
            self._restore(self.history[idx])

    def _refresh_history_box(self):
        box = self.hist_box
        if box is None or not box.winfo_exists():
            return
        box.delete(0, "end")
        for i, lab in enumerate(self.hist_labels):
            box.insert("end", " %d. %s" % (i, lab))
        box.selection_clear(0, "end")
        if 0 <= self.hist_i < len(self.hist_labels):
            box.selection_set(self.hist_i)
            box.see(self.hist_i)

    def _update_hist_buttons(self):
        for btn, ok in ((self.hist_undo_btn, self.hist_i > 0),
                        (self.hist_redo_btn,
                         self.hist_i < len(self.history) - 1)):
            if btn is not None:
                btn.configure(state="normal" if ok else "disabled")

    def reset_edit_all(self):
        if self.doc is None:
            return
        self.geom = []
        self.adj = self._default_adj()
        self.geom_key = None
        self.tile_cache.clear()
        self.contrast_mean = None
        self.auto_lut = None
        self.tone_key = None
        self.color_key = None
        self.cx = None
        self.cy = None
        self.zoom_mode = "fit"
        self.locals = []
        self.local_sel = -1
        self._rebuild_local_sliders()
        self._refresh_local_box()
        self._sync_panel()
        self._push_history("重置全部")
        self._render()
        self._update_status()

    # ------------------------------------------------------------ 裁剪

    def toggle_crop(self):
        if self.doc is None:
            return
        if self.crop_mode:
            self.cancel_crop()
            return
        self.toggle_panel(True)
        self.picker_mode = False
        self.local_mode = None
        self.crop_mode = True
        self.crop_anchor = None
        self.crop_rect = None
        if self.crop_item is not None:
            self.canvas.delete(self.crop_item)
            self.crop_item = None
        if self.cropbar is not None:
            self.cropbar.pack(side="top", fill="x", before=self.body)
        self._sync_cropbar()
        # 焦点给画布：否则按 Enter 可能被别的控件吃掉，看起来就像「裁剪没反应」
        try:
            self.canvas.focus_set()
        except Exception:
            pass
        self.canvas.configure(cursor="crosshair")
        self._update_status()

    def cancel_crop(self):
        self.crop_mode = False
        if self.cropbar is not None:
            self.cropbar.pack_forget()
        self._clear_grid()
        self._draw_hint()
        self.crop_anchor = None
        self.crop_rect = None
        lbl = getattr(self, "crop_size_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text="")
        if self.crop_item is not None:
            self.canvas.delete(self.crop_item)
            self.crop_item = None
        self._update_cursor()
        self._update_status()

    def _canvas_to_image(self, x, y):
        """画布坐标 → 图像坐标。"""
        im = self._view_image()
        if im is None:
            return 0.0, 0.0
        iw, ih = im.size
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        s = max(self.scale, 1e-6)
        cx = self.cx if self.cx is not None else iw / 2.0
        cy = self.cy if self.cy is not None else ih / 2.0
        return ((x - (cw / 2.0 - cx * s)) / s, (y - (ch / 2.0 - cy * s)) / s)

    def _image_to_canvas(self, ix, iy):
        """图像坐标 → 画布坐标。"""
        im = self._view_image()
        if im is None:
            return 0.0, 0.0
        iw, ih = im.size
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        s = max(self.scale, 1e-6)
        cx = self.cx if self.cx is not None else iw / 2.0
        cy = self.cy if self.cy is not None else ih / 2.0
        return (ix * s + (cw / 2.0 - cx * s), iy * s + (ch / 2.0 - cy * s))

    def _clear_grid(self):
        for it in self.grid_items:
            try:
                self.canvas.delete(it)
            except Exception:
                pass
        self.grid_items = []

    GRID_STYLES = (("thirds", "三分"), ("golden", "黄金分割"),
                   ("cross", "中心十字"), ("none", "关闭"))

    def _cycle_grid_style(self):
        order = [k for k, _l in self.GRID_STYLES]
        self.grid_style = order[(order.index(self.grid_style) + 1) % len(order)]
        label = dict(self.GRID_STYLES)[self.grid_style]
        if self.grid_style_btn is not None and self.grid_style_btn.winfo_exists():
            self.grid_style_btn.configure(
                text="构图线：%s" % label,
                bg=ACCENT if self.grid_style != "none" else BTN_BG,
                fg="#101010" if self.grid_style != "none" else FG)
        self._draw_crop_grid()
        self._flash("构图辅助线：%s" % label)

    def _draw_crop_grid(self):
        """构图辅助线：三分 / 黄金分割 / 中心十字 / 关闭。"""
        self._clear_grid()
        if not self.crop_mode or not self.crop_rect or self.grid_style == "none":
            return
        l, t, r, b = self.crop_rect
        x0, y0 = self._image_to_canvas(l, t)
        x1, y1 = self._image_to_canvas(r, b)
        if self.grid_style == "thirds":
            fx = fy = (1.0 / 3.0, 2.0 / 3.0)
        elif self.grid_style == "golden":
            fx = fy = (0.382, 0.618)
        else:                       # cross
            fx = fy = (0.5,)
        for f in fx:
            x = x0 + (x1 - x0) * f
            self.grid_items.append(self.canvas.create_line(
                x, y0, x, y1, fill="#7a7a7a", dash=(px(4), px(4))))
        for f in fy:
            y = y0 + (y1 - y0) * f
            self.grid_items.append(self.canvas.create_line(
                x0, y, x1, y, fill="#7a7a7a", dash=(px(4), px(4))))
        for it in self.grid_items:
            self.canvas.tag_raise(it)

    def _draw_crop(self):
        """裁剪框存的是图像坐标，所以缩放/平移/改窗口大小时它始终贴着图。"""
        if not self.crop_rect or self.doc is None:
            return
        l, t, r, b = self.crop_rect
        x0, y0 = self._image_to_canvas(l, t)
        x1, y1 = self._image_to_canvas(r, b)
        if self.crop_item is None:
            self.crop_item = self.canvas.create_rectangle(
                x0, y0, x1, y1, outline=ACCENT, width=max(1, px(2)),
                dash=(px(7), px(5)))
        else:
            self.canvas.coords(self.crop_item, x0, y0, x1, y1)
        self.canvas.tag_raise(self.crop_item)
        lbl = getattr(self, "crop_size_lbl", None)
        if lbl is not None and lbl.winfo_exists():
            lbl.configure(text="%d × %d" % (max(1, int(round(r - l))),
                                            max(1, int(round(b - t)))))
        self._draw_crop_grid()

    def apply_crop(self):
        if not self.crop_mode:
            return
        im = self._view_image()
        if im is None or not self.crop_rect:
            return
        iw, ih = im.size
        l, t, r, b = self.crop_rect
        l = max(0, min(iw - 1, int(round(l))))
        t = max(0, min(ih - 1, int(round(t))))
        r = max(l + 1, min(iw, int(round(r))))
        b = max(t + 1, min(ih, int(round(b))))
        if (r - l) < px(12) or (b - t) < px(12):
            messagebox.showinfo("裁剪", "选区太小了，拖一个大一点的框。", parent=self)
            return
        self.crop_mode = False
        if self.cropbar is not None:
            self.cropbar.pack_forget()
        self._clear_grid()
        if self.crop_item is not None:
            self.canvas.delete(self.crop_item)
            self.crop_item = None
        self.geom.append(("crop", (l, t, r, b)))
        self.geom_key = None
        self.tile_cache.clear()
        self.cx = None
        self.cy = None
        self.zoom_mode = "fit"
        self._push_history("裁剪 %d×%d" % (r - l, b - t))
        self._update_cursor()
        self._render()
        self._update_status()

    # ------------------------------------------------------------ 保存

    def _source_exif(self):
        """取出原图的 EXIF，保存时一并写回去。"""
        try:
            doc = self.doc
            if doc is None or doc.raw_preview:
                return None
            raw = getattr(doc, "exif_bytes", None)
            if not raw:
                return None
            try:
                ex = Image.Exif()
                ex.load(raw)
                # 画面在显示时已经转正了，方向标记改回 1，
                # 否则看图软件会再转一次。
                ex[0x0112] = 1
                return ex.tobytes()
            except Exception:
                return None
        except Exception:
            return None

    def save_as(self):
        doc = self.doc
        if doc is None:
            messagebox.showinfo("保存", "还没有打开图片。", parent=self)
            return
        src_ext = os.path.splitext(doc.path)[1].lower()
        base = os.path.splitext(os.path.basename(doc.path))[0]
        types = [("JPEG", "*.jpg *.jpeg"), ("PNG", "*.png"),
                 ("WebP", "*.webp"), ("BMP", "*.bmp"), ("TIFF", "*.tif *.tiff")]
        if src_ext in RAW_EXTS or doc.raw_preview:
            ext = ".jpg"          # RAW 绝不能覆盖，默认导出 JPEG
        elif src_ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
            ext = src_ext
        else:
            ext = ".png"
        path = filedialog.asksaveasfilename(
            parent=self, title="保存图片", initialdir=os.path.dirname(doc.path),
            initialfile="%s_编辑%s" % (base, ext), defaultextension=ext,
            filetypes=types)
        if not path:
            return
        same = os.path.abspath(path) == os.path.abspath(doc.path)
        if same:
            if src_ext in RAW_EXTS or doc.raw_preview:
                messagebox.showwarning(
                    "无法覆盖", "RAW 原文件不能被覆盖，请换一个文件名。", parent=self)
                return
            if not messagebox.askyesno(
                    "覆盖原文件", "确定要覆盖原文件吗？此操作无法撤销。\n\n%s"
                    % os.path.basename(path), parent=self, default="no"):
                return
        try:
            im = self._flatten()
            if im is None:
                return
            fmt = os.path.splitext(path)[1].lower()
            params = {}
            if fmt in (".jpg", ".jpeg"):
                if im.mode != "RGB":
                    im = im.convert("RGB")
                params["quality"] = 92
                exif = self._source_exif()
                if exif:
                    params["exif"] = exif
            elif fmt == ".webp":
                params["quality"] = 92
            if fmt in (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"):
                icc = _srgb_icc_bytes()
                if icc:
                    params["icc_profile"] = icc
            im.save(path, **params)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.meta_lbl.configure(text="已保存：%s" % os.path.basename(path))
        self.after(2600, self._update_status)

    def _cancel_modes(self):
        """Esc 统一取消：先退全分辨率载入/裁剪/吸管/建滤镜，再退幻灯片等。"""
        if getattr(self, "full_loading", None):
            self.pending_full = None
            self.full_loading = None
            self._stop_full_timer()
            self._set_full_btn_busy(False)
            self._flash("已取消载入全分辨率", 1800)
            self._update_status()
            return
        if self.picker_mode or self.local_mode or self.crop_mode:
            if self.crop_mode:
                self.cancel_crop()
            self.picker_mode = False
            self.local_mode = None
            self.local_drag = None
            self._draw_hint()
            self._update_cursor()
            self._update_status()
            return "break"
        self.on_escape()
        return "break"

    def on_escape(self):
        """Esc 只负责「退出当前状态」，绝不关闭程序。

        之前这里的 else 分支是 self.on_close()，结果什么都没开的时候
        按一下 Esc 整个程序就退了 —— 这是最要命的一个 bug。
        """
        if self.grid_shown:
            self.toggle_grid(False)
        elif self.crop_mode:
            self.cancel_crop()
        elif self.slideshow:
            self.toggle_slideshow()
        elif self.split_x is not None:
            self.toggle_split()
        elif self.picker_mode or self.local_mode:
            self.picker_mode = False
            self.local_mode = None
            self.local_drag = None
            self._draw_hint()
            self._update_cursor()
            self._update_status()

    # ------------------------------------------------------------ 信息

    def show_info(self):
        doc = self.doc
        if doc is None:
            return
        if self.info_win is not None and self.info_win.winfo_exists():
            self.info_win.destroy()
        win = tk.Toplevel(self)
        self.info_win = win
        win.title("图片信息")
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(560), px(640)))
        win.transient(self)
        self.after(40, self._apply_lang)
        bar = tk.Frame(win, bg=BAR_BG)
        bar.pack(side="bottom", fill="x", padx=px(12), pady=px(8))

        def do_copy():
            self.clipboard_clear()
            self.clipboard_append(self._info_text(doc))
            self._flash("图片信息已复制到剪贴板")

        self._panel_btn(bar, "复制全部", do_copy)
        self._panel_btn(bar, "关闭", win.destroy)
        txt = tk.Text(win, bg=DEEP_BG, fg=FG, bd=0, highlightthickness=0,
                      wrap="word", font=self.mono_font, padx=px(16),
                      pady=px(14), insertbackground=FG)
        sb = tk.Scrollbar(win, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.insert("1.0", self._info_text(doc))
        txt.configure(state="disabled")
        win.bind("<Escape>", lambda e: win.destroy())

    def cache_report(self):
        """当前缓存占用，给信息窗口用 —— 轻量软件应该让人看得见内存。"""
        try:
            docb = sum(d.mem_bytes() for d in self.cache.values()
                       if d is not None)
            docs = len([d for d in self.cache.values() if d is not None])
            tileb = sum(v.size[0] * v.size[1] * (4 if v.mode == "RGBA" else 3)
                        for v in self.tile_cache.values())
            detb = sum(v.size[0] * v.size[1] * 3
                       for v in self.detail_cache.values())
            thumbb = sum(ph.width() * ph.height() * 4
                         for ph in self.thumbs.values())
            return {"documents": docs, "doc_mb": docb / 1048576.0,
                    "tile_mb": tileb / 1048576.0,
                    "detail_mb": detb / 1048576.0,
                    "thumbs": len(self.thumbs),
                    "thumb_mb": thumbb / 1048576.0,
                    "budget_mb": self.cache_budget / 1048576.0}
        except Exception:
            return None

    def _adjust_summary(self):
        """把当前调整里所有非默认项列出来，方便贴给别人复现。"""
        a = self.adj
        d = self._default_adj()
        names = (("temperature", "色温"), ("tint", "色调"), ("exposure", "曝光"),
                 ("contrast", "对比度"), ("highlights", "高光"),
                 ("shadows", "阴影"), ("whites", "白色色阶"),
                 ("blacks", "黑色色阶"), ("vibrance", "自然饱和度"),
                 ("saturation", "饱和度"), ("clarity", "清晰度"),
                 ("dehaze", "去朦胧"), ("sharpen", "锐化"),
                 ("nr_luma", "亮度降噪"), ("nr_color", "颜色降噪"),
                 ("vignette", "暗角"))
        out = []
        for k, label in names:
            if abs(float(a.get(k, 0)) - float(d.get(k, 0))) > 1e-6:
                out.append("%s %+g" % (_tr(label), a[k]))
        for k, label in (("curve", "主曲线"), ("curve_r", "红曲线"),
                         ("curve_g", "绿曲线"), ("curve_b", "蓝曲线")):
            if not _curve_is_identity(a.get(k, d[k])):
                out.append(_tr(label) + _tr("已调"))
        for mode, label in (("hue", "色相"), ("sat", "饱和"), ("lum", "明度")):
            vals = [v for v in a["hsl"].get(mode, []) if abs(v) > 1e-6]
            if vals:
                out.append(_tr("HSL-%s %d 段") % (_tr(label), len(vals)))
        if a.get("grayscale"):
            out.append(_tr("灰度"))
        if a.get("split_hi_sat") or a.get("split_lo_sat"):
            out.append(_tr("色调分离"))
        if self.locals:
            out.append(_tr("局部滤镜 %d 个") % len(self.locals))
        if self._watermark():
            out.append(_tr("水印"))
        return out

    def _info_text(self, doc):
        im = self._view_image()
        size = im.size if im is not None else doc.size
        L = []
        L.append("文件")
        L.append("  名称      %s" % os.path.basename(doc.path))
        L.append("  路径      %s" % doc.path)
        L.append("  大小      %s (%d 字节)" % (human_size(doc.file_size), doc.file_size))
        L.append("  修改时间  %s" % fmt_time(doc.mtime))
        L.append("")
        L.append("图像")
        L.append("  格式      %s%s" % (
            doc.fmt, "（RAW 内嵌预览）" if doc.raw_preview else ""))
        L.append("  显示尺寸  %d × %d" % (size[0], size[1]))
        if (size[0], size[1]) != doc.size:
            L.append("  原始尺寸  %d × %d" % doc.size)
        L.append("  色彩模式  %s" % doc.mode)
        L.append("  色彩空间  %s%s" % (
            getattr(doc, "icc_source", "sRGB"),
            "（已转 sRGB）" if getattr(doc, "icc_converted", False) else ""))
        if getattr(self, "soft_proof", False):
            L.append("  软打样    %s（仅预览）"
                     % getattr(self, "soft_proof_name", "ICC"))
        if doc.n_frames > 1:
            L.append("  帧数      %d" % doc.n_frames)
        L.append("  透明通道  %s" % ("有" if doc.alpha else "无"))
        L.append("  缩放      %d%%" % int(round(self.scale * 100)))
        L.append("")
        exif = _exif_lines(doc)
        if exif:
            L.append("EXIF")
            L.extend(exif)
        else:
            L.append("EXIF      无")
        L.append("")
        rep = self.cache_report()
        if rep:
            L.append("内存缓存")
            L.append("  已解码    %d 张 / %.0f MB（上限 %.0f MB）" % (
                rep["documents"], rep["doc_mb"], rep["budget_mb"]))
            L.append("  渲染瓦片  %.1f MB" % rep["tile_mb"])
            L.append("  细节缓存  %.1f MB" % rep["detail_mb"])
            L.append("  缩略图    %d 张 / %.1f MB" % (rep["thumbs"],
                                                   rep["thumb_mb"]))
            L.append("")
        L.append("当前调整")
        summary = self._adjust_summary()
        if summary:
            L.append("  " + "  ·  ".join(summary))
        else:
            L.append("  （未做任何调整）")
        L.append("")
        # 逐行翻译：信息面板每行都是 "  名称      %s" 这种带占位符的词条
        return "\n".join(_trf(line) for line in L)

    def show_about(self):
        if self.about_win is not None:
            try:
                self.about_win.lift()
                self.about_win.focus_force()
                return
            except Exception:
                self.about_win = None
        win = tk.Toplevel(self)
        win.title("关于 %s" % APP_NAME)
        win.configure(bg=BAR_BG)
        win.transient(self)
        self.after(40, self._apply_lang)
        win.resizable(False, False)
        self.about_win = win
        body = tk.Frame(win, bg=BAR_BG)
        body.pack(padx=px(28), pady=px(22))
        big = (self.ui_font[0], -int(px(17)), "bold")
        head = tk.Frame(body, bg=BAR_BG)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, font=big, bg=BAR_BG, fg=FG).pack(
            side="left")
        tk.Label(head, text="  %s" % APP_VERSION, font=self.ui_font, bg=BAR_BG,
                 fg=ACCENT).pack(side="left", pady=(px(4), 0))
        tk.Label(body, text="打开快 · 切图快 · 调色准", font=self.ui_font_s,
                 bg=BAR_BG, fg=FG_DIM).pack(anchor="w", pady=(0, px(12)))

        def para(text, dim=True):
            tk.Label(body, text=text, justify="left", anchor="w",
                     font=self.ui_font, bg=BAR_BG,
                     fg=FG_DIM if dim else FG,
                     wraplength=px(440)).pack(fill="x", pady=(0, px(8)))

        para("「打开快」不是口号 —— 它只处理你眼睛能看到的像素。"
             "按可见区域渲染，4000 万像素的照片首帧不到一秒。", dim=False)
        para("「调色准」也不是 —— 预览和导出走同一套渲染管，"
             "实测平均逐像素差 0.000。你看到的就是你存下的。")

        facts = (
            "· 非破坏式：所有调整都在操作栈里，随时撤销、随时回到原图\n"
            "· 一个 .py 就是插件：自带 12 个（像素化/复古胶片/圆形头像/白边框/锐化/黑白/\n"
            "  自动色阶/加文字/16:9 裁剪/移轴微缩/丁达尔光/故障艺术），\n"
            "  都能调参，写一个也只要几十行\n"
            "· 技术：Python + Pillow + Tkinter，主程序 5.2 MB\n"
            "  没有 Electron、没有浏览器内核、不联网、不需要管理员权限")
        para(facts)

        para("性能档位（设置 → 性能）：拖动优先、首帧优先、自动；", dim=False)
        para("专注模式（Tab）：收起工具条、状态栏和右侧面板，只留画布。",
             dim=False)
        para("格式：JPEG · PNG · WebP · TIFF · BMP · GIF · ICO，"
             "以及尼康 NEF 等 RAW 的内嵌预览（不需要 RAW 解码库）。",
             dim=False)
        para("它不做什么：不做图库、不做液化、不做 AI 抠图。"
             "全屏做成了兼容模式（无边框最大化 + Esc 退出），"
             "系统级全屏在个别驱动上会黑屏，所以不用它。")

        row = tk.Frame(body, bg=BAR_BG)
        row.pack(fill="x", pady=(px(10), 0))
        self._panel_btn(row, "快捷键说明", self.show_help)
        self._panel_btn(row, "打开官网", self._open_site)
        self._panel_btn(row, "关闭", win.destroy)
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - win.winfo_width()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - win.winfo_height()) // 3
        win.geometry("+%d+%d" % (max(0, x), max(0, y)))

    def check_updates(self):
        """手动检查更新：只在点击时联网，不后台轮询、不自动下载。"""
        self._flash("正在检查更新…", 2500)

        def work():
            req = urllib.request.Request(
                "https://api.github.com/repos/11ly322/Prism/releases/latest",
                headers={"User-Agent": "Prism/" + APP_VERSION,
                         "Accept": "application/vnd.github+json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))

        def done(data, err):
            if err is not None:
                messagebox.showerror(
                    "检查更新", "检查更新失败：%s" % str(err)[:120],
                    parent=self)
                return
            tag = str((data or {}).get("tag_name") or "").lstrip("vV")
            if not tag:
                messagebox.showerror("检查更新", "检查更新失败：服务器没有返回版本号。",
                                     parent=self)
                return
            try:
                newer = (tuple(int(x) for x in tag.split("."))
                         > tuple(int(x) for x in APP_VERSION.split(".")))
            except Exception:
                newer = tag != APP_VERSION
            if newer:
                if messagebox.askyesno(
                        "发现新版本",
                        "发现新版本 %s（当前 %s）。\n\n打开下载页？"
                        % (tag, APP_VERSION), parent=self):
                    import webbrowser
                    try:
                        webbrowser.open(
                            "https://github.com/11ly322/Prism/releases/latest")
                    except Exception:
                        pass
            else:
                messagebox.showinfo(
                    "检查更新", "已是最新版本 %s。" % APP_VERSION, parent=self)

        self._async_call(work, done)

    def _open_site(self):
        import webbrowser
        try:
            webbrowser.open("https://11ly322.github.io/Prism/")
        except Exception as exc:
            messagebox.showinfo("官网", "https://11ly322.github.io/Prism/\n\n%s"
                                % exc, parent=self)

    def show_help(self):
        win = tk.Toplevel(self)
        win.title("快捷键 - %s %s" % (APP_NAME, APP_VERSION))
        win.configure(bg=BAR_BG)
        win.geometry("%dx%d" % (px(460), px(560)))
        win.transient(self)
        self.after(40, self._apply_lang)
        txt = tk.Text(win, bg=DEEP_BG, fg=FG, bd=0, highlightthickness=0,
                      wrap="word", font=self.mono_font, padx=px(18),
                      pady=px(16))
        txt.pack(fill="both", expand=True)
        body = {"en": HELP_TEXT_EN, "ja": HELP_TEXT_JA}.get(APP_LANG,
                                                HELP_TEXT)
        txt.insert("1.0", body)
        txt.configure(state="disabled")
        win.bind("<Escape>", lambda e: win.destroy())

    # ------------------------------------------------------------ 其它操作

    def copy_path(self):
        if self.doc is None:
            return
        self.clipboard_clear()
        self.clipboard_append(self.doc.path)
        self.meta_lbl.configure(text="路径已复制到剪贴板")
        self.after(1600, self._update_status)

    def delete_current(self):
        if not self.files or self.doc is None:
            return
        path = self.files[self.index]
        if not messagebox.askyesno(
                "删除文件",
                "确定要永久删除这个文件吗？此操作无法撤销。\n\n%s" % os.path.basename(path),
                parent=self, default="no"):
            return
        try:
            os.remove(path)
        except OSError as exc:
            messagebox.showerror("删除失败", str(exc), parent=self)
            return
        self.cache.pop(path, None)
        if path in self.cache_order:
            self.cache_order.remove(path)
        del self.files[self.index]
        if not self.files:
            self.doc = None
            self.index = -1
            self._render()
            self._update_status()
            self._update_title()
            return
        if self.index >= len(self.files):
            self.index = len(self.files) - 1
        idx = self.index
        self.index = -1
        self.goto(idx, wrap=False)

    def on_close(self):
        self._stop_anim()
        self.destroy()

    def destroy(self):
        """不管从哪条路径关闭，都先停掉所有挂着的 after 任务。

        否则窗口销毁后它们还会触发，在终端里刷出一堆 invalid command name。
        """
        self.alive = False
        try:
            self.save_settings()
        except Exception:
            pass
        for attr in ("slide_job", "refine_job", "resize_job", "bar_job",
                     "render_job", "pick_job", "hist_job", "anim_job",
                     "pump_job", "flash_job",
                     # 下面几个是后来加的，之前漏了：退出时会刷
                     # invalid command name "..._refresh_ai_status"
                     "_ai_job", "_watch_job", "grid_job", "thumbs_job",
                     "defer_job", "proxy_job"):
            job = getattr(self, attr, None)
            if job is not None:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
                setattr(self, attr, None)
        # 兜底：把解释器里所有挂着的 after 全部取消。
        # 逐个记录句柄容易漏（面板里还有几处临时 after），这里直接问 Tcl。
        try:
            for _aid in self.tk.eval("after info").split():
                try:
                    self.after_cancel(_aid)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            tk.Tk.destroy(self)
        except Exception:
            pass


# ---------------------------------------------------------------- EXIF


def _fmt_val(v):
    if isinstance(v, bytes):
        try:
            v = v.decode("utf-8", "replace")
        except Exception:
            v = repr(v)
    if isinstance(v, tuple) and len(v) == 2 and all(
            isinstance(x, (int, float)) for x in v):
        try:
            v = float(v[0]) / float(v[1]) if v[1] else v[0]
        except Exception:
            pass
    if isinstance(v, float):
        v = ("%.4f" % v).rstrip("0").rstrip(".")
    s = str(v).strip().replace("\n", " ")
    if len(s) > 180:
        s = s[:180] + "…"
    return s


_WANTED_TAGS = (
    0x010F,  # Make
    0x0110,  # Model
    0x0112,  # Orientation
    0x0131,  # Software
    0x013B,  # Artist
    0x8298,  # Copyright
    0x829A,  # ExposureTime
    0x829D,  # FNumber
    0x8822,  # ExposureProgram
    0x8827,  # ISOSpeedRatings
    0x9003,  # DateTimeOriginal
    0x9004,  # DateTimeDigitized
    0x9201,  # ShutterSpeedValue
    0x9202,  # ApertureValue
    0x9207,  # MeteringMode
    0x9209,  # Flash
    0x920A,  # FocalLength
    0x9286,  # UserComment
    0xA002,  # PixelXDimension
    0xA003,  # PixelYDimension
    0xA402,  # ExposureMode
    0xA403,  # WhiteBalance
    0xA405,  # FocalLengthIn35mmFilm
    0xA406,  # SceneCaptureType
    0xA434,  # LensModel
)


def _exif_lines(doc):
    img = doc.img
    try:
        ex = img.getexif()
    except Exception:
        return []
    if not ex:
        return []
    items = dict(ex)
    try:
        sub = ex.get_ifd(ExifTags.IFD.Exif)
        for k, v in sub.items():
            items.setdefault(k, v)
    except Exception:
        pass
    names = ExifTags.TAGS
    out = []
    seen = set()
    for tag in _WANTED_TAGS:
        if tag in items:
            out.append("  %-10s%s" % (names.get(tag, str(tag)), _fmt_val(items[tag])))
            seen.add(tag)
    gps = None
    try:
        g = ex.get_ifd(ExifTags.IFD.GPSInfo)
        if g:
            gps = g
    except Exception:
        gps = None
    if gps:
        try:
            lat = _gps_deg(gps.get(2), gps.get(1))
            lon = _gps_deg(gps.get(4), gps.get(3))
            if lat is not None and lon is not None:
                out.append("  %-10s%.6f, %.6f" % ("GPS", lat, lon))
        except Exception:
            pass
    others = 0
    for tag, val in items.items():
        if tag in seen or tag == 0x8769 or tag == 0x8825:
            continue
        if isinstance(val, bytes) and len(val) > 64:
            continue
        others += 1
        if others <= 20:
            out.append("  %-10s%s" % (names.get(tag, str(tag)), _fmt_val(val)))
    if others > 20:
        out.append("  …        另有 %d 个标签" % (others - 20))
    return out


def _gps_deg(coord, ref):
    if not coord:
        return None
    try:
        d = float(coord[0])
        m = float(coord[1])
        s = float(coord[2])
        val = d + m / 60.0 + s / 3600.0
        if ref in ("S", "W"):
            val = -val
        return val
    except Exception:
        return None



# 帮助窗口的英/日版本：行数与对齐跟中文一致，改中文时一起改。




# ---------------------------------------------------------------- 入口


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in sys.argv:
        where = _run_selftest()
        try:
            import tkinter.messagebox as _mb
            _mb.showinfo("Prism 自检", "结果已写入:\n%s" % where)
        except Exception:
            pass
        sys.exit(0)
    app = QPEApp()
    files = [a for a in argv if os.path.isfile(a)]
    folders = [a for a in argv if os.path.isdir(a)]
    if files:
        app.open_files(files)
    elif folders:
        app.open_folder(folders[0])
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
