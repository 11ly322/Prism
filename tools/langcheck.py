# -*- coding: utf-8 -*-
"""三语界面回归：中 → 英 → 日 切换后，各窗口的文字必须真的跟着变。

不只查词典覆盖率（tools/i18ncheck_app.py），还要打开每个窗口取实际控件文字，
因为「词条在词典里」和「界面用上了」是两件事。

跑法： python tools/langcheck.py
"""
import importlib.machinery
import json
import os
import shutil
import tempfile
import time

import tkinter as tk
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
SETTINGS = os.path.join(ROOT, "src", "Prism_settings.json")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-40s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def collect(w, out):
    """把一棵控件树上的可见文字收集起来，用于断言。"""
    try:
        cls = w.winfo_class()
    except Exception:
        return
    if isinstance(w, tk.Toplevel):
        try:
            out.append("TITLE:" + w.title())
        except Exception:
            pass
    if "_QpeRoundButton" in globals() and isinstance(w, _QpeRoundButton):
        out.append(str(getattr(w, "_text", "")))
    try:
        if cls in ("Label", "Button", "Checkbutton", "Radiobutton", "Menubutton"):
            out.append(str(w.cget("text")))
        elif cls == "Text":
            out.append(w.get("1.0", "end"))
    except Exception:
        pass
    for ch in w.winfo_children():
        collect(ch, out)


def wait(app, ms):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            app.update()
        except Exception:
            return
        time.sleep(0.01)


def main():
    global _QpeRoundButton
    mod = importlib.machinery.SourceFileLoader("lc", APP).load_module()
    _QpeRoundButton = mod._QpeRoundButton
    print("=== 三语界面 v%s ===" % mod.APP_VERSION)
    tmp = os.path.join(tempfile.gettempdir(), "_prism_langcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    for i in range(2):
        Image.new("RGB", (320, 240), (90 + i * 40, 120, 160)).save(
            os.path.join(tmp, "p%d.jpg" % i), quality=88)
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)

    app = mod.QPEApp()
    errors = []
    app.report_callback_exception = lambda e, v, tb: errors.append(
        "%s: %s" % (e.__name__, v))
    wait(app, 400)
    app.open_files([os.path.join(tmp, "p0.jpg")])
    wait(app, 1200)

    def switch(lang):
        app.lang = lang
        mod.APP_LANG = lang
        app._save_setting("lang", lang)
        app._build_bar()
        app._apply_lang()
        wait(app, 400)

    def probe(method, *args, **kw):
        before = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        try:
            getattr(app, method)(*args, **kw)
        except Exception as exc:
            errors.append("%s: %r" % (method, exc))
            return []
        wait(app, 500)
        now = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        texts = []
        for w in now:
            if w not in before:
                collect(w, texts)
                try:
                    w.destroy()
                except Exception:
                    pass
        wait(app, 120)
        return texts

    checks = [
        ("设置", "show_settings", "Language", "言語"),
        ("插件", "show_plugins", "Installed plugins", "インストール済みプラグイン"),
        ("安装插件", "show_plugin_install", "Plugin URL (.py)", "プラグインの URL（.py）"),
        ("批量重命名", "batch_rename", "Start rename", "名前変更を開始"),
        ("批量导出", "batch_export", "Batch export", "一括書き出し"),
        ("图片信息", "show_info", "Current adjustments", "現在の調整"),
        ("关于", "show_about", "accurate color", "色が正確"),
        ("快捷键", "show_help",
         ("Shortcuts - Prism", "Open folder", "Actual size 100%"),
         ("ショートカット - Prism", "フォルダーを開く", "原寸 100%")),
    ]
    for lang, idx in (("en", 2), ("ja", 3)):
        print("--- 切到 %s ---" % lang)
        switch(lang)
        # 打开图片时标题是「文件名 - Prism」，没有语言成分；临时清空文档看空窗口标题
        saved_doc, saved_files = app.doc, app.files
        app.doc, app.files = None, []
        app._update_title()
        title = app.title()
        app.doc, app.files = saved_doc, saved_files
        app._update_title()
        want_title = "image viewer" if lang == "en" else "画像ビューア"
        ok("%s 主窗口标题" % lang, want_title in title, repr(title))
        for name, method, token_en, token_ja in checks:
            token = token_en if lang == "en" else token_ja
            tokens = token if isinstance(token, tuple) else (token,)
            texts = probe(method)
            blob = "\n".join(texts)
            missing = [t for t in tokens if t not in blob]
            ok("%s 窗口：%s" % (lang, name), not missing,
               "找到 %s" % " / ".join(tokens) if not missing
               else "缺 %s" % missing)

    # 运行时文案（带 % 的模板）必须能还原出译文
    mod.APP_LANG = "en"
    cases = [("已保存 a.jpg", "Saved a.jpg"),
             ("旋转 45°", "Rotate 45°"),
             ("批量导出完成：成功 12 张", "Batch export complete: 12 exported")]
    for src, want in cases:
        got = mod._trf(src)
        ok("运行时文案 %s" % src, got == want, "%r -> %r" % (src, got))

    mod.APP_LANG = "ja"
    ok("运行时文案 ja", mod._trf("已保存 a.jpg") == "a.jpg を保存しました",
       repr(mod._trf("已保存 a.jpg")))

    ok("界面无回调异常", not errors, str(errors[:3]))
    app.destroy()
    shutil.rmtree(tmp, ignore_errors=True)
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)
    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 三语界面回归通过")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
