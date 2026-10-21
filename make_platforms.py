# -*- coding: utf-8 -*-
"""打包所有平台的发布物，让每次发版保持一致。

用法：
    python make_platforms.py            # 打看图版 + macOS 包 + Linux 包
    python make_platforms.py --no-exe   # 跳过 PyInstaller（只重打源码包）

产物都写进 docs/：
    Prism-Viewer-<ver>.zip   看图版（便携，PyInstaller 目录 + 压缩）
    Prism-macOS-<ver>.zip    源码运行包（含 plugins/）
    Prism-Linux-<ver>.zip    源码运行包（含 plugins/，带 .desktop）
旧版本的同类文件会被自动删除。
"""
import glob
import io
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "src")
DOCS = os.path.join(ROOT, "docs")
PLUGINS = os.path.join(ROOT, "plugins")


def app_version():
    with io.open(os.path.join(SRC, "Prism.pyw"), encoding="utf-8") as fh:
        m = re.search(r'APP_VERSION = "([^"]+)"', fh.read())
    return m.group(1) if m else "0"


def clean_old(pattern):
    for path in glob.glob(os.path.join(DOCS, pattern)):
        os.remove(path)
        print("   删除旧文件", os.path.basename(path))


def zip_dir(stage, out_name, exe_perms=()):
    out = os.path.join(DOCS, out_name)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, _dirs, files in os.walk(stage):
            for fn in files:
                full = os.path.join(base, fn)
                rel = os.path.relpath(full, stage).replace("\\", "/")
                info = zipfile.ZipInfo(rel)
                perm = 0o755 if rel.endswith(exe_perms) else 0o644
                info.external_attr = perm << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as fh:
                    zf.writestr(info, fh.read())
    return out


def copy_plugins(dest):
    """自带插件随源码包一起发，否则用户装了也没有插件可用。"""
    pdir = os.path.join(dest, "plugins")
    os.makedirs(pdir, exist_ok=True)
    for fn in os.listdir(PLUGINS):
        if fn.endswith((".py", ".md")):
            shutil.copy(os.path.join(PLUGINS, fn), os.path.join(pdir, fn))


MAC_CMD = """#!/bin/bash
# Prism 启动器（macOS）
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "  没有找到 python3，请先安装：https://www.python.org/downloads/"
  read -n 1 -s -r -p "按任意键关闭…"; exit 1
fi
if ! python3 -c "import PIL" >/dev/null 2>&1; then
  echo "  缺少 Pillow，正在尝试安装…"
  python3 -m pip install --user pillow
fi
exec python3 "Prism.pyw" "$@"
"""

LINUX_SH = """#!/usr/bin/env bash
# Prism 启动脚本（Linux）
cd "$(dirname "$0")" || exit 1
for PY in python3 python; do
  if command -v "$PY" >/dev/null 2>&1; then
    if "$PY" -c "import tkinter, PIL" >/dev/null 2>&1; then
      exec "$PY" "Prism.pyw" "$@"
    fi
  fi
done
echo "  缺少依赖（需要 python3 + tkinter + Pillow）："
echo "    Debian/Ubuntu : sudo apt install python3-tk python3-pil"
echo "    Fedora        : sudo dnf install python3-tkinter python3-pillow"
echo "    Arch          : sudo pacman -S tk python-pillow"
read -r -p "按回车关闭…" _
exit 1
"""

LINUX_DESKTOP = """[Desktop Entry]
Type=Application
Version=1.0
Name=Prism
Name[zh_CN]=Prism 图片查看器
Comment=简约图片查看器
Comment[zh_CN]=简约图片查看器
Exec=/opt/Prism/prism.sh %f
Icon=/opt/Prism/Prism.png
Terminal=false
Categories=Graphics;Viewer;Photography;
MimeType=image/jpeg;image/png;image/webp;image/tiff;image/bmp;image/gif;image/x-nikon-nef;
StartupWMClass=Prism
"""


