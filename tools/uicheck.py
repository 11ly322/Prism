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

        # 3) 最近打开
        ok("最近打开记录第一张", paths[0] in app.recent, str(len(app.recent)))
        ok("最近打开置顶第二张", app.recent and app.recent[0] == paths[1],
           str(app.recent[:1]))
        ok("最近打开菜单有项", app._recent_menu.index("end") is not None)
        app.clear_recent()
        ok("清空最近打开", app.recent == [], str(app.recent))

        # 4) 专注模式（面板懒构建：打开前应为 None）
        ok("面板启动不构建", app.panel is None)
        app.toggle_panel(True)
        for _ in range(5):
            app.update(); time.sleep(0.01)
        ok("首次打开才构建面板", app.panel is not None)
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
        ok("双击恢复默认宽度", app.panel_width == mod.px(260))

        # 4b) 右侧面板排版：固定顶部/固定底栏/折叠工具区
        ok("面板固定顶部存在", app.panel_top.winfo_ismapped())
        ok("面板固定底栏存在", app.panel_footer.winfo_ismapped())
        ok("面板底栏四个主操作",
           all(w.winfo_exists() for w in (app.hist_undo_btn,
                                          app.hist_redo_btn,
                                          app.cmp_btn, app.save_btn)))
        ok("面板滚动条为自绘", isinstance(app.psb, mod.tk.Canvas),
           app.psb.winfo_class())
        tool_body, _tool_toggle = app.sections["工具"]
        ok("工具分类默认隐藏", not tool_body.winfo_ismapped())
        ok("工具区控件已建好", app.hist_box.winfo_exists()
           and app.sort_btn.winfo_exists())
        app.set_panel_tab("tools")
        for _ in range(8):
            app.update(); time.sleep(0.01)
        ok("工具分类可切换", tool_body.winfo_ismapped()
           and app.panel_boxes["tools"].winfo_ismapped())
        ok("工具区不再重复设置/过曝/取色按钮",
           app.theme_btn is None and app.clip_btn is None
           and app.pick_btn is None)
        labels = []
        for _m in getattr(app, "_menus", []):
            if isinstance(_m, mod.tk.Menu):
                try:
                    for _i in range(int(_m.index("end")) + 1):
                        try:
                            labels.append(_m.entrycget(_i, "label"))
                        except Exception:
                            pass
                except Exception:
                    pass
        ok("文件菜单有图片信息", "图片信息" in labels)
        body_b, toggle_b = app.sections.get("人像美化", (None, None))
        ok("人像美化只有一个分区", body_b is not None
           and "人像 · 高级" not in app.sections)
        app.set_panel_tab("adjust")
        for _ in range(30):
            app.update(); time.sleep(0.01)
        app.update_idletasks()
        if body_b is not None and not body_b.winfo_ismapped():
            toggle_b()
            for _ in range(50):
                app.update(); time.sleep(0.01)
            app.update_idletasks()
        presets = getattr(app, "beauty_preset_btns", {})
        ok("美颜预设四个按钮", len(presets) == 4, str(len(presets)))
        ok("美颜预设不截断",
           bool(presets) and all(b.winfo_width() + 1 >= b.winfo_reqwidth()
                                 for b in presets.values()),
           str([(b._text, b.winfo_width(), b.winfo_reqwidth())
                for b in presets.values()]))
        for _lang in ("en", "ja"):
            app.lang = _lang
            mod.APP_LANG = _lang
            app._apply_lang()
            for _ in range(12):
                app.update(); time.sleep(0.01)
            app.update_idletasks()
            ok("美颜预设不截断 %s" % _lang,
               all(b.winfo_width() + 1 >= b.winfo_reqwidth()
                   for b in presets.values()),
               str([(b._text, b.winfo_width(), b.winfo_reqwidth())
                    for b in presets.values()]))
        app.lang = "zh"
        mod.APP_LANG = "zh"
        app._apply_lang()
        for _ in range(12):
            app.update(); time.sleep(0.01)
        app.set_panel_tab("adjust")
        for _ in range(8):
            app.update(); time.sleep(0.01)
        ok("调整分类可回切", app.panel_boxes["adjust"].winfo_ismapped()
           and not app.panel_boxes["tools"].winfo_ismapped())
        for _group in ("color", "detail", "effect", "presets", "tools",
                       "adjust"):
            app.set_panel_tab(_group)
            for _ in range(3):
                app.update(); time.sleep(0.01)
            only = [g for g, box in app.panel_boxes.items()
                    if box.winfo_ismapped()]
            ok("分类切换：%s" % _group, only == [_group], str(only))

        # 5) 性能档位
        app.set_perf_profile("fast-first")
        ok("档位立即生效", mod.PERF_PROFILE == "fast-first",
           mod.PERF_PROFILE)
        saved = json.load(open(app._settings_path(), encoding="utf-8"))
        ok("档位已保存", saved.get("perf_profile") == "fast-first",
           str(saved.get("perf_profile")))
        app.set_perf_profile("fast-slider")

        # 6) 全分辨率计时反馈
        app.full_loading = app.doc.path
        app.full_started = time.time() - 1.3
        app._full_tick()
        ok("全分辨率显示已用时间", "1." in app.full_btn.cget("text"),
           app.full_btn.cget("text"))
        app.full_loading = None
        app._stop_full_timer()
        app._set_full_btn_busy(False)

        # 7) 软打样（有系统 profile 才测，CI 的 Linux/macOS 会跳过）
        prof = ""
        if os.name == "nt":
            import glob
            base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                "System32", "spool", "drivers", "color")
            for p in glob.glob(os.path.join(base, "*.[iI][cC][cCmM]")):
                if "adobergb" in os.path.basename(p).lower():
                    prof = p
                    break
        if prof:
            ok("软打样能启用", bool(app.set_soft_proof_profile(prof)),
               app.soft_proof_name)
            ok("软打样状态已记录", bool(app.soft_proof
                                        and app.soft_proof_transforms))
            app.toggle_soft_proof(False)
            ok("软打样能关闭", not app.soft_proof)
        else:
            print("  SKIP 软打样（没有系统 AdobeRGB profile）")

        # 7) 设置窗口
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
