# -*- coding: utf-8 -*-
"""插件市场清单回归：schema 校验 / 缓存 / 本地 HTTP 拉取 / 安装。

不联网：本地起一个 127.0.0.1 的临时 HTTP 服务，把清单里的 url 换成它。
跑法： python tools/plugincatalogcheck.py
"""
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
INDEX = os.path.join(ROOT, "plugins", "index.json")
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-38s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    mod = importlib.machinery.SourceFileLoader("pcat", APP).load_module()
    print("=== 插件市场清单 v%s ===" % mod.APP_VERSION)
    raw = json.load(open(INDEX, encoding="utf-8"))
    tmp = os.path.join(tempfile.gettempdir(), "_prism_catcheck")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    mod._data_dir = lambda: tmp

    entries = mod.validate_plugin_catalog(raw)
    ok("官方清单通过校验", len(entries) == len(raw["plugins"]),
       "%d 个" % len(entries))
    ok("id 唯一",
       len({e["id"] for e in entries}) == len(entries),
       str([e["id"] for e in entries]))

    # 本地化文本回落
    ok("当前语言缺词回落中文",
       mod._catalog_text({"zh": "中文", "en": "English"}, "ja") == "中文")
    ok("当前语言优先",
       mod._catalog_text({"zh": "中文", "en": "English"}, "en") == "English")

    # 版本比较
    cases = [("1.2", "1.0", True), ("1.0", "1.2", False),
             ("1.0.1", "1.0", True), ("2.0", "2.0", False),
             ("1.10", "1.9", True), ("", "1.0", False)]
    bad = [(a, b, want) for a, b, want in cases
           if mod.catalog_is_newer(a, b) != want]
    ok("版本比较", not bad, str(bad[:2]))

    # 拒绝坏清单
    bad_cases = []
    def mutate(fn):
        obj = json.loads(json.dumps(raw))
        fn(obj)
        return obj
    bad_cases.append(("schema 不是 1",
                      mutate(lambda o: o.__setitem__("schema", 2))))
    bad_cases.append(("plugins 为空",
                      mutate(lambda o: o.__setitem__("plugins", []))))
    bad_cases.append(("plugins 不是列表",
                      mutate(lambda o: o.__setitem__("plugins", {}))))
    bad_cases.append(("id 重复",
                      mutate(lambda o: o["plugins"].append(
                          dict(o["plugins"][0])))))
    bad_cases.append(("sha 格式不对",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "sha256", "abc"))))
    bad_cases.append(("api 不支持",
                      mutate(lambda o: o["plugins"][0].__setitem__("api", 9))))
    bad_cases.append(("url 不是 http(s)",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "url", "ftp://example.com/x.py"))))
    bad_cases.append(("缺少 id",
                      mutate(lambda o: o["plugins"][0].pop("id"))))
    bad_cases.append(("条目不是对象",
                      mutate(lambda o: o["plugins"].append("x"))))
    bad_cases.append(("id 以 _ 开头",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "id", "_utils"))))
    bad_cases.append(("id 含大写",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "id", "GradND"))))
    bad_cases.append(("id 含空格",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "id", "a b"))))
    bad_cases.append(("id 太长",
                      mutate(lambda o: o["plugins"][0].__setitem__(
                          "id", "a" * 41))))
    for name, obj in bad_cases:
        try:
            mod.validate_plugin_catalog(obj)
            ok("拒绝：" + name, False)
        except mod.PluginSourceError:
            ok("拒绝：" + name, True)

    # ---- 本地 HTTP：清单 + 插件文件 ----
    payload = {}
    for e in raw["plugins"]:
        payload[os.path.basename(e["url"])] = open(
            os.path.join(ROOT, e["source"]), "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            name = self.path.lstrip("/").split("?")[0]
            if name == "index.json":
                body = json.dumps(catalog).encode("utf-8")
            else:
                body = payload.get(name)
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
    try:
        got, url = mod.fetch_plugin_catalog(base + "/index.json")
        ok("从 HTTP 拉到清单", len(got) == len(entries), url)
        ok("清单已写缓存",
           os.path.exists(mod.plugin_catalog_cache_path()))
    finally:
        srv.shutdown()
        srv.server_close()
    cached = mod.load_plugin_catalog_cache()
    ok("断网后读缓存", len(cached) == len(entries), "%d 个" % len(cached))
    os.remove(mod.plugin_catalog_cache_path())
    ok("缓存坏了回落空", mod.load_plugin_catalog_cache() == [])

    # ---- 安装：每个清单条目都要能落地 ----
    plugins_dir = os.path.join(tmp, "plugins")
    for e in entries:
        data = payload[os.path.basename(e["url"])]
        meta = mod.install_plugin_bytes(data, e["sha256"], folder=plugins_dir)
        ok("安装 %s" % e["id"],
           os.path.basename(meta["path"]) == mod.safe_plugin_filename(e["id"]) + ".py"
           and meta["id"] == e["id"],
           os.path.basename(meta["path"]))
    # 更新时保留原文件名
    data = payload[os.path.basename(entries[0]["url"])]
    renamed = mod.install_plugin_bytes(
        data, entries[0]["sha256"], folder=plugins_dir, overwrite=True,
        filename="我改过名字.py")
    ok("更新保留原文件名", os.path.basename(renamed["path"]) == "我改过名字.py",
       os.path.basename(renamed["path"]))
    try:
        mod.install_plugin_bytes(data, "0" * 64, folder=plugins_dir,
                                 overwrite=True)
        ok("清单哈希不符拒绝", False)
    except mod.PluginSourceError as exc:
        ok("清单哈希不符拒绝", "SHA-256" in str(exc), str(exc)[:32])

    # 安装源码的 id 也走同一套规则（防止 _utils / 中文 id 落成怪文件名）
    for bad_id in ("_utils", "GradND", "a b", ""):
        src = ('PLUGIN = {"id": %r, "name": "x", "api": 2}\n'
               'def run(img):\n    return img\n' % bad_id).encode("utf-8")
        try:
            mod.parse_plugin_source(src)
            ok("拒绝源码 id：" + repr(bad_id), False)
        except mod.PluginSourceError:
            ok("拒绝源码 id：" + repr(bad_id), True)

    # 三语 name / description
    loc_src = (b'PLUGIN = {"id": "loc", "name": {"zh": "\xe5\x90\x8d", '
               b'"en": "Name", "ja": "\xe5\x90\x8d\xe5\x89\x8d"}, '
               b'"description": {"zh": "\xe8\xaf\xb4", "en": "Desc", '
               b'"ja": "\xe8\xaa\xac\xe6\x98\x8e"}, "api": 2}\n'
               b'def run(img):\n    return img\n')
    old = mod.APP_LANG
    mod.APP_LANG = "en"
    meta_loc = mod.parse_plugin_source(loc_src)
    ok("源码 name 本地化", meta_loc["name"] == "Name", meta_loc["name"])
    ok("源码 description 本地化", meta_loc["description"] == "Desc",
       meta_loc["description"])
    mod.APP_LANG = "ja"
    meta_loc = mod.parse_plugin_source(loc_src)
    ok("源码 ja 回落/命中", meta_loc["name"] == "名前", meta_loc["name"])
    mod.APP_LANG = old

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if FAIL:
        print(">>> 失败 %d 项: %s" % (len(FAIL), FAIL))
        return 1
    print(">>> 插件市场清单回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
