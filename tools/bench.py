# -*- coding: utf-8 -*-
"""可复现的性能基准：启动、4000 万像素首帧、滑杆延迟、代理图、解码路径 Mpx/s。

用法：
    python tools/bench.py                 # 单轮
    python tools/bench.py --repeat 3      # 三轮取中位数（子进程隔离，内存口径可信）
    python tools/bench.py --proxy 2400    # 指定代理图上限
    python tools/bench.py --json          # 追加写入 tools/bench-results.json

--repeat 每一轮都在独立子进程里跑：Tk 资源与 PIL 缓冲不会跨轮累积，
所以内存峰值是真实值（早期版本同进程连跑会虚高 60%+）。
"""
import importlib.machinery
import json
import os
import platform
import shutil
import subprocess
import sys
import time

from PIL import Image

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "src", "Prism.pyw")
WORK = os.path.join(os.environ.get("TEMP", "."), "_prism_bench")
BIG = (8000, 5000)          # 4000 万像素


def mem_mb():
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        fn = getattr(k32, "K32GetProcessMemoryInfo", None) or ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        fn.restype = wintypes.BOOL
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        if not fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return 0.0, 0.0
        return pmc.WorkingSetSize / 1048576.0, pmc.PeakWorkingSetSize / 1048576.0
    except Exception:
        return 0.0, 0.0


def machine():
    info = {"os": platform.platform(), "python": platform.python_version(),
            "cpu": "", "ram_gb": 0.0, "machine": platform.machine()}
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "(Get-CimInstance Win32_Processor).Name;"
                              "[math]::Round((Get-CimInstance Win32_ComputerSystem)"
                              ".TotalPhysicalMemory/1GB,1)"],
                             capture_output=True, text=True, timeout=25)
        lines = [x.strip() for x in out.stdout.splitlines() if x.strip()]
        if lines:
            info["cpu"] = lines[0]
        if len(lines) > 1:
            info["ram_gb"] = float(lines[1])
    except Exception:
        pass
    return info


def mpix(w, h):
    return (w * h) / 1e6


def _arg_value(name, cast=int):
    for i, a in enumerate(sys.argv):
        if a == name and i + 1 < len(sys.argv):
            try:
                return cast(sys.argv[i + 1])
            except Exception:
                return None
        if a.startswith(name + "="):
            try:
                return cast(a.split("=", 1)[1])
            except Exception:
                return None
    return None


def ensure_big():
    """生成（并缓存）一张「真实感」4000 万像素测试图。

    早期版本用纯色图，压完只有 0.6MB、解码 30ms，解码与内存类优化在基准里
    根本体现不出来（曾经因此误判过一次）。现在用「低频块 + 高频噪声」，
    体积约 18MB，更接近真实照片的可压缩性。生成一次约 8 秒，之后复用缓存。
    """
    os.makedirs(WORK, exist_ok=True)
    big = os.path.join(WORK, "real40mp.jpg")
    if not os.path.exists(big):
        try:
            import numpy as np
            rng = np.random.default_rng(7)
            low = rng.normal(0, 40, (63, 100, 3))
            low = np.array(Image.fromarray(((low + 128).clip(0, 255)).astype("uint8"))
                           .resize(BIG, Image.BICUBIC), dtype=np.float32)
            base = (low + rng.normal(0, 18, (BIG[1], BIG[0], 3))).clip(0, 255).astype("uint8")
            Image.fromarray(base).save(big, quality=90)
        except Exception:
            Image.new("RGB", BIG, (180, 150, 130)).save(big, quality=88)
    return big


def apply_proxy(mod):
    sl = _arg_value("--slack", float)
    if sl:
        mod.DRAFT_SLACK = max(0.3, min(1.0, sl))
    n = _arg_value("--proxy", int)
    if n:
        mod.PROXY_ARG = n
    return getattr(mod, "PROXY_ARG", 0) or getattr(mod, "PREVIEW_MAX", 0)


