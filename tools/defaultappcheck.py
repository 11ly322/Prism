# -*- coding: utf-8 -*-
"""默认应用注册回归：不写真实注册表，用假 winreg 验证 Capabilities/ProgID。"""
import importlib.machinery
import os
import sys

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


def main():
    if os.name != "nt":
        print("  SKIP 默认应用注册（非 Windows）")
        return 0
    mod = importlib.machinery.SourceFileLoader(
        "inst9", os.path.join(ROOT, "src", "installer.pyw")).load_module()
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
        ok("%s 文件关联" % app,
           fake.store.get(cap + r"\FileAssociations", {}).get(
               ".jpg", (0, ""))[1] == progid)
        ok("%s ProgID 命令" % app,
           '"%s" "%%1"' % exe ==
           fake.store.get(r"Software\Classes\%s\shell\open\command" % progid,
                          {}).get(None, (0, ""))[1])
        ok("%s 注册到 RegisteredApplications" % app,
           fake.store.get(r"Software\RegisteredApplications", {}).get(
               app, (0, ""))[1] == r"Software\%s\Capabilities" % app)
        ok("%s 打开方式候选" % app,
           progid in fake.store.get(
               r"Software\Classes\.jpg\OpenWithProgids", {}))

    check("PrismTest", "Prism 测试")
    check("PrismBigScreenTest", "Prism 大屏版")

    print()
    if FAIL:
        print(">>> 默认应用注册回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 默认应用注册回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
