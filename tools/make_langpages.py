# -*- coding: utf-8 -*-
"""静态语言页构建：从中文主页生成 en/index.html 与 ja/index.html。

为什么不用浏览器预渲染：主页已经改成「固定中文 + 自动跳转」，运行时不再翻译，
所以这里用 Python 直接套用 i18n.js 里的词条，产物是纯静态 HTML。

跑法：python tools/make_langpages.py
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
BASE = "https://11ly322.github.io/Prism/"
META = {
    "en": ("en_US", "Prism — a minimalist image viewer",
           "Prism is a minimalist image viewer with JPEG, PNG, WebP, TIFF and Nikon NEF support, "
           "built-in curves, HSL, local filters and a plugin system.",
           "Prism is a minimalist image viewer supporting NEF, curves, HSL, local filters and plugins."),
    "ja": ("ja_JP", "Prism — ミニマルな画像ビューア",
           "Prism は JPEG・PNG・WebP・TIFF・ニコン NEF に対応したミニマルな画像ビューア。"
           "カーブ、HSL、ローカルフィルタ、プラグインを内蔵。",
           "Prism は NEF・カーブ・HSL・ローカルフィルタ・プラグインに対応したミニマルな画像ビューアです。"),
}


def load_dict():
    s = io.open(os.path.join(DOCS, "i18n.js"), encoding="utf-8").read()
    m = re.search(r"window\.PRISM_I18N = (\{.*?\});\s*\nwindow\.PRISM_LANGS", s, re.S)
    return json.loads(m.group(1))


def app_version():
    s = io.open(os.path.join(ROOT, "src", "Prism.pyw"), encoding="utf-8").read()
    return re.search(r'APP_VERSION = "([^"]+)"', s).group(1)


def translate_text(text, d, ver):
    t = text.strip()
    if not t:
        return text
    hit = d.get(t)
    if hit is None:
        hit = d.get(re.sub(r"\d+\.\d+\.\d+", "{v}", t))
    if hit is None:
        return text
    return text.replace(t, hit.replace("{v}", ver))


def build(lang, raw, dicts, ver):
    d = dicts[lang]
    out = re.sub(r">([^<>]+)<", lambda m: ">" + translate_text(m.group(1), d, ver) + "<", raw)
    # 属性
    for attr in ("alt", "title", "placeholder", "aria-label"):
        out = re.sub(r'%s="([^"]*)"' % attr,
                     lambda m: '%s="%s"' % (attr, translate_text(m.group(1), d, ver)), out)
    # 资源与按钮
    out = re.sub(r'(src|href)="(?!https?:|//|#|mailto:|\.\./)([^"]+)"',
                 lambda m: '%s="../%s"' % (m.group(1), m.group(2)), out)
    # 文档页有独立的三语 HTML：把站点内的链接指向当前语言版本
    if lang == "en":
        out = out.replace('href="plugin-guide.html"', 'href="plugin-guide.en.html"')
        out = out.replace('href="plugin-api.html"', 'href="plugin-api.en.html"')
    elif lang == "ja":
        out = out.replace('href="plugin-guide.html"', 'href="plugin-guide.ja.html"')
        out = out.replace('href="plugin-api.html"', 'href="plugin-api.ja.html"')
    for kind in ("main", "viewer", "plugins", "settings"):
        # 本地化截图不存在就保留中文原图：宁可少一张本地化，也不要 404 破图
        loc = "ui-%s-%s.webp" % (kind, lang)
        if os.path.exists(os.path.join(DOCS, "shots", loc)):
            out = out.replace('src="../shots/ui-%s.webp"' % kind,
                              'src="../shots/%s"' % loc)
        else:
            print("   !! 缺少 %s，%s 页沿用中文 ui-%s.webp" % (loc, lang, kind))
    out = out.replace("onclick=\"location.href='index.html'\"",
                      "onclick=\"location.href='../index.html'\"")
    out = re.sub(r'<button data-lang-btn="(\w+)"[^>]*>',
                 lambda m: ('<button data-lang-btn="%s"%s onclick="location.href=\'%s\'">'
                            % (m.group(1),
                               ' class="on"' if m.group(1) == lang else '',
                               "../index.html" if m.group(1) == "zh"
                               else "../%s/index.html" % m.group(1))), out)
    # head 元信息
    locale, title, desc, ld = META[lang]
    out = re.sub(r'<html lang="[^"]*"', '<html lang="%s"' % lang, out, count=1)
    out = re.sub(r"<title>.*?</title>", "<title>%s</title>" % title, out, count=1, flags=re.S)
    out = re.sub(r'<meta name="description" content="[^"]*">',
                 '<meta name="description" content="%s">' % desc, out, count=1)
    out = re.sub(r'<link rel="canonical" href="[^"]*">',
                 '<link rel="canonical" href="%s%s/">' % (BASE, lang), out, count=1)
    out = re.sub(r'<meta property="og:url" content="[^"]*">',
                 '<meta property="og:url" content="%s%s/">' % (BASE, lang), out, count=1)
    out = re.sub(r'<meta property="og:locale" content="[^"]*">',
                 '<meta property="og:locale" content="%s">' % locale, out, count=1)
    out = re.sub(r'<meta property="og:title" content="[^"]*">',
                 '<meta property="og:title" content="%s">' % title, out, count=1)
    out = re.sub(r'<meta property="og:description" content="[^"]*">',
                 '<meta property="og:description" content="%s">' % desc, out, count=1)
    out = re.sub(r'"description":"[^"]*"', '"description":"%s"' % ld, out, count=1)
    out = re.sub(r'<meta name="twitter:title" content="[^"]*">',
                 '<meta name="twitter:title" content="%s">' % title, out, count=1)
    out = re.sub(r'<meta name="twitter:description" content="[^"]*">',
                 '<meta name="twitter:description" content="%s">' % desc, out, count=1)
    out = re.sub(r'<link rel="alternate" hreflang="zh-Hans" href="[^"]*">',
                 '<link rel="alternate" hreflang="zh-Hans" href="%s">' % BASE, out, count=1)
    out = re.sub(r'<link rel="alternate" hreflang="en" href="[^"]*">',
                 '<link rel="alternate" hreflang="en" href="%sen/">' % BASE, out, count=1)
    out = re.sub(r'<link rel="alternate" hreflang="ja" href="[^"]*">',
                 '<link rel="alternate" hreflang="ja" href="%sja/">' % BASE, out, count=1)
    # 去掉运行时跳转脚本（静态页不需要）
    out = re.sub(r"<script>\s*/\* 主站固定中文.*?</script>", "", out, flags=re.S)
    return out


def main():
    dicts = load_dict()
    ver = app_version()
    raw = io.open(os.path.join(DOCS, "index.html"), encoding="utf-8").read()
    for lang in ("en", "ja"):
        d = os.path.join(DOCS, lang)
        os.makedirs(d, exist_ok=True)
        html = build(lang, raw, dicts, ver)
        io.open(os.path.join(d, "index.html"), "w", encoding="utf-8",
                newline="").write(html)
        print("   %s/index.html 生成（%.1f KB）"
              % (lang, os.path.getsize(os.path.join(d, "index.html")) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
