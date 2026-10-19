# -*- coding: utf-8 -*-
"""发布后线上验收：版本号、下载链接、清单、插件文件、三语文档。

跑法：
    python tools/verifysite.py                 # 用 src 里的版本号
    python tools/verifysite.py --ver 9.6.0 --wait 300

只做 GET/HEAD，不改任何东西；失败返回 1。
"""
import argparse
import importlib.machinery
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
BASE = "https://11ly322.github.io/Prism/"
UA = {"User-Agent": "Prism-verifysite"}
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-38s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def fetch(url, method="GET", timeout=25, headers=None):
    hdrs = dict(UA)
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def check_download(url):
    """GitHub Release 的 HEAD 有时被对象存储拒绝，退回 Range GET 只取 1 字节。"""
    last = None
    for _ in range(3):
        try:
            return fetch(url, method="HEAD")[0]
        except Exception as exc:
            last = exc
        try:
            return fetch(url, method="GET",
                         headers={"Range": "bytes=0-0"})[0]
        except Exception as exc:
            last = exc
        time.sleep(5)
    raise last


def get_with_retry(url, deadline, interval=10, method="GET"):
    last = None
    while time.time() < deadline:
        try:
            return fetch(url, method=method, timeout=20)
        except urllib.error.HTTPError as exc:
            last = "HTTP %s" % exc.code
        except Exception as exc:
            last = str(exc)
        time.sleep(interval)
    raise RuntimeError("%s 一直失败：%s" % (url, last))


def get_retry(url, tries=3, interval=5):
    """部署等待结束后，单条检查自己重试，避免被别的慢请求耗尽总预算。"""
    last = None
    for _ in range(tries):
        try:
            return fetch(url, timeout=25)
        except Exception as exc:
            last = exc
            time.sleep(interval)
    raise last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ver", default="")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--wait", type=int, default=3600)
    args = ap.parse_args()
    ver = args.ver
    if not ver:
        src = open(APP, encoding="utf-8").read()
        ver = re.search(r'APP_VERSION = "([^"]+)"', src).group(1)
    base = args.base.rstrip("/") + "/"
    deadline = time.time() + args.wait
    print("=== 线上验收 %s（最多等 %d 秒）===" % (ver, args.wait))

    stamp = str(int(time.time()))
    try:
        code, body = get_with_retry(base + "?cb=" + stamp, deadline)
        html = body.decode("utf-8", "replace")
        ok("首页 200", code == 200, str(code))
        ok("首页版本", 'data-ver="%s"' % ver in html, "期望 " + ver)
        ok("首页有下载链接",
           ("/v%s/" % ver) in html and ("Prism-Setup-%s.exe" % ver) in html)
        assets = sorted(set(re.findall(
            r'https://github\.com/11ly322/Prism/releases/download/v[^"/]+/[^"]+',
            html)))
        ok("页面 release 链接", len(assets) >= 6, "%d 条" % len(assets))
    except Exception as exc:
        ok("首页", False, str(exc))
        assets = []

    for asset in assets:
        name = asset.rsplit("/", 1)[-1]
        try:
            status = check_download(asset)
            ok("下载 " + name, status in (200, 206), str(status))
        except Exception as exc:
            ok("下载 " + name, False, str(exc))

    for lang, needle in (("", 'data-ver="%s"' % ver),
                         ("en/", 'data-ver="%s"' % ver),
                         ("ja/", 'data-ver="%s"' % ver)):
        try:
            code, body = get_retry(
                base + lang + "?cb=" + str(int(time.time())))
            text = body.decode("utf-8", "replace")
            ok("语言页 " + (lang or "zh"), code == 200 and needle in text,
               str(code))
        except Exception as exc:
            ok("语言页 " + (lang or "zh"), False, str(exc))

    try:
        code, body = get_retry(base + "plugins/index.json")
        mod = importlib.machinery.SourceFileLoader(
            "vs", APP).load_module()
        entries = mod.validate_plugin_catalog(json.loads(body.decode("utf-8")))
        ok("插件清单", code == 200 and len(entries) >= 1,
           "%d 个" % len(entries))
    except Exception as exc:
        ok("插件清单", False, str(exc))
        entries = []

    for entry in entries:
        try:
            status, body = fetch(entry["url"])
            import hashlib
            good = hashlib.sha256(body).hexdigest() == entry["sha256"]
            ok("清单插件 " + entry["id"], status == 200 and good,
               "sha " + ("OK" if good else "BAD"))
        except Exception as exc:
            ok("清单插件 " + entry["id"], False, str(exc))

    for doc in ("plugin-api.md", "plugin-api.en.md", "plugin-api.ja.md",
                "plugin-guide.html", "plugin-guide.en.html",
                "plugin-guide.ja.html"):
        try:
            status, _ = get_retry(base + doc)
            ok("文档 " + doc, status == 200, str(status))
        except Exception as exc:
            ok("文档 " + doc, False, str(exc))

    print()
    if FAIL:
        print(">>> 线上验收失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 线上验收通过（%s）" % ver)
    return 0


if __name__ == "__main__":
    sys.exit(main())
