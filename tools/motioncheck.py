# -*- coding: utf-8 -*-
"""动效 / 点击反馈 / 主题标记回归。"""
import importlib.machinery
import json
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


def pump(app, n=20):
    for _ in range(n):
        app.update()
        time.sleep(0.01)


def main():
    mod = importlib.machinery.SourceFileLoader(
        "motion9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    tmp = tempfile.mkdtemp(prefix="prism_motion_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    try:
        pump(app, 30)
        ok("默认开启动效", app.motion is True and mod.MOTION_ENABLED is True)
        app.show_settings()
        pump(app, 40)
        ok("设置页有动效卡片",
           getattr(app, "motion_card", None) is not None
           and app.motion_card.winfo_exists())
        ok("动效开关状态同步",
           getattr(app, "motion_var", None) is not None
           and app.motion_var.get() == 1)

        # 主题网格的选中标记
        marks = getattr(app, "_theme_marks", {})
        ok("主题网格有选中标记", len(marks) == len(mod.THEME_ORDER),
           str(len(marks)))
        ok("当前主题标记用强调色",
           marks.get(app.theme) is not None
           and str(marks[app.theme].cget("bg")).lower() == mod.ACCENT.lower(),
           marks.get(app.theme).cget("bg") if marks.get(app.theme) else "none")

        # 圆角按钮：开启动效时按下有反馈，关闭后立即无反馈
        state = {"n": 0}
        btn = mod._QpeRoundButton(app, text="demo",
                                  command=lambda: state.__setitem__("n", 1),
                                  bg=mod.BTN_BG, fg=mod.FG,
                                  hover_bg=mod.BAR_HOVER, hover_fg=mod.FG_HI)
        btn.pack()
        pump(app, 5)
        btn._on_enter()
        pump(app, 3)
        ok("悬停是连续缓动", 0.0 < btn._hover_t < 1.0, "%.2f" % btn._hover_t)
        pump(app, 22)
        ok("悬停到达终值", btn._hover_t > 0.98, "%.2f" % btn._hover_t)
        btn.invoke()
        ok("按钮命令执行", state["n"] == 1)
        ok("按钮按下反馈", btn._press is True and btn._press_t > 0.0,
           "%.2f" % btn._press_t)
        ok("点击有涟漪", btn._ripple_t > 0.0, "%.2f" % btn._ripple_t)
        pump(app, 20)
        ok("按钮反馈复位", btn._press is False)
        pump(app, 20)
        ok("按钮回弹结束", btn._press_t == 0.0, "%.2f" % btn._press_t)
        ok("涟漪淡出结束", btn._ripple_t == 0.0, "%.2f" % btn._ripple_t)
        btn.destroy()

        # 原生按钮的按下反馈（设置/插件/工具条菜单共用）
        std = mod.tk.Button(app, text="std", bg=mod.BTN_BG, fg=mod.FG)
        std.pack()
        app._wire_press(std, mod.BTN_BG, mod.ACCENT, mod.ON_BG)
        pump(app, 3)
        std.event_generate("<ButtonPress-1>")
        pump(app, 10)
        ok("原生按钮按下反馈",
           str(std.cget("bg")).lower() == mod.ACCENT.lower(), std.cget("bg"))
        std.event_generate("<ButtonRelease-1>")
        pump(app, 20)
        ok("原生按钮松开复位",
           str(std.cget("bg")).lower() == mod.BTN_BG.lower(), std.cget("bg"))
        std.destroy()

        # 工具条自绘图标按钮：按下时底色/图标反色
        icon = None

        def find_icon(w):
            nonlocal icon
            for ch in w.winfo_children():
                if icon is not None:
                    return
                if getattr(ch, "find_withtag", None):
                    try:
                        if ch.find_withtag("rbg"):
                            icon = ch
                            return
                    except Exception:
                        pass
                find_icon(ch)

        find_icon(app.bar)
        if icon is not None:
            icon.event_generate("<ButtonPress-1>")
            pump(app, 8)
            fills = [icon.itemcget(i, "fill")
                     for i in icon.find_withtag("rbg")]
            ok("图标按钮按下反馈",
               bool(fills) and str(fills[0]).lower() == mod.ACCENT.lower(),
               str(fills[:1]))
            icon.event_generate("<ButtonRelease-1>")
            pump(app, 12)
        else:
            ok("图标按钮存在", False)

        switch = getattr(app, "motion_switch", None)
        ok("设置页有自绘开关",
           switch is not None and switch.winfo_exists())
        switch.invoke()
        pump(app, 25)
        ok("关闭后总开关同步",
           app.motion is False and mod.MOTION_ENABLED is False)
        ok("关闭后勾选状态同步", app.motion_var.get() == 0)
        ok("开关圆钮动画到位", switch._t == 0.0, "%.2f" % switch._t)
        with open(os.path.join(tmp, "Prism_settings.json"), "r",
                  encoding="utf-8") as fh:
            saved = json.load(fh)
        ok("动效设置已保存", saved.get("motion") is False, saved.get("motion"))

        btn2 = mod._QpeRoundButton(
            app, text="demo2", command=lambda: None,
            bg=mod.BTN_BG, fg=mod.FG, hover_bg=mod.BAR_HOVER,
            hover_fg=mod.FG_HI)
        btn2.pack()
        pump(app, 3)
        btn2.invoke()
        ok("关闭后无按压反馈", btn2._press is False)
        ok("关闭后无涟漪", btn2._ripple_t == 0.0, "%.2f" % btn2._ripple_t)
        btn2.destroy()

        app.set_motion(True)
        pump(app, 25)
        app._flash("动效状态测试")
        app.update()
        ok("状态反馈从强调色开始",
           str(app.meta_lbl.cget("fg")).lower() == mod.ACCENT.lower(),
           app.meta_lbl.cget("fg"))
        pump(app, 30)
        ok("状态反馈渐变回落",
           str(app.meta_lbl.cget("fg")).lower() == mod.FG_DIM.lower(),
           app.meta_lbl.cget("fg"))
        ok("重新开启总开关",
           app.motion is True and mod.MOTION_ENABLED is True)
        ok("重新开启勾选状态", app.motion_var.get() == 1)
        ok("开关圆钮回到开启位", switch._t > 0.98, "%.2f" % switch._t)
        try:
            app.set_win.destroy()
            pump(app, 4)
        except Exception:
            pass
        ok("关闭设置后解除开关 trace", switch._trace is None)

        # 切主题后标记仍跟随；关闭动效不影响主题/A11y
        app.show_settings()
        pump(app, 30)
        app.set_theme("paper")
        pump(app, 25)
        marks = getattr(app, "_theme_marks", {})
        ok("切主题后标记跟随",
           str(marks[app.theme].cget("bg")).lower() == mod.ACCENT.lower(),
           marks[app.theme].cget("bg"))
        app.set_motion(False)
        app.set_theme("dark")
        pump(app, 20)
        ok("关闭动效仍可切主题", app.theme == "dark")
        app.set_motion(True)
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 动效回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 动效回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
