# -*- coding: utf-8 -*-
"""批量导出异步回归：解码/保存走后台，主线程仍能更新进度。"""
import importlib.machinery
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    from PIL import Image
    mod = importlib.machinery.SourceFileLoader(
        "batch9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    tmp = tempfile.mkdtemp(prefix="prism_batch_")
    mod._data_dir = lambda: tmp
    app = mod.QPEApp()
    for _ in range(20):
        app.update(); time.sleep(0.01)
    try:
        src = os.path.join(tmp, "src")
        out = os.path.join(tmp, "out")
        os.makedirs(src); os.makedirs(out)
        files = []
        for i in range(3):
            p = os.path.join(src, "img%d.jpg" % i)
            im = Image.new("RGB", (640, 480), (40 + i * 30, 90, 150))
            for x in range(0, 640, 64):
                for y in range(0, 480, 64):
                    im.putpixel((x, y), (x % 256, y % 256, i * 60))
            im.save(p, quality=88)
            files.append(p)

        win = mod.tk.Toplevel(app)
        app.batch_win = win
        app.b_bar = mod.tk.Canvas(win, width=200, height=10)
        app.b_msg = mod.tk.Label(win)
        app.b_go = mod.tk.Button(win)
        app.b_stop_btn = mod.tk.Button(win)
        app.b_files = files
        app.b_out_dir = out
        app.b_ext = ".jpg"
        app.b_fmt_name = "JPEG"
        app.b_quality = 85
        app.b_maxlong = 0
        app.adj["exposure"] = 0.35
        app.adj["vignette"] = 30
        app.adj["skin_smooth"] = 25
        app.wm_text = "TEST"
        app.wm_pos = "br"
        app.wm_size = 4
        app.b_use_adj = True
        app.b_overwrite = False
        app.b_i = 0
        app.b_ok = 0
        app.b_fail = []
        app.b_stop = False
        app.b_busy = False
        app._batch_tick()

        t0 = time.time()
        ticks = 0
        while time.time() - t0 < 30:
            app.update(); time.sleep(0.01); ticks += 1
            if app.b_i >= len(files) and not app.b_busy:
                break
        ok("批量全部处理", app.b_i == len(files), "%d/%d" % (app.b_i,
                                                         len(files)))
        ok("全部成功", app.b_ok == len(files) and not app.b_fail,
           "ok=%d fail=%d" % (app.b_ok, len(app.b_fail)))
        ok("主线程仍在泵事件", ticks > 10, "%d ticks" % ticks)
        outs = [os.path.join(out, "img%d.jpg" % i) for i in range(3)]
        ok("输出文件已写入", all(os.path.isfile(p) for p in outs))
        sizes = []
        for p in outs:
            with Image.open(p) as im:
                sizes.append(im.size)
        ok("输出尺寸正确", all(s == (640, 480) for s in sizes), str(sizes))
    finally:
        try:
            if getattr(app, "batch_win", None) is not None:
                app.batch_win.destroy()
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 批量导出回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 批量导出回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
