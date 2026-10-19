# -*- coding: utf-8 -*-
"""把三语 Markdown 文档渲染成站点用的静态 HTML。

输入：docs/plugin-api{,.en,.ja}.md、plugins/README{,.en,.ja}.md
输出：docs/plugin-api{,.en,.ja}.html、docs/plugin-guide{,.en,.ja}.html

跑法：
    python tools/make_docs_html.py           生成
    python tools/make_docs_html.py --check   只检查是否最新
"""
import html
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GITHUB = "https://github.com/11ly322/Prism/blob/main/"
FAIL = []
SETS = {
    "api": {
        "src": {"zh": os.path.join(DOCS, "plugin-api.md"),
                "en": os.path.join(DOCS, "plugin-api.en.md"),
                "ja": os.path.join(DOCS, "plugin-api.ja.md")},
        "out": {"zh": "plugin-api.html", "en": "plugin-api.en.html",
                "ja": "plugin-api.ja.html"},
        "title": {"zh": "Prism 插件 API", "en": "Prism Plugin API",
                  "ja": "Prism プラグイン API"},
    },
    "guide": {
        "src": {"zh": os.path.join(ROOT, "plugins", "README.md"),
                "en": os.path.join(ROOT, "plugins", "README.en.md"),
                "ja": os.path.join(ROOT, "plugins", "README.ja.md")},
        "out": {"zh": "plugin-guide.html", "en": "plugin-guide.en.html",
                "ja": "plugin-guide.ja.html"},
        "title": {"zh": "Prism 插件指南", "en": "Prism Plugin Guide",
                  "ja": "Prism プラグインガイド"},
    },
}
LANG_LABEL = {"zh": "中文", "en": "English", "ja": "日本語"}
DOC_NAMES = {"zh": "中文", "en": "EN", "ja": "日本語"}


def inline(text):
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)
    return text


def link(m):
    label, href = m.group(1), m.group(2)
    if not href.startswith(("http://", "https://", "#")):
        href = resolve_link(href)
    return '<a href="%s">%s</a>' % (html.escape(href, quote=True), label)


CUR_SET = "api"


def resolve_link(href):
    """Markdown 里的相对链接 -> 站点 HTML 或 GitHub 源码页。"""
    path = href.split("#", 1)[0]
    base = os.path.basename(path)
    mapping = {
        "plugin-api.md": "plugin-api.html",
        "plugin-api.en.md": "plugin-api.en.html",
        "plugin-api.ja.md": "plugin-api.ja.html",
        "README.md": "plugin-guide.html",
        "README.en.md": "plugin-guide.en.html",
        "README.ja.md": "plugin-guide.ja.html",
    }
    if base in mapping:
        return mapping[base] + ("#" + href.split("#", 1)[1] if "#" in href else "")
    # 其它仓库内文件：链到 GitHub
    norm = os.path.normpath(os.path.join(
        "plugins" if CUR_SET == "guide" else "docs", path)).replace("\\", "/")
    if norm.startswith(".."):
        norm = os.path.normpath(os.path.join("plugins", path)).replace("\\", "/")
    return GITHUB + norm


def render(md):
    lines = md.replace("\r\n", "\n").split("\n")
    out, i = [], 0
    # 第一行语言切换单独做成 nav
    if lines and "[" in lines[0] and "](" in lines[0]:
        nav = inline(lines[0])
        out.append('<nav class="lang">%s</nav>' % nav)
        i = 1
        if i < len(lines) and not lines[i].strip():
            i += 1
    para, bullets, numbered = [], [], []

    def flush():
        nonlocal para, bullets, numbered
        if para:
            out.append("<p>%s</p>" % inline(" ".join(para)))
            para = []
        if bullets:
            out.append("<ul>%s</ul>" % "".join(
                "<li>%s</li>" % inline(x) for x in bullets))
            bullets = []
        if numbered:
            out.append("<ol>%s</ol>" % "".join(
                "<li>%s</li>" % inline(x) for x in numbered))
            numbered = []

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            flush()
            fence = stripped[:3]
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>%s</code></pre>" %
                       html.escape("\n".join(code)))
            continue
        if not stripped:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m:
            flush()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, inline(m.group(2)), level))
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(
                r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            flush()
            head = [c.strip() for c in stripped.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in
                             lines[i].strip().strip("|").split("|")])
                i += 1
            body = "".join(
                "<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in row)
                for row in rows)
            out.append("<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
                "".join("<th>%s</th>" % inline(c) for c in head), body))
            continue
        if re.match(r"^[-*]\s+", stripped):
            if numbered:
                flush()
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
            i += 1
            continue
        m = re.match(r"^\d+\.\s+(.*)$", stripped)
        if m:
            if bullets:
                flush()
            numbered.append(m.group(1))
            i += 1
            continue
        para.append(stripped)
        i += 1
    flush()
    return "\n".join(out)


