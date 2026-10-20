# -*- coding: utf-8 -*-
"""浅色/深色主题回归：面板、设置、底栏、自绘按钮不能残留深色。"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-32s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def lum(hex_color):
    h = str(hex_color).lstrip("#")
    if len(h) != 6:
        return None
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    mod = importlib.machinery.SourceFileLoader(
        "theme9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    tmp = tempfile.mkdtemp(prefix="prism_theme_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    try:
        for _ in range(40):
            app.update(); time.sleep(0.01)
        app.toggle_panel(True)
        for _ in range(30):
            app.update(); time.sleep(0.01)
        app.show_settings()
        for _ in range(60):
            app.update(); time.sleep(0.01)
        wrap = app.pcan.winfo_children()[0]
        inner = wrap.winfo_children()[0]

        for name in ("light", "dark", "light"):
            app.set_theme(name)
            for _ in range(40):
                app.update(); time.sleep(0.01)
            pal = mod.THEMES[name]
            ok("%s 全局 PANEL" % name, mod.PANEL_BG == pal["PANEL"],
               mod.PANEL_BG)
            ok("%s 面板底色" % name, inner.cget("bg") == pal["PANEL"],
               inner.cget("bg"))
            ok("%s 设置窗口底色" % name,
               app.set_win.cget("bg") == pal["PANEL"], app.set_win.cget("bg"))
            ok("%s 工具条在顶部" % name,
               app.bar.pack_info().get("side") == "top"
               and app.bar.winfo_y() == 0, str(app.bar.winfo_y()))

            rbg = []

            def scan_icons(w):
                for ch in w.winfo_children():
                    if getattr(ch, "find_withtag", None):
                        try:
                            for item in ch.find_withtag("rbg"):
                                rbg.append(ch.itemcget(item, "fill"))
                        except Exception:
                            pass
                    scan_icons(ch)

            scan_icons(app.bar)
            ok("%s 自绘图标底色" % name,
               bool(rbg) and all(str(c).lower() == pal["BAR_BG"].lower()
                                 for c in rbg), str(rbg[:2]))

            rounds = []

            def walk(w):
                for ch in w.winfo_children():
                    if isinstance(ch, mod._QpeRoundButton):
                        rounds.append(ch)
                    walk(ch)

            walk(app.bar)
            ok("%s 圆角按钮底色" % name,
               bool(rounds) and all(
                   str(b._bg).lower() == pal["BAR_BG"].lower() for b in rounds),
               str([b._bg for b in rounds[:2]]))

            if name == "light":
                ok("浅色面板是亮色", (lum(inner.cget("bg")) or 0) > 180,
                   inner.cget("bg"))
                ok("浅色正文是深色", (lum(mod.FG) or 255) < 100, mod.FG)
                ok("浅色棋盘格是亮色", (lum(mod.CHECK_A) or 0) > 180,
                   mod.CHECK_A)
                ok("浅色工具条是亮色", (lum(app.bar.cget("bg")) or 0) > 180,
                   app.bar.cget("bg"))
            else:
                ok("深色面板是暗色", (lum(inner.cget("bg")) or 255) < 80,
                   inner.cget("bg"))
                ok("深色棋盘格是暗色", (lum(mod.CHECK_A) or 255) < 80,
                   mod.CHECK_A)

        ok("棋盘格随主题更新", mod.CHECK_A == mod.THEMES["light"]["CHECK_A"],
           mod.CHECK_A)
        ok("BG_RGB 随主题更新", mod.BG_RGB == (0xf4, 0xf4, 0xf4), str(mod.BG_RGB))
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 主题回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 主题回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
