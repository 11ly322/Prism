# -*- coding: utf-8 -*-
"""一条命令跑完所有回归，输出一张总表。

跑法：
    python tools/runall.py            # 全量（含 selfcheck / newcheck / beauty / uishot）
    python tools/runall.py --fast     # 发布门禁用：跳过耗时的视觉与全量回归
    python tools/runall.py --only plugincheck,marketcheck
"""
import argparse
import io
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (名字, 脚本, 参数, 是否属于快跑, 超时秒)
SUITES = [
    ("词条", "tools/i18ncheck_app.py", ["--strict"], True, 60),
    ("插件索引", "tools/make_plugin_index.py", ["--check"], True, 60),
    ("三语文档", "tools/docscheck.py", [], True, 60),
    ("文档 HTML", "tools/make_docs_html.py", ["--check"], True, 60),
    # 版本号不放在这里：发布前页面还停留在上一版，由 make_release 在更新页面后单独检查
    ("URL 安装", "tools/plugininstallcheck.py", [], True, 120),
    ("清单", "tools/plugincatalogcheck.py", [], True, 120),
    ("清单静态", "tools/pluginprcheck.py", [], True, 60),
    ("插件回归", "tools/plugincheck.py", [], True, 180),
    ("市场界面", "tools/marketcheck.py", [], True, 180),
    ("三语界面", "tools/langcheck.py", [], True, 240),
    ("导入冒烟", "tools/importcheck.py", [], True, 120),
    ("界面/性能", "tools/uicheck.py", [], True, 240),
    ("ICC", "tools/icccheck.py", [], True, 60),
    ("ICC 真profile", "tools/iccprofilecheck.py", [], True, 60),
    ("补充功能", "tools/newcheck.py", [], False, 300),
    ("自检", "tools/selfcheck.py", [], False, 420),
    ("美颜", "tools/beautycheck.py", [], False, 420),
    ("外观截图", "tools/uishot.py", [], False, 300),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="只跑快跑套件")
    ap.add_argument("--only", default="", help="逗号分隔的套件名")
    args = ap.parse_args()
    picked = [s for s in SUITES if not args.fast or s[3]]
    if args.only:
        names = {x.strip() for x in args.only.split(",") if x.strip()}
        def _match(s):
            return (s[0] in names
                    or os.path.basename(s[1]) in names
                    or os.path.splitext(os.path.basename(s[1]))[0] in names)
        picked = [s for s in picked if _match(s)]
    if not picked:
        print("没有匹配的套件")
        return 2

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    rows, failed = [], []
    for name, script, extra, _fast, timeout in picked:
        t0 = time.time()
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(ROOT, script)] + extra,
                cwd=ROOT, capture_output=True, timeout=timeout, env=env)
            code = proc.returncode
            out = (proc.stdout or b"").decode("utf-8", "replace")
            err = (proc.stderr or b"").decode("utf-8", "replace")
            tail = (out + err).strip().splitlines()[-1:] or [""]
        except subprocess.TimeoutExpired:
            code, tail = 124, ["超时（%d 秒）" % timeout]
        except Exception as exc:
            code, tail = 1, [str(exc)]
        secs = time.time() - t0
        rows.append((name, script, code, secs, tail[0][:90]))
        if code != 0:
            failed.append((name, tail[0][:200]))
        print("  %s %-10s %-30s %5.1fs  %s" % (
            "PASS" if code == 0 else "FAIL", name, os.path.basename(script),
            secs, tail[0][:80]))

    print()
    print("== 汇总 ==")
    print("  套件 %d 个，通过 %d，失败 %d，总耗时 %.1fs" % (
        len(rows), len(rows) - len(failed), len(failed), time.time() - started))
    if failed:
        for name, msg in failed:
            print("  !! %s: %s" % (name, msg))
        return 1
    print(">>> 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
