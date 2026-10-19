# -*- coding: utf-8 -*-
"""插件市场界面回归：状态显示 / 一键安装 / 更新 / 哈希不符拒绝。

不需要外网：本地 HTTP 服务提供清单与插件文件；应用的数据目录、插件目录都指向临时目录。
跑法： python tools/marketcheck.py
"""
import http.server
import importlib.machinery
import json
import os
import shutil
import socketserver
import tempfile
import threading
import time

import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
INDEX = os.path.join(ROOT, "plugins", "index.json")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-38s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


class FakeBox:
    """把确认框换成「总是确定」，错误消息记下来。"""
    def __init__(self):
        self.errors = []

    def askyesno(self, *a, **k):
        return True

    def showerror(self, title=None, message=None, **k):
        self.errors.append(str(message))

    def __getattr__(self, name):
        def noop(*a, **k):
            return None
        return noop


def collect(w, out):
    try:
        cls = w.winfo_class()
    except Exception:
        return
    if isinstance(w, tk.Toplevel):
        try:
            out.append("TITLE:" + w.title())
        except Exception:
            pass
    if isinstance(w, _MOD._QpeRoundButton):
        out.append(str(getattr(w, "_text", "")))
    elif cls in ("Label", "Button", "Checkbutton", "Radiobutton"):
        try:
            out.append(str(w.cget("text")))
        except Exception:
            pass
    for ch in w.winfo_children():
        collect(ch, out)


def wait_until(app, pred, timeout=15.0, step=0.02):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if pred():
            return True
        time.sleep(step)
    return False


