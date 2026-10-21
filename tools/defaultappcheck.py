# -*- coding: utf-8 -*-
"""默认应用注册回归：不写真实注册表，用假 winreg 验证 Capabilities/ProgID。

支持 ``--rounds N`` 重复跑 N 轮（发布前自检 10 轮用）。
"""
import importlib.machinery
import os
import sys
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    REG_NONE = 0

    def __init__(self):
        self.store = {}

    def CreateKey(self, hive, path):
        self.store.setdefault(path, {})
        return path

    def SetValueEx(self, key, name, reserved, typ, value):
        self.store[key][name] = (typ, value)

    def CloseKey(self, key):
        pass


def ok(name, cond, detail=""):
    print("  %s %-32s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def run_round(mod, round_no):
    global FAIL
    FAIL = []
    fake = FakeWinreg()
    sys.modules["winreg"] = fake

    def check(app, friendly):
        mod.APP = app
        mod.FRIENDLY = friendly
        mod.SUPPORTED_EXTS = (".jpg", ".png")
        exe = r"C:\Apps\%s.exe" % app
        ok("%s 可注册" % app, mod.register_default_app(exe) is True)
        cap = r"Software\%s\Capabilities" % app
        progid = app + ".Image"
        ok("%s ApplicationName" % app,
           fake.store[cap].get("ApplicationName", (0, ""))[1] == friendly)
        ok("%s ApplicationDescription" % app,
           bool(fake.store[cap].get("ApplicationDescription", (0, ""))[1]))
        ok("%s 文件关联" % app,
           fake.store.get(cap + r"\FileAssociations", {}).get(
               ".jpg", (0, ""))[1] == progid)
        ok("%s ProgID 命令" % app,
           '"%s" "%%1"' % exe ==
           fake.store.get(r"Software\Classes\%s\shell\open\command" % progid,
                          {}).get(None, (0, ""))[1])
        ok("%s 注册到 RegisteredApplications" % app,
           fake.store.get(r"Software\RegisteredApplications", {}).get(
               friendly, (0, ""))[1] == r"Software\%s\Capabilities" % app)
        ok("%s 打开方式候选" % app,
           progid in fake.store.get(
               r"Software\Classes\.jpg\OpenWithProgids", {}))

        # 一键设为默认：写类默认，但不触碰 UserChoice
        count = mod.apply_image_associations()
        ok("%s 一键登记数量" % app, count == 2, str(count))
        ok("%s .jpg 类默认" % app,
           fake.store.get(r"Software\Classes\.jpg", {}).get(
               None, (0, ""))[1] == progid)
        ok("%s .png 类默认" % app,
           fake.store.get(r"Software\Classes\.png", {}).get(
               None, (0, ""))[1] == progid)
        ok("%s 未改 UserChoice" % app,
           not any("UserChoice" in path for path in fake.store))

    check("PrismTest", "Prism 测试")
    check("PrismBigScreenTest", "Prism 大屏版")

    # 默认应用 URI：Win10 打开列表，Win11 直接定位应用
    old = mod._win_build
    try:
        mod.FRIENDLY = "Prism 测试"
        mod._win_build = lambda: 7601
        ok("Win7 URI", mod.default_apps_uri() == "ms-settings:defaultapps",
           mod.default_apps_uri())
        mod._win_build = lambda: 19045
        ok("Win10 URI", mod.default_apps_uri() == "ms-settings:defaultapps",
           mod.default_apps_uri())
        mod._win_build = lambda: 22621
        want = ("ms-settings:defaultapps?registeredAppUser=" +
                quote("Prism 测试", safe=""))
        ok("Win11 URI", mod.default_apps_uri() == want,
           mod.default_apps_uri())
    finally:
        mod._win_build = old

    # 一键入口：Win10/11 必须打开设置确认；Win7/8 不打开
    old_start = mod.os.startfile
    opened = []
    try:
        mod.os.startfile = lambda uri: opened.append(uri)
        mod.FRIENDLY = "Prism 测试"
        mod._win_build = lambda: 19045
        n, confirm = mod.one_click_default(r"C:\Apps\PrismTest.exe")
        ok("Win10 一键登记", n == 2 and confirm is True, "%s/%s" % (n, confirm))
        ok("Win10 打开确认页", opened == ["ms-settings:defaultapps"], opened)
        opened[:] = []
        mod._win_build = lambda: 7601
        n, confirm = mod.one_click_default(r"C:\Apps\PrismTest.exe")
        ok("Win7 一键生效", n == 2 and confirm is False, "%s/%s" % (n, confirm))
        ok("Win7 不弹设置", opened == [], opened)
    finally:
        mod.os.startfile = old_start

    print("  第 %d 轮：%s" % (round_no, "PASS" if not FAIL else "FAIL"))
    return list(FAIL)


def main():
    if os.name != "nt":
        print("  SKIP 默认应用注册（非 Windows）")
        return 0
    rounds = 1
    if "--rounds" in sys.argv:
        try:
            rounds = max(1, int(sys.argv[sys.argv.index("--rounds") + 1]))
        except Exception:
            rounds = 1
    mod = importlib.machinery.SourceFileLoader(
        "inst9", os.path.join(ROOT, "src", "installer.pyw")).load_module()
    failed = []
    for i in range(1, rounds + 1):
        print("== 默认应用自检 %d/%d ==" % (i, rounds))
        failed += run_round(mod, i)
        print()
    if failed:
        print(">>> 默认应用注册回归失败 %d 项：%s" %
              (len(failed), sorted(set(failed))))
        return 1
    print(">>> 默认应用注册回归通过（%d 轮）" % rounds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
