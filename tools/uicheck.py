# -*- coding: utf-8 -*-
"""界面/性能回归：全分辨率、1:1、专注模式、面板拖宽、性能档位、设置窗口。"""
import importlib.machinery
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    tmp = tempfile.mkdtemp(prefix="prism_ui_")
    from PIL import Image
    paths = []
    for i, color in enumerate(((90, 120, 160), (160, 110, 90))):
        sub = os.path.join(tmp, "shot%d" % i)
        os.makedirs(sub)
        p = os.path.join(sub, "big.jpg")
        im = Image.new("RGB", (5000, 4000), color)
        for x in range(0, 5000, 125):
            for y in range(0, 4000, 125):
                im.paste(((x + y + i * 40) % 256, (x * 2) % 256,
                          (y * 2) % 256), (x, y, x + 125, y + 125))
        im.save(p, quality=85)
        paths.append(p)

    mod = importlib.machinery.SourceFileLoader(
        "ui960", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    mod._data_dir = lambda: tmp
    mod.AUTO_DRAFT_PIXELS = 2000000      # 6MP 图也走自动降档
    app = mod.QPEApp()
    for _ in range(20):
        app.update(); time.sleep(0.01)
    try:
        # 1) 降档 + F5 取回全分辨率
        app.open_files([paths[0]])
        t0 = time.time()
        while time.time() - t0 < 30:
            app.update(); time.sleep(0.02)
            if getattr(app, "doc", None) is not None:
                break
        for _ in range(30):
            app.update(); time.sleep(0.02)
        doc = app.doc
        ok("大图自动降档", doc is not None and doc.size != doc.orig_size,
           "%s / %s" % (doc.size if doc else None,
                        getattr(doc, "orig_size", None)))
        ok("降档标记", bool(getattr(doc, "auto_drafted", False)))
        ok("状态栏入口可见", bool(app.full_btn.winfo_ismapped()))
        app.load_full_resolution()
        t0 = time.time()
        while time.time() - t0 < 30:
            app.update(); time.sleep(0.02)
            if app.doc is not None and app.doc.size == app.doc.orig_size:
                break
        ok("F5 取回原图", app.doc.size == app.doc.orig_size,
           str(app.doc.size))
        ok("取回后入口隐藏", not app.full_btn.winfo_ismapped())

        # 2) 1:1 自动取回原图
        app.open_files([paths[1]])
        t0 = time.time()
        while time.time() - t0 < 30:
            app.update(); time.sleep(0.02)
            if getattr(app, "doc", None) is not None:
                break
        for _ in range(20):
            app.update(); time.sleep(0.02)
        app.actual_size()
        t0 = time.time()
        while time.time() - t0 < 30:
            app.update(); time.sleep(0.02)
            if app.doc is not None and app.doc.size == app.doc.orig_size:
                break
        ok("1:1 自动取回原图", app.doc.size == app.doc.orig_size,
           str(app.doc.size))
        ok("1:1 缩放为 100%", abs(app.scale - 1.0) < 1e-6,
           "%.3f" % app.scale)

        # 3) 专注模式
        app.toggle_panel(True)
        for _ in range(5):
            app.update(); time.sleep(0.01)
        app.toggle_focus_mode()
        for _ in range(5):
            app.update(); time.sleep(0.01)
        ok("专注模式隐藏工具栏", not app.bar.winfo_ismapped())
        ok("专注模式隐藏状态栏", not app.status.winfo_ismapped())
        ok("专注模式隐藏面板", not app.panel.winfo_ismapped())
        app.toggle_focus_mode()
        for _ in range(5):
            app.update(); time.sleep(0.01)
        ok("退出专注恢复工具栏", app.bar.winfo_ismapped())
        ok("退出专注恢复状态栏", app.status.winfo_ismapped())
        ok("退出专注恢复面板", app.panel.winfo_ismapped())

        # 4) 面板拖宽 + 持久化
        class E:
            x_root = 0
        before = app.panel.winfo_width()
        app._panel_drag = (before + 200, before)
        app._panel_drag_move(E())
        for _ in range(5):
            app.update(); time.sleep(0.01)
        after = app.panel.winfo_width()
        ok("面板可拖宽", after > before, "%d -> %d" % (before, after))
        app._panel_drag_end(E())
        saved = json.load(open(app._settings_path(), encoding="utf-8"))
        ok("面板宽度已保存", int(saved.get("panel_w", 0)) == app.panel_width,
           str(saved.get("panel_w")))
        app._panel_drag_reset()
        ok("双击恢复默认宽度", app.panel_width == mod.px(238))

        # 5) 性能档位
        app.set_perf_profile("fast-first")
        ok("档位立即生效", mod.PERF_PROFILE == "fast-first",
           mod.PERF_PROFILE)
        saved = json.load(open(app._settings_path(), encoding="utf-8"))
        ok("档位已保存", saved.get("perf_profile") == "fast-first",
           str(saved.get("perf_profile")))
        app.set_perf_profile("fast-slider")

        # 6) 设置窗口
        app.show_settings()
        for _ in range(20):
            app.update(); time.sleep(0.01)
        tops = [w for w in app.winfo_children()
                if isinstance(w, mod.tk.Toplevel)]
        ok("设置窗口能打开", len(tops) >= 1, "%d 个" % len(tops))
        for w in tops:
            try:
                w.destroy()
            except Exception:
                pass
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 界面/性能回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 界面/性能回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
