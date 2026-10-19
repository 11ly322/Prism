# -*- coding: utf-8 -*-
"""插件异步路径回归：点「运行插件」后主线程必须立刻返回、结果窗口必须出现。

跑法： python tools/plugincheck.py
"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    mod = importlib.machinery.SourceFileLoader("pc", APP).load_module()
    tmp = os.path.join(tempfile.gettempdir(), "_prism_plugcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    plugin = os.path.join(tmp, "gray.py")
    open(plugin, "w", encoding="utf-8").write(
        'PLUGIN = {"id": "gray", "name": "灰度", "version": "1", "api": 2,\n'
        '          "author": "test", "description": "回归用"}\n'
        'PARAMS = [{"key": "amount", "label": "强度", "type": "slider",\n'
        '           "min": 0, "max": 100, "default": 50}]\n'
        'def run(img, **params):\n'
        '    return img.convert("L").convert("RGB")\n')
    big = os.path.join(tmp, "big.jpg")
    Image.new("RGB", (4000, 3000), (170, 140, 120)).save(big, quality=80)
    mod._plugin_dir = lambda: tmp
    S = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(S):
        os.remove(S)

    import tkinter as tk
    app = mod.QPEApp()
    for _ in range(25):
        app.update(); time.sleep(0.01)
    app.open_files([big])
    for _ in range(140):
        app.update(); time.sleep(0.01)
        if app.doc is not None:
            break
    ok("打开测试图", app.doc is not None,
       str(None if app.doc is None else app.doc.img.size))

    app._scan_plugins()
    ok("扫描到插件", len(app.plugins) >= 1, "%d 个" % len(app.plugins))
    if not app.plugins:
        app.destroy()
        return 1
    item = app.plugins[0]
    spec = app._plugin_params_spec(item)
    ok("控件类型解析", [p["type"] for p in spec] == ["range"],
       str([p["type"] for p in spec]))

    # 三语标签：label/name/description 可以是 {zh,en,ja}
    class _FakeMod:
        PARAMS = [{"key": "x", "type": "slider", "min": 0, "max": 1,
                   "default": 0,
                   "label": {"zh": "强度", "en": "Strength", "ja": "強さ"}}]
    fake_item = {"module": _FakeMod, "id": "fake"}
    old_lang = mod.APP_LANG
    for lang, want in (("en", "Strength"), ("ja", "強さ"), ("zh", "强度")):
        mod.APP_LANG = lang
        got = app._plugin_params_spec(fake_item)[0]["label"]
        ok("参数标签本地化 " + lang, got == want, got)
    mod.APP_LANG = old_lang

    before = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    t0 = time.perf_counter()
    app.run_plugin(item)
    ret_ms = (time.perf_counter() - t0) * 1000
    ok("主线程立即返回", ret_ms < 80, "%.1f ms" % ret_ms)

    found = None
    for _ in range(600):
        app.update(); time.sleep(0.01)
        tops = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
        if len(tops) > len(before):
            found = (time.perf_counter() - t0) * 1000
            break
    ok("结果窗口出现", found is not None,
       ("%.0f ms" % found) if found else "未出现")
    ok("异步不阻塞界面", ret_ms < (found or 1e9), "返回 %.1f < 窗口 %.0f" % (ret_ms, found or 0))

    # --- 参数记忆（9.4）---
    print("--- 插件参数持久化 ---")
    item = app.plugins[0]
    app._remember_plugin_params(item, {"amount": 73.5})
    ok("记住本次参数", app._plugin_params(item, spec).get("amount") == 73.5,
       str(app._plugin_params(item, spec)))
    app.plug_params = {}                 # 模拟重启：内存清空，只从设置文件读
    app.load_settings()
    ok("重启后恢复", app._plugin_params(item, spec).get("amount") == 73.5,
       str(app.plug_params.get("gray")))
    app._remember_plugin_params(item, {"amount": 999})
    ok("越界收敛到上限", app._plugin_params(item, spec).get("amount") == 100.0,
       str(app._plugin_params(item, spec).get("amount")))
    app._remember_plugin_params(item, {"amount": "abc"})
    ok("坏值回落默认", app._plugin_params(item, spec).get("amount") == 50,
       str(app._plugin_params(item, spec).get("amount")))
    choice = [{"key": "mode", "label": "模式", "type": "choice",
               "choices": ["a", "b"], "default": "a", "min": 0, "max": 1,
               "step": 1}]
    app._remember_plugin_params(item, {"mode": "zzz"})
    ok("失效选项回落默认", app._plugin_params(item, choice)["mode"] == "a")
    app._forget_plugin_params(item)
    ok("恢复默认会清空记忆", app._plugin_params(item, spec).get("amount") == 50
       and "gray" not in app.plug_params)

    # 禁用 -> 重新启用（回归：启用时把 gray.py 砍成 gr，静默失败）
    app._scan_plugins()
    gray = next(p for p in app.plugins if p["id"] == "gray")
    app._set_plugin_enabled(gray, False)
    app.update()
    ok("禁用后改名为 .disabled",
       os.path.exists(os.path.join(tmp, "gray.py.disabled"))
       and not os.path.exists(os.path.join(tmp, "gray.py")))
    ok("禁用后插件列表为空", not any(p["id"] == "gray" for p in app.plugins))
    # 走插件窗口的实际路径：已禁用列表里传的是 "gray.py"
    app._set_plugin_enabled({"file": "gray.py"}, True)
    app.update()
    ok("重新启用恢复 .py",
       os.path.exists(os.path.join(tmp, "gray.py"))
       and not os.path.exists(os.path.join(tmp, "gray.py.disabled")))
    ok("重新启用后能扫描到", any(p["id"] == "gray" for p in app.plugins))
    # 直接传 .disabled 全名也要能接住
    app._set_plugin_enabled({"file": "gray.py"}, False)
    app._set_plugin_enabled({"file": "gray.py.disabled"}, True)
    ok("传 .disabled 全名也能启用",
       os.path.exists(os.path.join(tmp, "gray.py")))

    # 重复 id：第二个同名插件的文件要被跳过，并出现在错误列表里
    dup = os.path.join(tmp, "gray_dup.py")
    open(dup, "w", encoding="utf-8").write(
        'PLUGIN = {"id": "gray", "name": "重复", "version": "1", "api": 2}\n'
        'def run(img, **params):\n    return img\n')
    app._scan_plugins()
    ok("重复 id 只保留一个",
       sum(1 for p in app.plugins if p["id"] == "gray") == 1,
       "%d 个" % sum(1 for p in app.plugins if p["id"] == "gray"))
    ok("重复 id 记入错误列表",
       any("重复" in str(e) for _f, e in app.plugin_errors),
       str(app.plugin_errors[-1:]))
    os.remove(dup)

    # 安装窗口能打开（只建界面，不发网络请求）
    tops_before = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    app.show_plugin_install()
    for _ in range(20):
        app.update(); time.sleep(0.01)
    tops_now = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel)]
    ok("网址安装窗口能打开", len(tops_now) > len(tops_before),
       "%d -> %d" % (len(tops_before), len(tops_now)))
    for w in tops_now:
        if w not in tops_before:
            w.destroy()
    app.update()

    # 语言不被 save_settings 整份覆盖（旧 bug）
    app.lang = "ja"
    app._save_setting("lang", "ja")
    app.save_settings()
    import json
    with open(S, encoding="utf-8") as fh:
        saved = json.load(fh)
    ok("save_settings 保留语言", saved.get("lang") == "ja", str(saved.get("lang")))

    app.destroy()
    if os.path.exists(S):
        os.remove(S)
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 插件异步路径回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
