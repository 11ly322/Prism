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
    toc = []
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
            text = m.group(2)
            attrs = ""
            if level == 2:
                hid = "sec-%d" % (len(toc) + 1)
                toc.append((hid, re.sub(r"[`*]", "", text)))
                attrs = ' id="%s"' % hid
            out.append("<h%d%s>%s</h%d>" % (
                level, attrs, inline(text), level))
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
    return "\n".join(out), toc


PAGE = """<!DOCTYPE html>
<html lang="%(lang)s">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<meta name="description" content="%(title)s">
<style>
:root{color-scheme:light dark;--bg:#f6f6f4;--fg:#1c1c1c;--dim:#666;--line:#dcdcd8;--card:#fff;--accent:#245fce;--code:#1f1f22}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,"Segoe UI",Roboto,"Noto Sans JP","Noto Sans SC",sans-serif}
header.hd{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 88%%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.hd-in{max-width:900px;margin:0 auto;padding:12px 22px;display:flex;align-items:center;gap:22px}
.brand{font-weight:700;font-size:18px;color:var(--fg);text-decoration:none;letter-spacing:.02em}
nav.links{display:flex;gap:16px;flex-wrap:wrap;font-size:14px}
nav.links a{color:var(--dim);text-decoration:none;padding:3px 0;border-bottom:1px solid transparent}
nav.links a:hover{color:var(--fg);border-color:var(--line)}
main{max-width:900px;margin:0 auto;padding:34px 22px 70px}
nav.lang{display:flex;gap:8px;font-size:13px;margin-bottom:24px;flex-wrap:wrap}
nav.lang a,nav.lang strong{display:inline-block;padding:3px 10px;border:1px solid var(--line);border-radius:999px;text-decoration:none;color:var(--dim);font-weight:400}
nav.lang strong{color:var(--fg);border-color:var(--fg)}
nav.toc{display:flex;flex-wrap:wrap;gap:6px 14px;align-items:baseline;margin:0 0 26px;padding:12px 14px;border:1px solid var(--line);border-radius:10px;background:var(--card);font-size:13px}
nav.toc b{font-size:12px;color:var(--dim);font-weight:600;margin-right:4px}
nav.toc a{color:var(--fg);text-decoration:none;border-bottom:1px dotted var(--line)}
nav.toc a:hover{border-bottom-style:solid}
h2{scroll-margin-top:70px}
h1{font-size:31px;line-height:1.28;margin:0 0 20px;letter-spacing:-.01em}
h2{font-size:23px;margin:38px 0 10px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:18px;margin:24px 0 8px}
p,li{color:color-mix(in srgb,var(--fg) 88%%,transparent)}
a{color:var(--accent)}
code{background:color-mix(in srgb,var(--fg) 8%%,transparent);border-radius:4px;padding:1px 5px;font-size:90%%;font-family:ui-monospace,Consolas,monospace}
pre{background:var(--code);color:#eaeaea;border-radius:10px;padding:15px 17px;overflow:auto;border:1px solid #2c2c30}
pre code{background:none;padding:0;color:inherit;font-size:13px;line-height:1.6}
table{border-collapse:collapse;width:100%%;margin:14px 0;font-size:14px;background:var(--card)}
th,td{border:1px solid var(--line);padding:7px 10px;text-align:left;vertical-align:top}
th{background:color-mix(in srgb,var(--fg) 6%%,transparent);font-weight:600}
tbody tr:nth-child(even){background:color-mix(in srgb,var(--fg) 2.5%%,transparent)}
blockquote{margin:14px 0;padding:9px 15px;border-left:3px solid var(--line);color:var(--dim)}
footer{border-top:1px solid var(--line);margin-top:40px}
.ft-in{max-width:900px;margin:0 auto;padding:18px 22px 40px;font-size:13px;color:var(--dim)}
@media (prefers-color-scheme:dark){
 :root{--bg:#141414;--fg:#e8e8e8;--dim:#a0a0a0;--line:#333;--card:#191919;--accent:#8ab4ff}
}
@media (max-width:620px){h1{font-size:26px}h2{font-size:20px}main{padding-top:24px}}
</style>
</head>
<body>
<header class="hd"><div class="hd-in">
<a class="brand" href="./">Prism</a>
<nav class="links">
<a href="./">%(home)s</a>
<a href="plugin-guide%(lang_suffix)s.html">%(guide)s</a>
<a href="plugin-api%(lang_suffix)s.html">%(api)s</a>
<a href="https://github.com/11ly322/Prism">GitHub</a>
</nav></div></header>
<main>
%(body)s
</main>
<footer><div class="ft-in">Prism · MIT License · <a href="https://github.com/11ly322/Prism">GitHub</a></div></footer>
</body>
</html>
"""

HEAD_LABELS = {
    "zh": ("首页", "指南", "API"),
    "en": ("Home", "Guide", "API"),
    "ja": ("ホーム", "ガイド", "API"),
}



def build_all():
    outputs = {}
    global CUR_SET
    for set_name, spec in SETS.items():
        CUR_SET = set_name
        for lang, src in spec["src"].items():
            md = io.open(src, encoding="utf-8").read()
            body, toc = render(md)
            # 语言切换里的 .md 链接换成当前站点 html
            body = re.sub(r'href="([a-z-]+\.md)"', lambda m: 'href="%s"' % (
                {"plugin-api.md": "plugin-api.html",
                 "plugin-api.en.md": "plugin-api.en.html",
                 "plugin-api.ja.md": "plugin-api.ja.html",
                 "README.md": "plugin-guide.html",
                 "README.en.md": "plugin-guide.en.html",
                 "README.ja.md": "plugin-guide.ja.html"}.get(m.group(1),
                                                              m.group(1))), body)
            if toc:
                label = {"zh": "目录", "en": "Contents",
                         "ja": "目次"}[lang]
                links = "".join('<a href="#%s">%s</a>' % (
                    hid, html.escape(text)) for hid, text in toc)
                body = re.sub(
                    r'(<nav class="lang">.*?</nav>)',
                    lambda m: m.group(1) + '<nav class="toc"><b>%s</b>%s</nav>'
                    % (label, links), body, count=1, flags=re.S)
            suffix = "" if lang == "zh" else "." + lang
            home, guide, api = HEAD_LABELS[lang]
            page = PAGE % {
                "lang": {"zh": "zh-CN", "en": "en", "ja": "ja"}[lang],
                "title": spec["title"][lang],
                # 正文里的 % 不能被外层格式化吃掉
                "body": body.replace("%", "%%"),
                "lang_suffix": suffix,
                "home": home, "guide": guide, "api": api,
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
