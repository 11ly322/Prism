# -*- coding: utf-8 -*-
"""新建插件脚手架：一条命令生成可运行的插件文件。

用法：
    python tools/newplugin.py 我的滤镜 --id my_filter --author 你的名字
生成 plugins/我的滤镜.py，含 PLUGIN 元信息、可调参数与注释示例。
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "plugins")

TEMPLATE = '''# -*- coding: utf-8 -*-
"""%(name)s — 由 tools/newplugin.py 生成。

写插件只要三步：
  1. 改下面的 PLUGIN（id/name/version/author/description）
  2. 改 PARAMS（会自动生成滑杆/下拉/勾选）
  3. 改 run(img, **params)，返回新的 PIL.Image
放进 plugins/ 目录即生效，热重载 1.5 秒内自动扫描。
"""

from PIL import Image, ImageEnhance

PLUGIN = {
    "id": "%(pid)s",
    "name": "%(name)s",
    "version": "1.0",
    "api": 2,
    "author": "%(author)s",
    "description": "一句话说明这个插件做什么",
    "network": False,        # 是否联网
    "writes_files": False,   # 是否写文件
}

PARAMS = [
    {"key": "amount", "label": "强度", "type": "slider",
     "min": 0, "max": 100, "default": 40, "step": 1},
]


def run(img, **params):
    """img 是已套用全部调整的 PIL.Image（RGB）；params 里是上面 PARAMS 的值。"""
    p = params or {}
    amount = float(p.get("amount", 40)) / 100.0
    if amount <= 0:
        return img
    out = ImageEnhance.Contrast(img.convert("RGB")).enhance(1.0 + amount)
    return out
'''


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    name = args[0]
    pid = "my_plugin"
    author = "anonymous"
    for i, a in enumerate(sys.argv):
        if a == "--id" and i + 1 < len(sys.argv):
            pid = sys.argv[i + 1]
        elif a == "--author" and i + 1 < len(sys.argv):
            author = sys.argv[i + 1]
    os.makedirs(PLUGINS, exist_ok=True)
    path = os.path.join(PLUGINS, name + ".py")
    if os.path.exists(path):
        print("已存在：%s" % path)
        return 1
    text = TEMPLATE % {"name": name, "pid": pid, "author": author}
    io.open(path, "w", encoding="utf-8", newline="").write(text)
    print("已生成 %s" % path)
    print("下一步：打开 Prism → 工具栏「插件」→ 重载插件，即可看到它。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