def once(big):
    """跑一轮（在调用它的进程内），返回指标字典。"""
    S = os.path.join(os.path.dirname(APP), "Prism_settings.json")
    if os.path.exists(S):
        os.remove(S)
    t0 = time.perf_counter()
    mod = importlib.machinery.SourceFileLoader("bench", APP).load_module()
    limit = apply_proxy(mod)
    app = mod.QPEApp()
    for _ in range(30):
        app.update(); time.sleep(0.01)
    t_boot = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    app.open_files([big])
    first = None
    for _ in range(400):
        app.update()
        if getattr(app, "surface_img", None) is not None:
            first = (time.perf_counter() - t0) * 1000
            break
        time.sleep(0.005)
    for _ in range(20):
        app.update(); time.sleep(0.01)

    lat = []
    for v in (0.2, 0.4, 0.6, 0.8, 1.0):
        app.adj["exposure"] = v
        app._mark_fast()
        t0 = time.perf_counter()
        app._render(fast=True)
        app.update()
        lat.append((time.perf_counter() - t0) * 1000)

    proxy_ms = None
    try:
        src = app._view_image()
        if src is not None:
            app.preview_key = None
            t0 = time.perf_counter()
            mod.QPEApp._preview_of(app, src)
            proxy_ms = (time.perf_counter() - t0) * 1000
    except Exception:
        pass

    app.toggle_low_mem()
    for _ in range(10):
        app.update(); time.sleep(0.01)
    ws, peak = mem_mb()
    try:
        app.toggle_fullscreen(); app.update(); app._exit_fullscreen()
    except Exception:
        pass
    app.destroy()
    if os.path.exists(S):
        os.remove(S)
    return {"startup_ms": t_boot, "first": first,
            "slider": sum(lat) / len(lat), "proxy": proxy_ms,
            "ws": ws, "peak": peak, "limit": limit,
            "version": getattr(mod, "APP_VERSION", "?")}


def run_pipeline_cost(big_path):
    from PIL import Image as I
    res = {}

    def timed(label, fn):
        t0 = time.perf_counter()
        img = fn()
        dt = time.perf_counter() - t0
        w, h = img.size
        res[label] = {"ms": dt * 1000.0, "mp": round(mpix(w, h), 2),
                      "mp_s": round(mpix(w, h) / max(1e-9, dt), 2),
                      "size": [w, h]}
        return img

    def draft_path():
        im = I.open(big_path)
        im.draft("RGB", (1600, 1000))
        im.load()
        return im
    timed("draft_1600", draft_path)

    def full_path():
        im = I.open(big_path)
        im.load()
        return im
    full = timed("load_full", full_path)
    timed("reduce4_resize1600", lambda: full.reduce(4).resize((1600, 1000), I.LANCZOS))
    timed("resize1600_only", lambda: full.resize((1600, 1000), I.LANCZOS))
    del full
    return res


def _median(vals):
    vals = sorted(v for v in vals if v is not None and v >= 0)
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0


def _bind_cpus(n):
    """把当前进程绑定到前 n 个逻辑核（Windows）。子进程会继承。"""
    if not n or n <= 0:
        return 0
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        mask = (1 << n) - 1
        return 1 if k32.SetProcessAffinityMask(
            k32.GetCurrentProcess(), ctypes.c_size_t(mask)) else 0
    except Exception:
        return 0


def child_main():
    """子进程模式：跑一轮，把结果打成一行 JSON。"""
    cpus = _arg_value("--cpu", int) or 0
    bound = _bind_cpus(cpus)
    big = ensure_big()
    r = once(big)
    r["cpu_bound"] = cpus if bound else 0
    r["paths"] = {} if ("--_no-paths" in sys.argv or "--no-paths" in sys.argv)         else run_pipeline_cost(big)
    sys.stdout.write("BENCH_JSON:" + json.dumps(r, ensure_ascii=False) + chr(10))
    return 0


