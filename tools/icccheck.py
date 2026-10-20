# -*- coding: utf-8 -*-
"""ICC / 导出色空间回归：带 sRGB profile 的图能读、导出会写 sRGB profile。"""
import importlib.machinery
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-30s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def main():
    from PIL import Image
    mod = importlib.machinery.SourceFileLoader(
        "icc9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    icc = mod._srgb_icc_bytes()
    ok("能生成 sRGB profile", bool(icc), "%d 字节" % len(icc or b""))

    tmp = tempfile.mkdtemp(prefix="prism_icc_")
    try:
        p = os.path.join(tmp, "tagged.jpg")
        Image.new("RGB", (320, 240), (120, 160, 90)).save(
            p, quality=90, icc_profile=icc)
        doc = mod.ImageDoc.load(p)
        ok("带 profile 的图能打开", doc.size == (320, 240), str(doc.size))
        ok("记录色彩空间", "srgb" in (doc.icc_source or "").lower(),
           doc.icc_source)
        ok("已是 sRGB 不重复转换", doc.icc_converted is False)

        plain = os.path.join(tmp, "plain.jpg")
        Image.new("RGB", (64, 48), (10, 20, 30)).save(plain)
        doc2 = mod.ImageDoc.load(plain)
        ok("无 profile 按 sRGB", doc2.icc_source == "sRGB",
           doc2.icc_source)

        out = os.path.join(tmp, "out.jpg")
        doc.img.save(out, quality=90, icc_profile=icc)
        with Image.open(out) as im:
            got = im.info.get("icc_profile")
        ok("导出写入 sRGB profile", bool(got), "%d 字节" % len(got or b""))
        ok("写出的 profile 可识别",
           "srgb" in mod._icc_description(got).lower(),
           mod._icc_description(got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> ICC 回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> ICC 回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
