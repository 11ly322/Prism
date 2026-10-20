# -*- coding: utf-8 -*-
"""用系统里的真实 AdobeRGB / Display P3 profile 验证 ICC 链路。

Windows 的 spool\\drivers\\color 通常自带厂商 profile；没有就跳过（CI 的
Linux/macOS runner 一般没有），不把 profile 文件提交进仓库。
"""
import glob
import importlib.machinery
import io
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def find_profiles():
    if os.name != "nt":
        return []
    base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "System32", "spool", "drivers", "color")
    picked = []
    for path in glob.glob(os.path.join(base, "*.[iI][cC][cCmM]")):
        name = os.path.basename(path).lower()
        if "adobergb" in name:
            picked.append(("AdobeRGB", path))
        elif "displayp3" in name:
            picked.append(("Display P3", path))
    return picked


def chart():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (640, 360), (18, 18, 20))
    d = ImageDraw.Draw(img)
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
              (0, 255, 255), (255, 0, 255), (255, 128, 0), (40, 180, 90),
              (240, 220, 200), (30, 40, 60)]
    for i, c in enumerate(colors):
        x = (i % 5) * 128
        y = (i // 5) * 180
        d.rectangle([x, y, x + 127, y + 179], fill=c)
    for i in range(0, 640, 8):
        v = int(255 * i / 639.0)
        d.line([(i, 0), (i, 359)], fill=(v, 255 - v, (v * 2) % 256))
    return img


def main():
    from PIL import Image, ImageChops, ImageCms, ImageStat
    mod = importlib.machinery.SourceFileLoader(
        "icc_prof", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    profiles = find_profiles()
    if not profiles:
        print("  SKIP 系统里没有 AdobeRGB / Display P3 profile")
        return 0

    tmp = tempfile.mkdtemp(prefix="prism_icc_prof_")
    try:
        for label, path in profiles:
            icc = open(path, "rb").read()
            desc = mod._icc_description(icc)
            jpg = os.path.join(tmp, "%s.jpg" % label.replace(" ", "_"))
            chart().save(jpg, quality=95, icc_profile=icc)
            doc = mod.ImageDoc.load(jpg)
            ok("%s 能打开" % label, doc.size == (640, 360), str(doc.size))
            ok("%s 识别为需转换" % label, bool(doc.icc_converted),
               doc.icc_source)
            ok("%s 转后仍为 RGB" % label, doc.img.mode == "RGB",
               doc.img.mode)

            # 用同一条 ImageCms 路径独立算一遍，逐像素比较
            src = Image.open(jpg).convert("RGB")
            exp = ImageCms.profileToProfile(
                src, ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                ImageCms.createProfile("sRGB"), renderingIntent=0,
                outputMode="RGB")
            diff = ImageChops.difference(doc.img, exp)
            mx = max(band[1] for band in ImageStat.Stat(diff).extrema)
            ok("%s 与独立转换一致" % label, mx <= 1, "max Δ=%d" % mx)

            # 透明 PNG：转色不能把 alpha 丢掉
            png = os.path.join(tmp, "%s.png" % label.replace(" ", "_"))
            im = chart().convert("RGBA")
            im.putpixel((0, 0), (255, 0, 0, 0))
            im.save(png, icc_profile=icc)
            doc2 = mod.ImageDoc.load(png)
            ok("%s 保留透明通道" % label, doc2.img.mode == "RGBA",
               doc2.img.mode)
            ok("%s 透明角落" % label, doc2.img.getpixel((0, 0))[3] == 0,
               str(doc2.img.getpixel((0, 0))))

            # 真实照片（design/sample.jpg）再跑一遍转换一致性
            sample = os.path.join(ROOT, "design", "sample.jpg")
            if os.path.isfile(sample):
                pjpg = os.path.join(tmp, "%s_photo.jpg" % label.replace(" ", "_"))
                Image.open(sample).convert("RGB").save(
                    pjpg, quality=92, icc_profile=icc)
                pd = mod.ImageDoc.load(pjpg)
                pexp = ImageCms.profileToProfile(
                    Image.open(pjpg).convert("RGB"),
                    ImageCms.ImageCmsProfile(io.BytesIO(icc)),
                    ImageCms.createProfile("sRGB"), renderingIntent=0,
                    outputMode="RGB")
                pdiff = ImageChops.difference(pd.img, pexp)
                pmx = max(band[1] for band in ImageStat.Stat(pdiff).extrema)
                ok("%s 真实照片转换一致" % label, pmx <= 1,
                   "max Δ=%d" % pmx)

            out = os.path.join(tmp, "%s_out.jpg" % label.replace(" ", "_"))
            doc.img.save(out, quality=92,
                         icc_profile=mod._srgb_icc_bytes())
            with Image.open(out) as im2:
                out_icc = im2.info.get("icc_profile")
            ok("%s 导出 sRGB profile" % label,
               "srgb" in mod._icc_description(out_icc).lower(),
               mod._icc_description(out_icc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAIL:
        print(">>> 真实 profile ICC 回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 真实 profile ICC 回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
