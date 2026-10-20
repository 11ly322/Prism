# -*- coding: utf-8 -*-
"""软打样：sRGB -> 目标 ICC -> sRGB 的双变换预览。"""
import glob
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL = []


def ok(name, cond, detail=""):
    print("  %s %-34s %s" % ("PASS" if cond else "FAIL", name, detail))
    if not cond:
        FAIL.append(name)


def find_profile():
    if os.name != "nt":
        return ""
    base = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "System32", "spool", "drivers", "color")
    for path in glob.glob(os.path.join(base, "*.[iI][cC][cCmM]")):
        name = os.path.basename(path).lower()
        if "adobergb" in name or "displayp3" in name:
            return path
    return ""


def main():
    from PIL import Image, ImageChops, ImageCms, ImageStat
    import importlib.machinery
    mod = importlib.machinery.SourceFileLoader(
        "soft9", os.path.join(ROOT, "src", "Prism.pyw")).load_module()
    path = find_profile()
    if not path:
        print("  SKIP 系统里没有 AdobeRGB / Display P3 profile")
        return 0

    t1, t2, name = mod._build_soft_proof(path)
    ok("构建双变换", bool(t1 and t2), name)

    img = Image.new("RGB", (240, 160), (200, 30, 40))
    for x in range(0, 240, 24):
        for y in range(0, 160, 24):
            img.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, 128))
    fake = types.SimpleNamespace(soft_proof_transforms=(t1, t2))
    out = mod.QPEApp._apply_soft_proof(fake, img)
    ok("输出尺寸不变", out.size == img.size, str(out.size))
    ok("输出仍为 RGB", out.mode == "RGB", out.mode)

    # 独立算一遍同样的双变换，逐像素比较
    exp = ImageCms.applyTransform(img, t1)
    exp = ImageCms.applyTransform(exp, t2)
    diff = ImageChops.difference(out, exp)
    mx = max(band[1] for band in ImageStat.Stat(diff).extrema)
    ok("与独立双变换一致", mx <= 1, "max Δ=%d" % mx)

    # 用 sRGB 自身做目标，双变换应接近恒等
    srgb = ImageCms.createProfile("sRGB")
    prof = ImageCms.ImageCmsProfile(srgb)
    tmp = os.path.join(os.environ.get("TEMP", "."), "prism_soft_srgb.icc")
    open(tmp, "wb").write(prof.tobytes())
    try:
        a, b, _ = mod._build_soft_proof(tmp)
        fake2 = types.SimpleNamespace(soft_proof_transforms=(a, b))
        same = mod.QPEApp._apply_soft_proof(fake2, img)
        d = ImageChops.difference(same, img)
        smx = max(band[1] for band in ImageStat.Stat(d).extrema)
        ok("sRGB 目标近似恒等", smx <= 1, "max Δ=%d" % smx)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    print()
    if FAIL:
        print(">>> 软打样回归失败 %d 项：%s" % (len(FAIL), FAIL))
        return 1
    print(">>> 软打样回归通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
