# -*- coding: utf-8 -*-
"""应用内词条覆盖率自检。

扫描 src/Prism.pyw 里的中文字符串，报告哪些还没进 LANG_TABLE。

跑法：python tools/i18ncheck_app.py [--list N] [--json out.json] [--strict]

--strict 有未译词条就返回 1，用于发布前门禁。

--json 输出每条未译词条的完整原文、出现次数、行号与所在源码行，
补词条时按它逐条翻译（终端里的表格会截断长串）。
"""
import importlib.machinery
import io
import json
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


def _blank(match):
    """把匹配到的块替换成等长空白（保留换行），这样行号不会错位。"""
    return re.sub(r"[^\n]", " ", match.group(0))


def main():
    only_list = "--list" in sys.argv
    json_out = None
    if "--json" in sys.argv:
        try:
            json_out = sys.argv[sys.argv.index("--json") + 1]
        except Exception:
            print("--json 后面要跟输出路径")
            return 2
    limit = 15
    if only_list:
        try:
            limit = int(sys.argv[sys.argv.index("--list") + 1])
        except Exception:
            pass
    src = io.open(APP, encoding="utf-8").read()
    # 去掉三引号块与词典本身，减少误报；用等长空白替换以保住行号
    src = re.sub(r"LANG_TABLE = \{.*?\n\}\n", _blank, src, flags=re.S)
    src = re.sub(r'""".*?"""', _blank, src, flags=re.S)
    src = re.sub(r"'''.*?'''", _blank, src, flags=re.S)
    numbered = [(i, ln) for i, ln in enumerate(src.splitlines(), 1)
                if not ln.strip().startswith("#")]
    keys = load_keys()

    from collections import Counter
    missing = Counter()
    places = {}
    for lineno, ln in numbered:
        for m in LIT.finditer(ln):
            s = m.group(1)
            if not CJK.search(s):
                continue
            if any(h in s for h in SKIP_HINT):
                continue
            if s in keys:
                continue
            missing[s] += 1
            places.setdefault(s, []).append([lineno, ln.strip()[:110]])

    total_untranslated = sum(missing.values())
    print("  词典键数 = %d" % len(keys))
    print("  未收录的中文字面量 = %d 条（出现 %d 次）"
          % (len(missing), total_untranslated))
    for s, n in missing.most_common(limit):
        print("     %-40s ×%d" % (s[:38], n))
    if json_out:
        items = []
        for s in sorted(missing, key=lambda k: places[k][0][0]):
            items.append({"zh": s, "count": missing[s],
                          "places": places[s]})
        with io.open(json_out, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(items, ensure_ascii=False, indent=1))
        print("  已写出 %s（%d 条）" % (json_out, len(items)))
    if "--strict" in sys.argv and missing:
        print("  !! 有 %d 条新文案还没做三语，发布前必须补齐" % len(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
