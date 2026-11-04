# -*- coding: utf-8 -*-
"""大屏版回归：模式识别、底部大按钮、无快捷键、无面板。"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []

# Windows 默认 GBK 控制台无法编码底栏的 ◀/▶；测试脚本被 Prism 的
# excepthook 捕获时还会误报成「启动失败」。这里只降级无法编码的字符，
# 保留中文和正常输出。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except Exception:
        pass


def ok(name, cond, detail=""):
    print("  %s %-32s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    from PIL import Image
    sys.argv = ["bigscreencheck", "--bigscreen"]
    mod = importlib.machinery.SourceFileLoader(
        "big9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    tmp = tempfile.mkdtemp(prefix="prism_big_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    for _ in range(40):
        app.update(); time.sleep(0.01)
    try:
        ok("识别大屏模式", mod.BIGSCREEN is True and mod.VIEWER_ONLY is True)
        ok("面板不构建", app.panel is None)
        ok("工具栏在底部", app.bar.pack_info().get("side") == "bottom",
           str(app.bar.pack_info().get("side")))
        texts = []

        def collect(w):
            for child in w.winfo_children():
                if isinstance(child, mod.tk.Button):
                    texts.append(child.cget("text"))
                collect(child)

        collect(app.bar)
        for label in ("打开", "文件夹", "幻灯片", "全屏", "退出"):
            ok("底栏按钮 " + label, label in texts, str(texts[:6]))
        ok("无 F5 快捷键", not app.bind("<F5>"))
        ok("无 Ctrl+O 快捷键", not app.bind("<Control-o>"))
        _l, _t, aw, ah = mod._work_area()
        ok("大屏窗口不出屏",
           app.winfo_x() >= _l and app.winfo_y() >= _t
           and app.winfo_x() + app.winfo_width() <= _l + aw
           and app.winfo_y() + app.winfo_height() <= _t + ah,
           "%dx%d+%d+%d / %dx%d" % (app.winfo_width(), app.winfo_height(),
                                    app.winfo_x(), app.winfo_y(), aw, ah))

        p = os.path.join(tmp, "a.jpg")
        Image.new("RGB", (800, 600), (90, 120, 160)).save(p)
        app.open_files([p])
        t0 = time.time()
        while time.time() - t0 < 20:
            app.update(); time.sleep(0.01)
            if app.doc is not None:
                break
        ok("大屏能打开图片", app.doc is not None and app.doc.size == (800, 600))
        ok("底栏有画笔", "画笔" in texts, str(texts[:9]))
        ok("画笔工具条已建", app.brush_palette is not None)
        app.toggle_brush()
        app.update()
        ok("画笔开启", app.brush_on and app.brush_palette.winfo_ismapped())
        pb = app.brush_palette
        canvas_bottom = app.canvas.winfo_rooty() + app.canvas.winfo_height()
        ok("画笔工具条在底部",
           abs(pb.winfo_rooty() + pb.winfo_height() - canvas_bottom) <= 16,
           "%d/%d" % (pb.winfo_rooty() + pb.winfo_height(), canvas_bottom))
        ok("画笔工具条不挡状态栏",
           pb.winfo_rooty() + pb.winfo_height() <= app.status.winfo_rooty() + 2)
        app._on_press(SimpleNamespace(x=2, y=2))
        app._on_drag(SimpleNamespace(x=20, y=20))
        app._on_release(SimpleNamespace(x=20, y=20))
        ok("图像外不起笔", not app.brush_strokes and not app.brush_items)
        im = app._view_image()
        bx, by = app._image_to_canvas(im.size[0] * 0.45, im.size[1] * 0.55)
        app._on_press(SimpleNamespace(x=bx, y=by))
        app._on_drag(SimpleNamespace(x=bx + 40, y=by + 25))
        app._on_release(SimpleNamespace(x=bx + 40, y=by + 25))
        ok("画笔落笔", len(app.brush_strokes) == 1 and bool(app.brush_items))
        app._brush_undo_action()
        ok("画笔撤销", not app.brush_strokes and not app.brush_items)
        app._set_brush_color("#ffd666")
        app._brush_size_by(2)
        bx, by = app._image_to_canvas(im.size[0] * 0.55, im.size[1] * 0.45)
        app._on_press(SimpleNamespace(x=bx, y=by))
        app._on_drag(SimpleNamespace(x=bx + 40, y=by + 25))
        app._on_release(SimpleNamespace(x=bx + 40, y=by + 25))
        ok("画笔颜色/粗细", len(app.brush_strokes) == 1
           and app.brush_strokes[0]["color"] == "#ffd666")
        sizes = [s for _sc, s, _dot in app.brush_size_btns]
        ok("画笔三档", sizes == [4, 10, 20], str(sizes))
        app.brush_size_btns[-1][0].event_generate("<Button-1>", x=2, y=2)
        app.update()
        ok("点击三档按钮", abs(app.brush_size - 20) < 0.01,
           "%.0f" % app.brush_size)

        # 区域橡皮：画一条横线，在中间擦一刀，应断成两条而不是整条消失。
        app._brush_clear()
        app.brush_undo = []
        app._set_brush_size(10)
        if app.brush_eraser:
            app._toggle_brush_eraser()
        im = app._view_image()
        x0, y0 = app._image_to_canvas(im.size[0] * 0.25, im.size[1] * 0.5)
        x1, y1 = app._image_to_canvas(im.size[0] * 0.75, im.size[1] * 0.5)
        app._on_press(SimpleNamespace(x=x0, y=y0))
        for i in range(1, 11):
            app._on_drag(SimpleNamespace(
                x=x0 + (x1 - x0) * i / 10.0,
                y=y0 + (y1 - y0) * i / 10.0))
        app._on_release(SimpleNamespace(x=x1, y=y1))
        n_points = len(app.brush_strokes[0]["points"]) if app.brush_strokes else 0
        ok("区域橡皮准备", len(app.brush_strokes) == 1 and n_points >= 5,
           "%d 点" % n_points)
        app._toggle_brush_eraser()
        mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        app._on_motion(SimpleNamespace(x=mx, y=my))
        app.update()
        ok("橡皮区域显示",
           app.brush_cursor_item is not None
           and app.canvas.type(app.brush_cursor_item) == "oval")
        undo_before = len(app.brush_undo)
        app._on_press(SimpleNamespace(x=mx, y=my))
        ok("区域擦除断开笔迹", len(app.brush_strokes) == 2,
           "%d 段" % len(app.brush_strokes))
        app._on_release(SimpleNamespace(x=mx, y=my))
        ok("区域擦除一次撤销", len(app.brush_undo) == undo_before + 1,
           "%d -> %d" % (undo_before, len(app.brush_undo)))
        app._brush_undo_action()
        ok("区域擦除可撤销",
           len(app.brush_strokes) == 1
           and len(app.brush_strokes[0]["points"]) == n_points)
        if app.brush_eraser:
            app._toggle_brush_eraser()
        s0 = app.scale
        app._on_pinch(SimpleNamespace(delta=120, x=400, y=300))
        ok("双指捏合放大", app.scale > s0, "%.3f -> %.3f" % (s0, app.scale))

        p2 = os.path.join(tmp, "b.jpg")
        Image.new("RGB", (640, 480), (160, 90, 60)).save(p2)
        app.open_files([p, p2])
        for _ in range(100):
            app.update()
            time.sleep(0.01)
            if app.doc is not None and app.index == 0:
                break
        app.goto(1)
        for _ in range(100):
            app.update()
            time.sleep(0.01)
            if app.index == 1 and app.doc is not None:
                break
        ok("换图清空画笔", app.index == 1 and not app.brush_on
           and not app.brush_strokes
           and not app.brush_palette.winfo_ismapped())
        app.geometry("1366x768")
        for _ in range(30):
            app.update()
            time.sleep(0.01)
        app._layout_bigscreen_bar()
        app.update()
        right = max((w.winfo_x() + w.winfo_width())
                    for w in app.bar.winfo_children())
        ok("1366 底栏不溢出", right <= app.bar.winfo_width() + 2,
           "%d/%d %s" % (right, app.bar.winfo_width(), app._big_mode))
        ok("1366 显示画笔", app._big_brush_btn.winfo_ismapped())
        app.toggle_panel(True)
        ok("大屏没有修图面板", app.panel is None)
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 大屏版回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 大屏版回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
