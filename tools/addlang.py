# -*- coding: utf-8 -*-
"""把一批三语词条追加进 src/Prism.pyw 的 LANG_TABLE。

输入 JSON 格式（tools/i18ncheck_app.py --json 的反向）：

    {"中文原文": {"en": "English", "ja": "日本語"}, ...}

用法：
    python tools/addlang.py batch.json --section "9.4.0 对话框"
    python tools/addlang.py batch.json --dry      # 只校验不写

会做的事：
1. 拒绝空译、拒绝 en/ja 键不一致、拒绝已在词典里的键（避免覆盖旧译文）；
2. 校验占位符（%s %d %.1f %+d %% 等）在原文与译文里数量一致；
3. 按 en / ja 两个语言块分别插入，带一行分组注释；
4. 写回前做 ast 语法检查，失败不落盘。
"""
import ast
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "src", "Prism.pyw")
PH = re.compile(r"%(?:[-+ #0]*\d*(?:\.\d+)?[sdifgeE%])")


def load_existing():
    """只解析词典，不执行整个程序：抓 LANG_TABLE 的源码再 ast.literal_eval。"""
    src = io.open(APP, encoding="utf-8").read()
    start = src.index("LANG_TABLE = {")
    depth = 0
    for i in range(start, len(src)):
        ch = src[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src, start, i + 1
    raise SystemExit("找不到 LANG_TABLE 的结尾")


def placeholders(text):
    return sorted(PH.findall(text))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    section = ""
    if "--section" in sys.argv:
        try:
            section = sys.argv[sys.argv.index("--section") + 1]
        except Exception:
            print("--section 后面要跟分组名")
            return 2
    if not args:
        print(__doc__)
        return 2
    path = args[0]
    with io.open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        data = {str(it["zh"]): {"en": it["en"], "ja": it["ja"]} for it in data}
    if not isinstance(data, dict):
        print("JSON 顶层必须是对象")
        return 2

    src, start, end = load_existing()
    table = ast.literal_eval(src[start + len("LANG_TABLE = "):end])
    existing = set(table["en"]) | set(table["ja"])

    rows, problems = [], []
    for zh, tr in data.items():
        zh = str(zh)
        if not isinstance(tr, dict):
            problems.append("译文不是对象：%s" % zh)
            continue
        en, ja = str(tr.get("en") or ""), str(tr.get("ja") or "")
        if not en or not ja:
            problems.append("缺少 en 或 ja：%s" % zh)
            continue
        if zh in existing:
            problems.append("词典里已有：%s" % zh)
            continue
        want = [p for p in placeholders(zh) if p != "%%"]
        for lang, text in (("en", en), ("ja", ja)):
            got = [p for p in placeholders(text) if p != "%%"]
            if sorted(want) != sorted(got):
                problems.append("%s 占位符不一致：%s -> %s（%s / %s）"
                                % (lang, zh, text, want, got))
        rows.append((zh, en, ja))

    if problems:
        print("有 %d 个问题，未写入：" % len(problems))
        for p in problems[:30]:
            print("  - " + p)
        if len(problems) > 30:
            print("  …… 还有 %d 个" % (len(problems) - 30))
        return 1
    if not rows:
        print("没有需要新增的词条")
        return 0

    def block(values, lang):
        out = []
        if section:
            out.append("        # %s" % section)
        for zh, en, ja in values:
            out.append("        %s: %s," % (
                json.dumps(zh, ensure_ascii=False),
                json.dumps(en if lang == "en" else ja, ensure_ascii=False)))
        return "\n".join(out) + "\n"

    en_txt, ja_txt = block(rows, "en"), block(rows, "ja")
    anchor_en = '\n    },\n    "ja": {\n'
    anchor_ja = "\n    },\n}\n\n\ndef _tr(text):"
    if src.count(anchor_en) != 1 or src.count(anchor_ja) != 1:
        print("词典结构不是预期的两块，放弃写入")
        return 1
    src = src.replace(anchor_en, "\n" + en_txt + '    },\n    "ja": {\n')
    src = src.replace(anchor_ja,
                      "\n" + ja_txt + "    },\n}\n\n\ndef _tr(text):")
    try:
        ast.parse(src)
    except SyntaxError as exc:
        print("写回后语法错误，未落盘：%s" % exc)
        return 1
    if dry:
        print("干跑通过：%d 条，语法 OK（未写文件）" % len(rows))
        return 0
    with io.open(APP, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(src)
    print("已写入 %d 条三语词条" % len(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