def main():
    global _MOD
    mod = importlib.machinery.SourceFileLoader("mkt", APP).load_module()
    _MOD = mod
    print("=== 插件市场界面 v%s ===" % mod.APP_VERSION)
    tmp = os.path.join(tempfile.gettempdir(), "_prism_marketcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    data_dir = os.path.join(tmp, "data")
    plugins_dir = os.path.join(tmp, "plugins")
    os.makedirs(data_dir)
    os.makedirs(plugins_dir)

    raw = json.load(open(INDEX, encoding="utf-8"))
    payload = {}
    for e in raw["plugins"]:
        payload[os.path.basename(e["url"])] = open(
            os.path.join(ROOT, e["source"]), "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            name = self.path.lstrip("/").split("?")[0]
            body = (json.dumps(catalog).encode("utf-8")
                    if name == "index.json" else payload.get(name))
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    base = "http://127.0.0.1:%d" % port
    catalog = json.loads(json.dumps(raw))
    for e in catalog["plugins"]:
        e["url"] = base + "/" + os.path.basename(e["url"])
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # 伪造一个「内置插件」：id=bw 但文件名是 黑白.py；清单里塞同 id 条目测试冲突
    open(os.path.join(plugins_dir, "黑白.py"), "w", encoding="utf-8").write(
        'PLUGIN = {"id": "bw", "name": "黑白", "version": "2.0", "api": 2}\n'
        'def run(img, **params):\n    return img\n')
    bw_entry = json.loads(json.dumps(catalog["plugins"][0]))
    bw_entry["id"] = "bw"
    bw_entry["name"] = {"zh": "黑白", "en": "Mono", "ja": "モノクロ"}
    bw_entry["version"] = "1.0"
    catalog["plugins"].append(bw_entry)

    # 预置状态：soft-glow 已装当前版；duotone 装旧版；grad-nd 未装
    by_id = {e["id"]: e for e in raw["plugins"]}
    soft = open(os.path.join(ROOT, by_id["soft-glow"]["source"]), "rb").read()
    open(os.path.join(plugins_dir, "soft-glow.py"), "wb").write(soft)
    duo = open(os.path.join(ROOT, by_id["duotone"]["source"]), "rb").read()
    old_duo = duo.replace(b'"version": "1.0"', b'"version": "0.9"')
    assert old_duo != duo
    open(os.path.join(plugins_dir, "duotone.py"), "wb").write(old_duo)

    mod._data_dir = lambda: data_dir
    mod._plugin_dir = lambda: plugins_dir
    mod.PLUGIN_CATALOG_URL = base + "/index.json"
    fake = FakeBox()
    mod.messagebox = fake

    app = mod.QPEApp()
    app.lang = "zh"
    mod.APP_LANG = "zh"
    try:
        app.show_plugin_market()
        ready = wait_until(
            app, lambda: "共" in getattr(app, "_market_status", None).cget("text")
            if getattr(app, "_market_status", None) is not None else False, 20)
        ok("市场窗口拉到清单", ready,
           getattr(app, "_market_status", None).cget("text") if ready else "超时")
        texts = []
        collect(app.market_win, texts)
        ok("状态：未安装", "未安装" in texts, "")
        ok("状态：已安装", "已安装" in texts, "")
        ok("状态：可更新", any("可更新 0.9 → 1.0" in t for t in texts), "")
        ok("状态：与已装插件冲突", "与已装插件冲突" in texts, "")
        ok("按钮：安装 / 更新 / 重新安装",
           all(x in texts for x in ("安装", "更新", "重新安装")), "")

        def entry(pid):
            return next(e for e in app._market_entries if e["id"] == pid)

        # 搜索过滤：按 id / 名称 / 说明 / 作者
        app._market_query.set("duo")
        app._market_render()
        wait_until(app, lambda: False, 0.2)
        texts = []
        collect(app.market_win, texts)
        ok("搜索命中 duotone",
           any("双色调" in t for t in texts) and not any("柔光" in t for t in texts))
        ok("搜索计数", "共 1 / 4 个插件" in texts,
           [t for t in texts if "共 " in t][:1])
        app._market_query.set("")
        app._market_render()
        wait_until(app, lambda: False, 0.2)

        # 冲突 id：直接拒绝，不能覆盖内置插件
        n_err = len(fake.errors)
        app._market_install(entry("bw"))
        hit = wait_until(app, lambda: len(fake.errors) > n_err, 8)
        ok("冲突 id 不能覆盖安装", hit and any(
            "占用" in e for e in fake.errors[n_err:]),
           fake.errors[-1][:40] if fake.errors else "无错误")

        # 一键安装 grad-nd
        app._market_install(entry("grad-nd"))
        done = wait_until(app, lambda: os.path.exists(
            os.path.join(plugins_dir, "grad-nd.py")) and any(
                p.get("id") == "grad-nd" for p in app.plugins), 20)
        ok("一键安装落盘并出现在插件列表", done, "")

        # 更新 duotone：0.9 -> 1.0，且保留原文件名
        app._market_install(entry("duotone"))
        done = wait_until(app, lambda: b'"version": "1.0"' in open(
            os.path.join(plugins_dir, "duotone.py"), "rb").read(), 20)
        ok("一键更新覆盖旧版", done, "")
        ok("更新后仍是原文件名",
           os.path.exists(os.path.join(plugins_dir, "duotone.py")))

        # 哈希不符：不能覆盖已有文件
        bad = dict(entry("soft-glow"))
        bad["sha256"] = "0" * 64
        before = open(os.path.join(plugins_dir, "soft-glow.py"), "rb").read()
        n_err = len(fake.errors)
        app._market_install(bad)
        hit = wait_until(app, lambda: len(fake.errors) > n_err, 12)
        after = open(os.path.join(plugins_dir, "soft-glow.py"), "rb").read()
        ok("哈希不符被拒绝", hit and any(
            "SHA-256" in e for e in fake.errors[n_err:]),
           (fake.errors[-1][:40] if fake.errors else "无错误"))
        ok("哈希不符未改动文件", before == after)
        texts = []
        collect(app.market_win, texts)
        ok("市场状态刷新为已安装", texts.count("已安装") >= 2,
           "已安装 ×%d" % texts.count("已安装"))
    finally:
        try:
            app.destroy()
        except Exception:
            pass
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 插件市场界面回归通过")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
