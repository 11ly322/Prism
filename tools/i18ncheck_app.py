# -*- coding: utf-8 -*-
"""应用内词条覆盖率自检。

扫描 src/Prism.pyw 里的中文字符串，报告哪些还没进 LANG_TABLE。

跑法：python tools/i18ncheck_app.py [--list N]
"""
import importlib.machinery
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
CJK = re.compile(r"[\u4e00-\u9fff]")
LIT = re.compile(r'"([^"\n]{2,80})"')

# 这些不是界面文案：注释、异常、日志、格式串主体、路径
SKIP_HINT = ("%(", "\\n", "logs/", ".py", "sqlite", "http", "utf-8",
             "win32", "/", "\\", ":", "＝", "=")
SKIP_WORDS = ("错误", "失败", "异常", "无法", "日志", "插件 ")


def load_keys():
    mod = importlib.machinery.SourceFileLoader("prism_keys", APP).load_module()
    return set(mod.LANG_TABLE["en"].keys())


def main():
    only_list = "--list" in sys.argv
    limit = 15
    if only_list:
        try:
            limit = int(sys.argv[sys.argv.index("--list") + 1])
        except Exception:
            pass
    src = io.open(APP, encoding="utf-8").read()
    # 去掉三引号块与注释行，减少误报
    # 词典本身的译文也是中文字面量，必须先剔除，否则统计会把译文算成缺失
    src = re.sub(r"LANG_TABLE = \{.*?\n\}\n", "", src, flags=re.S)
    src = re.sub(r'""".*?"""', "", src, flags=re.S)
    src = re.sub(r"'''.*?'''", "", src, flags=re.S)
    lines = [ln for ln in src.splitlines()
             if not ln.strip().startswith("#")]
    keys = load_keys()

    from collections import Counter
    missing = Counter()
    for ln in lines:
        for m in LIT.finditer(ln):
            s = m.group(1)
            if not CJK.search(s):
                continue
            if any(h in s for h in SKIP_HINT):
                continue
            if s in keys:
                continue
            missing[s] += 1

    total_untranslated = sum(missing.values())
    print("  词典键数 = %d" % len(keys))
    print("  未收录的中文字面量 = %d 条（出现 %d 次）"
          % (len(missing), total_untranslated))
    for s, n in missing.most_common(limit):
        print("     %-40s ×%d" % (s[:38], n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