PAGE = """<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(title)s">
<style>
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;background:#f6f6f4;color:#1c1c1c;font:16px/1.7 -apple-system,"Segoe UI",Roboto,"Noto Sans JP","Noto Sans SC",sans-serif}
main{max-width:820px;margin:0 auto;padding:40px 22px 80px}
nav.top{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:26px;font-size:14px}
nav.top a{color:#555;text-decoration:none;border-bottom:1px solid #ccc}
nav.lang{display:flex;gap:10px;font-size:14px;color:#666;margin-bottom:22px}
nav.lang a{color:#2f6df6;text-decoration:none}
h1{font-size:30px;line-height:1.3;margin:0 0 18px}
h2{font-size:23px;margin:34px 0 10px}
h3{font-size:18px;margin:24px 0 8px}
p,li{color:#2a2a2a}
a{color:#245fce}
code{background:#ececea;border-radius:4px;padding:1px 5px;font-size:90%%;font-family:ui-monospace,Consolas,monospace}
pre{background:#1f1f22;color:#eaeaea;border-radius:8px;padding:14px 16px;overflow:auto}
pre code{background:none;padding:0;color:inherit;font-size:13px;line-height:1.55}
table{border-collapse:collapse;width:100%%;margin:12px 0;font-size:14px}
th,td{border:1px solid #d8d8d4;padding:6px 9px;text-align:left;vertical-align:top}
th{background:#ececea;font-weight:600}
blockquote{margin:12px 0;padding:8px 14px;border-left:3px solid #c9c9c4;color:#555}
@media (prefers-color-scheme:dark){
 body{background:#141414;color:#e8e8e8}
 p,li{color:#d6d6d6}
 code{background:#262628}
 th,td{border-color:#333}
 th{background:#222}
 blockquote{border-color:#444;color:#aaa}
 nav.top a{color:#bbb;border-color:#444}
 a{color:#8ab4ff}
}
</style>
</head>
<body>
<main>
<nav class="top"><a href="./">Prism</a><a href="plugin-guide%(lang_suffix)s.html">Guide</a><a href="plugin-api%(lang_suffix)s.html">API</a></nav>
%(body)s
</main>
</body>
</html>
"""


def build_all():
    outputs = {}
    global CUR_SET
    for set_name, spec in SETS.items():
        CUR_SET = set_name
        for lang, src in spec["src"].items():
            md = io.open(src, encoding="utf-8").read()
            body = render(md)
            # 语言切换里的 .md 链接换成当前站点 html
            body = re.sub(r'href="([a-z-]+\.md)"', lambda m: 'href="%s"' % (
                {"plugin-api.md": "plugin-api.html",
                 "plugin-api.en.md": "plugin-api.en.html",
                 "plugin-api.ja.md": "plugin-api.ja.html",
                 "README.md": "plugin-guide.html",
                 "README.en.md": "plugin-guide.en.html",
                 "README.ja.md": "plugin-guide.ja.html"}.get(m.group(1),
                                                              m.group(1))), body)
            suffix = "" if lang == "zh" else "." + lang
            page = PAGE % {
                "lang": {"zh": "zh-CN", "en": "en", "ja": "ja"}[lang],
                "title": spec["title"][lang],
                # 正文里的 % 不能被外层格式化吃掉
                "body": body.replace("%", "%%"),
                "lang_suffix": suffix,
            }
            outputs[os.path.join(DOCS, spec["out"][lang])] = page
    return outputs


def main():
    check = "--check" in sys.argv
    outputs = build_all()
    changed = []
    for path, content in outputs.items():
        old = io.open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if old != content:
            changed.append(os.path.basename(path))
            if not check:
                io.open(path, "w", encoding="utf-8", newline="\n").write(content)
    if check:
        if changed:
            print("文档 HTML 不是最新：%s" % ", ".join(changed))
            return 1
        print("文档 HTML 最新：%d 页" % len(outputs))
        return 0
    print("已生成文档 HTML %d 页%s" % (
        len(outputs), ("（更新 " + ", ".join(changed) + "）") if changed else "（无变化）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