def main():
    if "--_child" in sys.argv:
        return child_main()

    asked = _arg_value("--repeat", int) or 1
    # 单轮会被抖动带偏（实测同配置两次可有 397ms 与 781ms 的差别），
    # 少于 3 轮直接抬到 3 轮，宁可多跑几秒也不要假数据。
    repeat = max(3, min(9, asked))
    if asked < 3:
        print("提示：--repeat 少于 3 会自动按 3 轮跑（单轮数据不可信）")
    want_json = "--json" in sys.argv
    note = ""
    for i, a in enumerate(sys.argv):
        if a == "--note" and i + 1 < len(sys.argv):
            note = sys.argv[i + 1]
        elif a.startswith("--note="):
            note = a.split("=", 1)[1]
    info = machine()
    big = ensure_big()

    print("测试机：%s | %s | %.1f GB | Python %s"
          % (info["cpu"] or "?", info["os"], info["ram_gb"] or 0, info["python"]))
    if repeat > 1:
        print("重复 %d 轮（子进程隔离，内存口径可信），指标取中位数" % repeat)
    print("-" * 68)

    runs = []
    base = [sys.executable, os.path.abspath(__file__), "--_child"]
    if _arg_value("--proxy", int):
        base += ["--proxy", str(_arg_value("--proxy", int))]
    if _arg_value("--cpu", int):
        base += ["--cpu", str(_arg_value("--cpu", int))]
    if _arg_value("--slack", float):
        base += ["--slack", str(_arg_value("--slack", float))]
    prof = _arg_value("--perf-profile", str)
    if prof:
        base += ["--perf-profile", prof]
    if "--no-paths" in sys.argv or "--_no-paths" in sys.argv:
        base += ["--_no-paths"]
    for k in range(repeat):
        try:
            out = subprocess.run(base, capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", timeout=300)
        except Exception as exc:
            print("  第 %d 轮失败：%s" % (k + 1, exc))
            continue
        got = None
        for line in (out.stdout or "").splitlines():
            if line.startswith("BENCH_JSON:"):
                try:
                    got = json.loads(line[len("BENCH_JSON:"):])
                except Exception:
                    got = None
        if got is None:
            print("  第 %d 轮无数据（stderr 前两行：%s）"
                  % ((k + 1), " / ".join((out.stderr or "").splitlines()[:2])))
            continue
        runs.append(got)
        if repeat > 1:
            print("  第 %d 轮：启动 %.0f ms  首帧 %.0f ms  滑杆 %.0f ms  内存 %.0f/%.0f MB"
                  % (k + 1, got["startup_ms"], got["first"] or -1,
                     got["slider"], got["ws"], got["peak"]))

    if not runs:
        print("没有拿到任何有效数据，检查上面的报错。")
        return 1

    def _stats(vals):
        vals = sorted(v for v in vals if v is not None and v >= 0)
        if not vals:
            return 0.0, 0.0, 0.0, 0.0
        n = len(vals)
        med = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2.0
        lo, hi = vals[0], vals[-1]
        mean = sum(vals) / float(n)
        var = sum((v - mean) ** 2 for v in vals) / float(n)
        return med, lo, hi, var ** 0.5

    t_boot = _median([r["startup_ms"] for r in runs])
    first = _median([r["first"] for r in runs])
    lat_mean = _median([r["slider"] for r in runs])
    proxy_ms = _median([r["proxy"] for r in runs])
    ws = _median([r["ws"] for r in runs])
    peak = _median([r["peak"] for r in runs])
    limit = runs[-1].get("limit", 0)
    paths = runs[-1].get("paths", {})

    b_med, b_lo, b_hi, b_sd = _stats([r["startup_ms"] for r in runs])
    f_med, f_lo, f_hi, f_sd = _stats([r["first"] for r in runs])
    s_med, s_lo, s_hi, s_sd = _stats([r["slider"] for r in runs])
    bound = runs[-1].get("cpu_bound", 0)
    print("代理图上限              %6d%s" % (limit, ("   核数绑定 %d" % bound) if bound else ""))
    print("启动到可交互            %6.0f ms   中位 %.0f / 最小 %.0f / 最大 %.0f / 标准差 %.0f"
          % (t_boot or 0, b_med, b_lo, b_hi, b_sd))
    print("40MP 首帧（打开→可见）  %6.0f ms   中位 %.0f / 最小 %.0f / 最大 %.0f / 标准差 %.0f"
          % (first if first else -1, f_med, f_lo, f_hi, f_sd))
    print("滑杆预览延迟（5 次均值）%6.0f ms   中位 %.0f / 最小 %.0f / 最大 %.0f / 标准差 %.0f"
          % (lat_mean or 0, s_med, s_lo, s_hi, s_sd))
    print("代理图生成（主线程）    %s" % ("%.0f ms" % proxy_ms if proxy_ms is not None else "n/a"))
    print("内存（当前 / 峰值）     %.0f / %.0f MB" % (ws or 0, peak or 0))
    print("-" * 68)
    print("%-22s %8s %8s %10s %12s" % ("解码路径", "耗时ms", "Mpx", "Mpx/s", "输出尺寸"))
    for k in ("draft_1600", "load_full", "reduce4_resize1600", "resize1600_only"):
        v = paths.get(k)
        if not v:
            continue
        print("%-22s %8.0f %8.1f %10.1f %12s" % (
            k, v["ms"], v["mp"], v["mp_s"], "%dx%d" % tuple(v["size"])))
    print("-" * 68)
    print("（数字随机器浮动；用 --repeat 3 取中位数后再对比。）")

    out = {"machine": info, "app_version": runs[-1].get("version", "?"),
           "startup_ms": round(t_boot or 0, 1),
           "first_frame_40mp_ms": round(first or -1, 1),
           "slider_ms": round(lat_mean or 0, 1),
           "proxy_ms": round(proxy_ms, 1) if proxy_ms is not None else None,
           "mem_current_mb": round(ws or 0, 1), "mem_peak_mb": round(peak or 0, 1),
           "repeat": repeat, "proxy_limit": limit, "note": note, "paths": paths}
    if want_json:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "bench-results.json")
        old = {}
        if os.path.exists(p):
            try:
                old = json.load(open(p, encoding="utf-8"))
            except Exception:
                old = {}
        data = {"machine": info, "runs": old.get("runs", [])}
        def _key(r):
            return (r.get("app_version"), r.get("proxy_limit"),
                    (r.get("note") or "")[:24])
        kept = [r for r in data["runs"] if _key(r) != _key(out)]
        data["runs"] = kept + [out]
        json.dump(data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("已写入 tools/bench-results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
