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


def _rel_lum(hex_color):
    def channel(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    h = str(hex_color).lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    l1, l2 = _rel_lum(a), _rel_lum(b)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


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

        ok("主题数量", len(mod.THEME_ORDER) >= 10,
           str(len(mod.THEME_ORDER)))
        ok("主题无重复", len(set(mod.THEME_ORDER)) == len(mod.THEME_ORDER))
        radios = []

        def scan_radios(w):
            for ch in w.winfo_children():
                if isinstance(ch, mod.tk.Radiobutton):
                    radios.append(ch)
                scan_radios(ch)

        scan_radios(app.set_win)
        ok("设置里列出全部主题", len(radios) >= len(mod.THEME_ORDER) + 3,
           "%d radios" % len(radios))

        for name in mod.THEME_ORDER:
            app.set_theme(name)
            for _ in range(25):
                app.update(); time.sleep(0.008)
            pal = mod.THEMES[name]
            missing = [r for r in mod._THEME_ROLES if r not in pal]
            ok("%s 角色完整" % name, not missing, str(missing))
            ok("%s 面板底色" % name, inner.cget("bg") == pal["PANEL"],
               inner.cget("bg"))
            ok("%s 设置窗口底色" % name,
               app.set_win.cget("bg") == pal["PANEL"], app.set_win.cget("bg"))
            ok("%s 工具条在顶部" % name,
               app.bar.pack_info().get("side") == "top"
               and app.bar.winfo_y() == 0, str(app.bar.winfo_y()))
            ok("%s 正文可读" % name, contrast(mod.FG, pal["PANEL"]) >= 4.0,
               "%.1f:1" % contrast(mod.FG, pal["PANEL"]))
            ok("%s 强调色可读" % name, contrast(pal["ON"], pal["ACCENT"]) >= 3.0,
               "%.1f:1" % contrast(pal["ON"], pal["ACCENT"]))
            if (lum(pal["PANEL"]) or 0) > 128:
                ok("%s 浅色配套" % name,
                   (lum(mod.FG) or 255) < 110
                   and (lum(mod.CHECK_A) or 0) > 180,
                   "%s / %s" % (mod.FG, mod.CHECK_A))
            else:
                fg_l = lum(mod.FG) or 0
                chk_l = lum(mod.CHECK_A)
                ok("%s 深色配套" % name,
                   fg_l > 150 and chk_l is not None and chk_l < 100,
                   "%s / %s" % (mod.FG, mod.CHECK_A))

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
        ok("自绘图标底色", bool(rbg)
           and all(str(c).lower() == mod.BAR_BG.lower() for c in rbg),
           str(rbg[:2]))

        rounds = []

        def walk(w):
            for ch in w.winfo_children():
                if isinstance(ch, mod._QpeRoundButton):
                    rounds.append(ch)
                walk(ch)

        walk(app.bar)
        ok("圆角按钮底色", bool(rounds)
           and all(str(b._bg).lower() == mod.BAR_BG.lower() for b in rounds),
           str([b._bg for b in rounds[:2]]))

        ok("棋盘格随主题更新",
           mod.CHECK_A == mod.THEMES[mod.THEME_ORDER[-1]]["CHECK_A"],
           mod.CHECK_A)
        ok("BG_RGB 随主题更新",
           mod.BG_RGB == tuple(int(mod.BG[i:i + 2], 16) for i in (1, 3, 5)),
           str(mod.BG_RGB))
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