def pack_macos(ver):
    stage = os.path.join(ROOT, "_mac_stage")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    shutil.copy(os.path.join(SRC, "Prism.pyw"), stage)
    shutil.copy(os.path.join(SRC, "lang_data.py"), stage)
    shutil.copy(os.path.join(SRC, "Prism.png"), stage)
    copy_plugins(stage)
    with open(os.path.join(stage, "启动 Prism.command"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write(MAC_CMD)
    with open(os.path.join(stage, "README-macOS.txt"), "w",
              encoding="utf-8", newline="\n") as fh:
        fh.write("Prism %s — macOS 运行包（源码运行，不是编译好的 .app）\n\n"
                 "1. 安装 Python 3：https://www.python.org/downloads/\n"
                 "2. 双击「启动 Prism.command」（首次可能需要右键 -> 打开）\n"
                 "3. 若提示无法验证开发者：系统设置 -> 隐私与安全性 -> 仍要打开\n\n"
                 "自带插件在 plugins/ 目录，装好后在程序里点「插件」即可看到。\n"
                 "打不开时先在终端执行：chmod +x \"启动 Prism.command\"\n" % ver)
    clean_old("Prism-macOS-*.zip")      # 先删旧版本，再写新的
    out = zip_dir(stage, "Prism-macOS-%s.zip" % ver, exe_perms=(".command",))
    shutil.rmtree(stage, ignore_errors=True)
    return out


def pack_linux(ver):
    stage = os.path.join(ROOT, "_lin_stage")
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(stage)
    shutil.copy(os.path.join(SRC, "Prism.pyw"), stage)
    shutil.copy(os.path.join(SRC, "lang_data.py"), stage)
    shutil.copy(os.path.join(SRC, "Prism.png"), stage)
    copy_plugins(stage)
    with open(os.path.join(stage, "prism.sh"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(LINUX_SH)
    with open(os.path.join(stage, "Prism.desktop"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(LINUX_DESKTOP)
    with open(os.path.join(stage, "README-Linux.txt"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write("Prism %s — Linux 运行包（源码运行，不是编译好的二进制）\n\n"
                 "依赖：python3 + tkinter + Pillow\n"
                 "  Debian/Ubuntu : sudo apt install python3-tk python3-pil\n"
                 "  Fedora        : sudo dnf install python3-tkinter python3-pillow\n"
                 "  Arch          : sudo pacman -S tk python-pillow\n\n"
                 "运行：chmod +x prism.sh && ./prism.sh [图片]\n\n"
                 "装进应用菜单：整目录放 /opt/Prism，再把 Prism.desktop\n"
                 "拷到 /usr/share/applications/（里面的路径按需要改）。\n\n"
                 "自带插件在 plugins/ 目录。\n" % ver)
    clean_old("Prism-Linux-*.zip")
    out = zip_dir(stage, "Prism-Linux-%s.zip" % ver,
                  exe_perms=(".sh", ".desktop"))
    shutil.rmtree(stage, ignore_errors=True)
    return out


def pack_viewer(ver):
    build = os.path.join(ROOT, "_viewer_build")
    shutil.rmtree(build, ignore_errors=True)
    py = sys.executable
    args = [py, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", "PrismViewer",
            "--icon", os.path.join(SRC, "Prism.ico"),
            "--add-data", os.path.join(SRC, "Prism.ico") + os.pathsep + ".",
            "--add-data", os.path.join(SRC, "Prism.png") + os.pathsep + ".",
            "--distpath", os.path.join(build, "dist"),
            "--workpath", os.path.join(build, "w"),
            "--specpath", build,
            os.path.join(SRC, "Prism.pyw")]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    dist = os.path.join(build, "dist", "PrismViewer")
    exe = os.path.join(dist, "PrismViewer.exe")
    if not os.path.exists(exe):
        raise RuntimeError("看图版构建失败")
    # 看图版不含任何修图功能，因此也不带插件与模型
    for doc in ("README.md", "CHANGELOG.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy(src, dist)
    clean_old("Prism-Viewer-*.zip")
    out = zip_dir(dist, "Prism-Viewer-%s.zip" % ver)
    # 看图版也提供与完整版相同的自解压安装包
    inst = pack_viewer_installer(dist, ver)
    shutil.rmtree(build, ignore_errors=True)
    return [out, inst]



def pack_viewer_installer(dist, ver):
    """用 installer.pyw 把看图版打成和完整版一样的自解压安装包。"""
    root = ROOT
    inst_src = os.path.join(root, "src", "installer.pyw")
    txt = io.open(inst_src, encoding="utf-8").read()
    # APP 同时用于拼「启动 xxx.exe」的路径与安装目录名，必须与真实 exe 名一致
    txt = re.sub(r'APP = "[^"]*"', 'APP = "PrismViewer"', txt, count=1)
    txt = re.sub(r'FRIENDLY = "[^"]*"', 'FRIENDLY = "Prism 看图版"', txt, count=1)
    # 必须把行尾的 「 % VER」也一并匹配掉，否则会变成 "...%s" % VER % VER
    txt = re.sub(r'(?m)^DISPLAY = ".*" % VER$',
                 lambda _m: 'DISPLAY = "Prism Viewer %s" % VER', txt, count=1)
    txt = re.sub(r'VER = "[\d.]+"', 'VER = "%s"' % ver, txt, count=1)
    tmp_script = os.path.join(root, "_viewer_installer.py")
    io.open(tmp_script, "w", encoding="utf-8").write(txt)

    # 文件名必须是 payload.zip：安装器运行时按这个名字找内嵌资源
    tmpdir = os.path.join(root, "_viewer_inst_payload")
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir, exist_ok=True)
    payload = os.path.join(tmpdir, "payload.zip")
    if os.path.exists(payload):
        os.remove(payload)
    # 注意：payload 里的路径必须是「根目录就是 exe」，不能带 PrismViewer/ 这一层，
    # 否则安装后会变成 <目标>\PrismViewer\PrismViewer.exe
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(dist):
            for fn in files:
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, dist).replace("\\", "/")
                zf.write(full, arc)

    build = os.path.join(root, "_viewer_inst_build")
    shutil.rmtree(build, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--windowed", "--name", "Prism Viewer %s 自解压安装" % ver,
            "--icon", os.path.join(root, "src", "Prism.ico"),
            "--add-data", payload + os.pathsep + ".",
            "--add-data", os.path.join(root, "src", "Prism.ico") + os.pathsep + ".",
            "--distpath", os.path.join(build, "dist"),
            "--workpath", os.path.join(build, "w"),
            "--specpath", build, tmp_script]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    exe = os.path.join(build, "dist", "Prism Viewer %s 自解压安装.exe" % ver)
    if not os.path.exists(exe):
        raise RuntimeError("看图版安装包构建失败")
    clean_old("Prism-Viewer-Setup-*.exe")
    out = os.path.join(DOCS, "Prism-Viewer-Setup-%s.exe" % ver)
    shutil.copy(exe, out)
    shutil.rmtree(build, ignore_errors=True)
    if os.path.exists(tmp_script):
        os.remove(tmp_script)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return out


def pack_bigscreen(ver):
    """大屏版：纯看图、无快捷键、底栏大按钮；同样提供 zip + exe 安装器。"""
    build = os.path.join(ROOT, "_bigscreen_build")
    shutil.rmtree(build, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onedir", "--windowed", "--name", "PrismBigScreen",
            "--icon", os.path.join(SRC, "Prism.ico"),
            "--add-data", os.path.join(SRC, "Prism.ico") + os.pathsep + ".",
            "--add-data", os.path.join(SRC, "Prism.png") + os.pathsep + ".",
            "--distpath", os.path.join(build, "dist"),
            "--workpath", os.path.join(build, "w"),
            "--specpath", build,
            os.path.join(SRC, "Prism.pyw")]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    dist = os.path.join(build, "dist", "PrismBigScreen")
    exe = os.path.join(dist, "PrismBigScreen.exe")
    if not os.path.exists(exe):
        raise RuntimeError("大屏版构建失败")
    for doc in ("README.md", "CHANGELOG.md"):
        src = os.path.join(ROOT, doc)
        if os.path.exists(src):
            shutil.copy(src, dist)
    clean_old("Prism-BigScreen-*.zip")
    out = zip_dir(dist, "Prism-BigScreen-%s.zip" % ver)
    inst = pack_bigscreen_installer(dist, ver)
    shutil.rmtree(build, ignore_errors=True)
    return [out, inst]


def pack_bigscreen_installer(dist, ver):
    root = ROOT
    inst_src = os.path.join(root, "src", "installer.pyw")
    txt = io.open(inst_src, encoding="utf-8").read()
    txt = re.sub(r'APP = "[^"]*"', 'APP = "PrismBigScreen"', txt, count=1)
    txt = re.sub(r'FRIENDLY = "[^"]*"', 'FRIENDLY = "Prism 大屏版"', txt, count=1)
    txt = re.sub(r'(?m)^DISPLAY = ".*" % VER$',
                 lambda _m: 'DISPLAY = "Prism 大屏版 %s" % VER', txt, count=1)
    txt = re.sub(r'VER = "[\d.]+"', 'VER = "%s"' % ver, txt, count=1)
    tmp_script = os.path.join(root, "_bigscreen_installer.py")
    io.open(tmp_script, "w", encoding="utf-8").write(txt)

    tmpdir = os.path.join(root, "_bigscreen_inst_payload")
    shutil.rmtree(tmpdir, ignore_errors=True)
    os.makedirs(tmpdir, exist_ok=True)
    payload = os.path.join(tmpdir, "payload.zip")
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirs, files in os.walk(dist):
            for fn in files:
                full = os.path.join(dirpath, fn)
                arc = os.path.relpath(full, dist).replace("\\", "/")
                zf.write(full, arc)

    build = os.path.join(root, "_bigscreen_inst_build")
    shutil.rmtree(build, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--onefile", "--windowed", "--name",
            "Prism Big Screen %s 自解压安装" % ver,
            "--icon", os.path.join(root, "src", "Prism.ico"),
            "--add-data", payload + os.pathsep + ".",
            "--add-data", os.path.join(root, "src", "Prism.ico") + os.pathsep + ".",
            "--distpath", os.path.join(build, "dist"),
            "--workpath", os.path.join(build, "w"),
            "--specpath", build, tmp_script]
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    exe = os.path.join(build, "dist",
                       "Prism Big Screen %s 自解压安装.exe" % ver)
    if not os.path.exists(exe):
        raise RuntimeError("大屏版安装包构建失败")
    clean_old("Prism-BigScreen-Setup-*.exe")
    out = os.path.join(DOCS, "Prism-BigScreen-Setup-%s.exe" % ver)
    shutil.copy(exe, out)
    shutil.rmtree(build, ignore_errors=True)
    if os.path.exists(tmp_script):
        os.remove(tmp_script)
    shutil.rmtree(tmpdir, ignore_errors=True)
    return out


def main():
    ver = app_version()
    do_exe = "--no-exe" not in sys.argv
    print("== Prism %s 平台包 ==" % ver)
    outs = []
    if do_exe:
        print("  [1/4] 看图版（便携 zip + 安装包，较慢）…")
        outs.extend(pack_viewer(ver))
        print("  [2/4] 大屏版（便携 zip + 安装包，较慢）…")
        outs.extend(pack_bigscreen(ver))
    print("  [3/4] macOS 源码包…")
    outs.append(pack_macos(ver))
    print("  [4/4] Linux 源码包…")
    outs.append(pack_linux(ver))
    for path in outs:
        if not os.path.exists(path):
            print("   !! 缺失 %s" % path)
            continue
        print("   -> %-28s %7.1f KB" % (os.path.basename(path),
                                        os.path.getsize(path) / 1024.0))


if __name__ == "__main__":
    main()
