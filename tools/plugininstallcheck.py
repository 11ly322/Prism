# -*- coding: utf-8 -*-
"""插件 URL 安装链路回归：解析 / 哈希 / 落盘 / 下载 / 大小上限。

不需要 Tk，也不联网（本地起一个 127.0.0.1 的临时 HTTP 服务）。
跑法： python tools/plugininstallcheck.py
"""
import hashlib
import http.server
import importlib.machinery
import json
import os
import shutil
import socketserver
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
CATALOG = os.path.join(ROOT, "plugins", "index.json")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-36s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    mod = importlib.machinery.SourceFileLoader("pinf", APP).load_module()
    print("=== 插件安装链路 v%s ===" % mod.APP_VERSION)
    entries = json.load(open(CATALOG, encoding="utf-8"))["plugins"]
    entry = entries[0]
    DEMO = os.path.join(ROOT, entry["source"])
    SHA = entry["sha256"]
    data = open(DEMO, "rb").read()

    meta = mod.parse_plugin_source(data)
    ok("清单第一个插件可解析", meta["id"] == entry["id"] and meta["api"] == 2,
       "%s / api %s" % (meta["id"], meta["api"]))
    ok("清单 SHA-256 与文件一致",
       hashlib.sha256(data).hexdigest() == SHA,
       hashlib.sha256(data).hexdigest()[:16])

    # 文件名清洗：路径穿越必须被吃掉
    ok("路径穿越被清洗",
       mod.safe_plugin_filename("../../evil") == "evil",
       mod.safe_plugin_filename("../../evil"))
    ok("中文 id 有兜底", mod.safe_plugin_filename("插件") == "plugin",
       mod.safe_plugin_filename("插件"))

    tmp = os.path.join(tempfile.gettempdir(), "_prism_installcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        got = mod.install_plugin_bytes(data, SHA, folder=tmp)
        path = got["path"]
        ok("写入插件目录", os.path.exists(path) and open(path, "rb").read() == data,
           os.path.basename(path))
        try:
            mod.install_plugin_bytes(data, folder=tmp)
            ok("同名不覆盖", False)
        except FileExistsError:
            ok("同名不覆盖", True)
        got2 = mod.install_plugin_bytes(data, folder=tmp, overwrite=True)
        ok("显式覆盖可用", got2["path"] == path)

        try:
            mod.install_plugin_bytes(data, "0" * 64, folder=tmp, overwrite=True)
            ok("哈希不符拒绝", False)
        except mod.PluginSourceError as exc:
            ok("哈希不符拒绝", "SHA-256" in str(exc), str(exc)[:40])

        cases = [
            ("缺少 PLUGIN", b"def run(img):\n    return img\n"),
            ("缺少 run", b'PLUGIN = {"id": "x", "name": "x", "api": 2}\n'),
            ("语法错误", b'PLUGIN = {"id": "x"\n'),
            ("API 不支持", b'PLUGIN = {"id": "x", "api": 9}\ndef run(img):\n'
                           b'    return img\n'),
            ("缺少 id", b'PLUGIN = {"name": "x", "api": 2}\ndef run(img):\n'
                        b'    return img\n'),
            ("非 UTF-8", b'PLUGIN = {"id": "x"}\n\xff\xfe'),
        ]
        for name, raw in cases:
            try:
                mod.parse_plugin_source(raw)
                ok("拒绝：" + name, False)
            except mod.PluginSourceError:
                ok("拒绝：" + name, True)

        # ---- 本地 HTTP 服务：下载、404、大小上限 ----
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/demo.py":
                    body = data
                elif self.path == "/big.py":
                    body = b"#" * (mod.PLUGIN_MAX_BYTES + 10)
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        srv = socketserver.TCPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = "http://127.0.0.1:%d" % port
            net = mod.fetch_plugin_source(base + "/demo.py")
            ok("HTTP 下载", net == data, "%d 字节" % len(net))
            meta2 = mod.parse_plugin_source(net)
            ok("下载后可解析", meta2["id"] == "grad-nd")
            try:
                mod.fetch_plugin_source(base + "/demo.py",
                                        max_bytes=64)
                ok("大小上限生效", False)
            except mod.PluginSourceError as exc:
                ok("大小上限生效", "太大" in str(exc), str(exc))
            try:
                mod.fetch_plugin_source(base + "/big.py")
                ok("超过上限拒绝", False)
            except mod.PluginSourceError as exc:
                ok("超过上限拒绝", "太大" in str(exc), str(exc))
            try:
                mod.fetch_plugin_source(base + "/nope.py")
                ok("404 抛出异常", False)
            except Exception as exc:
                ok("404 抛出异常", True, type(exc).__name__)
            try:
                mod.fetch_plugin_source("file:///etc/passwd")
                ok("拒绝非 http(s)", False)
            except mod.PluginSourceError as exc:
                ok("拒绝非 http(s)", "http" in str(exc), str(exc))
        finally:
            srv.shutdown()
            srv.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 插件安装链路回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
