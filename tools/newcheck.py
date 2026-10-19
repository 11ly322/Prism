# -*- coding: utf-8 -*-
"""新功能补充测试：镜头 / 胶片 / 插件 / 菜单 / 撤销

美颜模块的完整回归见 tools/beautycheck.py。
"""
import importlib.machinery, os, shutil, time
import numpy as np
import tkinter as tk
from PIL import Image, ImageDraw

APP = r"D:\pictu\src\Prism.pyw"
WORK = os.path.join(os.environ.get("TEMP", "."), "_prism_new")
FAIL = []

def ok(name, cond, detail=""):
    if cond:
        print("  PASS %-30s %s" % (name, detail))
    else:
        FAIL.append(name)
        print("  FAIL %-30s %s" % (name, detail))

shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
mod = importlib.machinery.SourceFileLoader("psc", APP).load_module()
print("=== 补充测试 v%s ===" % mod.APP_VERSION)

S = os.path.join(r"D:\pictu\src", "Prism_settings.json")
if os.path.exists(S): os.remove(S)
app = mod.QPEApp()
for _ in range(40): app.update(); time.sleep(0.02)

im = Image.new("RGB", (800, 600))
d = ImageDraw.Draw(im)
for y in range(600):
    d.line([(0, y), (800, y)], fill=(40 + y // 6, 70, 120))
d.ellipse([250, 140, 550, 460], fill=(226, 183, 158))
im.save(os.path.join(WORK, "a.jpg"), quality=90)
app.open_files([os.path.join(WORK, "a.jpg")])
for _ in range(70): app.update(); time.sleep(0.02)
base = app._flatten().convert("RGB")

def run_with(patch):
    app.adj = mod.QPEApp._default_adj()
    app.adj.update(patch)
    app.geom_key = None
    app.detail_cache.clear()
    out = app._flatten().convert("RGB")
    a0 = np.asarray(base, np.int16); a1 = np.asarray(out, np.int16)
    if a0.shape != a1.shape: return None
    return float(np.abs(a1 - a0).mean())

print("--- 1. 镜头畸变矫正 ---")
for v in (40.0, -40.0):
    dd = run_with({"lens": v})
    ok("畸变 %+.0f" % v, dd is not None and dd > 0.5, "平均差 %.2f" % (dd or 0))
ok("畸变 0 是中性", run_with({"lens": 0.0}) == 0.0)

print("--- 2. 胶片模拟 ---")
for name in ("柯达暖调", "富士艳丽", "伊尔福黑白", "宝丽来"):
    dd = run_with({"film": name})
    ok("胶片 %s" % name, dd is not None and dd > 1.0, "平均差 %.2f" % (dd or 0))
ok("胶片 无 是中性", run_with({"film": "无"}) == 0.0)
ok("强度 0 = 不改变", run_with({"film": "柯达暖调", "film_strength": 0}) == 0.0)

print("--- 3. 人像美化（无脸时降级）---")
dd = run_with({"skin_smooth": 70.0, "skin_glow": 50.0})
ok("肤色柔化+提亮生效", dd is not None and dd > 0.0, "平均差 %.2f" % (dd or 0))

print("--- 4. 美颜模块 ---")
print("  SKIP 美颜细节已移至 tools/beautycheck.py（22 项）")

print("--- 5. 插件系统 ---")
pdir = mod._plugin_dir()
for f in os.listdir(pdir):
    p2 = os.path.join(pdir, f)
    shutil.rmtree(p2, ignore_errors=True) if os.path.isdir(p2) else os.remove(p2)
for fn in os.listdir(r"D:\pictu\plugins"):
    if fn.endswith(".py"):
        shutil.copy(os.path.join(r"D:\pictu\plugins", fn), os.path.join(pdir, fn))
app._scan_plugins()
ok("自带插件全部加载", len(app.plugins) >= 9, "实际 %d" % len(app.plugins))
ok("无加载错误", not app.plugin_errors, str(app.plugin_errors))
for item in app.plugins:
    spec = app._plugin_params_spec(item)
    params = app._plugin_defaults(spec)
    try:
        out = app._call_plugin(item, base.copy(), None, params)
        ok("插件运行:%s" % item["name"], out is not None and hasattr(out, "size"),
           "%d 个可调项" % len(spec))
    except Exception as exc:
        ok("插件运行:%s" % item["name"], False, str(exc))

print("--- 6. 菜单与快捷键 ---")
mbs = []
def walk(w):
    for c in w.winfo_children():
        if isinstance(c, tk.Menubutton): mbs.append(c)
        walk(c)
walk(app.bar)
ok("五个菜单", [m.cget("text") for m in mbs] == ["文件","编辑","视图","工具","帮助"],
   str([m.cget("text") for m in mbs]))
menus = [m for m in getattr(app, "_menus", []) if isinstance(m, tk.Menu)]
total = 0
for mn in menus:
    for i in range(40):
        try:
            if mn.type(i) != "separator": total += 1
        except Exception:
            break
ok("菜单项数量 >40", total > 40, "%d 项" % total)
ok("全屏为兼容模式", hasattr(app, "toggle_fullscreen"))
ok("F11 绑定切全屏", bool(app.bind("<F11>")))

print("--- 7. 撤销/快照 ---")
app.adj = mod.QPEApp._default_adj()
app.adj["exposure"] = 1.0
app._push_history("测试")
n0 = len(app.history)
app.undo()
for _ in range(10): app.update(); time.sleep(0.01)
ok("撤销可回退", abs(app.adj["exposure"]) < 0.01, "曝光 %.2f" % app.adj["exposure"])
app.destroy()
for f in os.listdir(pdir):
    p2 = os.path.join(pdir, f)
    shutil.rmtree(p2, ignore_errors=True) if os.path.isdir(p2) else os.remove(p2)
if os.path.exists(S): os.remove(S)
shutil.rmtree(WORK, ignore_errors=True)
print()
if FAIL:
    print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
else:
    print(">>> 补充测试全部通过")
