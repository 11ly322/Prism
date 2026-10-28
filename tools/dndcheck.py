# -*- coding: utf-8 -*-
"""拖入打开：模拟 TkDND 的 <<Drop>> 事件，检查文件、文件夹、混合与非法路径。"""
import importlib.machinery
import os
import shutil
import tempfile
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-30s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def pump(app, n=30):
    for _ in range(n):
        app.update()
        time.sleep(0.01)


class Drop:
    def __init__(self, data):
        self.data = data


def main():
    mod = importlib.machinery.SourceFileLoader(
        "dnd9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    if not mod._DND_OK:
        print("  SKIP tkinterdnd2 未安装")
        return 0
    tmp = tempfile.mkdtemp(prefix="prism_dnd_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    try:
        pump(app, 25)
        empty = os.path.join(tmp, "empty")
        os.makedirs(empty)
        a = os.path.join(empty, "a one.jpg")
        b = os.path.join(empty, "b two.png")
        Image.new("RGB", (80, 60), (200, 160, 140)).save(a)
        Image.new("RGB", (60, 80), (120, 160, 200)).save(b)
        far = os.path.join(tmp, "far")
        os.makedirs(far)
        c = os.path.join(far, "c.jpg")
        Image.new("RGB", (40, 40), (130, 180, 130)).save(c)

        ok("主窗口注册拖放", getattr(app, "_drop_registered", False))
        ok("画布注册拖放", getattr(app.canvas, "_drop_registered", False))
        ok("工具栏注册拖放", getattr(app.bar, "_drop_registered", False))
        ok("状态栏注册拖放", getattr(app.status, "_drop_registered", False))

        app._on_drop(Drop("{%s}" % a))
        pump(app, 35)
        ok("拖入带空格路径", bool(app.files) and app.files[0] == a)
        ok("拖入后已载入图片", app.doc is not None and app.error is None,
           str(app.error)[:40])

        app._on_drop(Drop("{%s}" % empty))
        pump(app, 30)
        ok("拖入文件夹", app.folder == empty and len(app.files) == 2,
           "%d 张" % len(app.files))

        app._on_drop(Drop("{%s} {%s}" % (far, b)))
        pump(app, 30)
        ok("混合拖入优先文件", c not in app.files and b in app.files,
           "%s" % [os.path.basename(x) for x in app.files[:3]])

        before = list(app.files)
        app._on_drop(Drop("{C:\\definitely\\missing\\nope.jpg}"))
        pump(app, 5)
        ok("非法路径不改变当前文件", app.files == before)

        app.toggle_panel(True)
        pump(app, 30)
        ok("面板打开后注册拖放",
           getattr(app, "panel", None) is not None
           and getattr(app.panel, "_drop_registered", False))
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 拖入打开回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 拖入打开回归通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
