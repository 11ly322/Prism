# -*- coding: utf-8 -*-
r"""Prism 自解压安装器。

双击后由你选择：
  · 安装到本机  -> %LOCALAPPDATA%\Prism\<版本>，建开始菜单快捷方式、登记卸载项
  · 就地解压    -> 解到本 exe 旁边的 Prism 文件夹（绿色便携，不写注册表）
两种情况都会显示解压到了哪里，并提供「打开文件夹」和「启动 Prism」。
"""
import os
import sys
import time
import subprocess
import zipfile

VER = "9.13.1"
APP = "Prism"
DISPLAY = "Prism %s" % VER


def _base():
    return getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))


def payload_path():
    return os.path.join(_base(), "payload.zip")


def exe_home():
    """本安装器 exe 所在目录（不是临时解包目录）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def install_target():
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, APP, VER)


def portable_target():
    return os.path.join(exe_home(), APP)


def shortcut_path():
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs",
                        "%s.lnk" % APP)


def desktop_shortcut_path():
    """桌面路径用系统 API 取，这样 OneDrive 重定向过的桌面也能找对。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Environment]::GetFolderPath('Desktop')"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        p = (out or "").strip()
        if p:
            return os.path.join(p, "%s.lnk" % APP)
    except Exception:
        pass
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(home, "Desktop", "%s.lnk" % APP)


def make_shortcut(exe, lnk=None):
    lnk = lnk or shortcut_path()
    try:
        os.makedirs(os.path.dirname(lnk), exist_ok=True)
        ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
              "$s.TargetPath='%s';$s.WorkingDirectory='%s';"
              "$s.IconLocation='%s,0';$s.Description='%s';$s.Save()"
              % (lnk, exe, os.path.dirname(exe), exe, DISPLAY))
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", ps],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       timeout=40)
        return os.path.exists(lnk)
    except Exception:
        return False


def register_uninstall(dest, exe):
    try:
        import winreg
        key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\%s" % APP
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key)
        winreg.SetValueEx(k, "DisplayName", 0, winreg.REG_SZ, DISPLAY)
        winreg.SetValueEx(k, "DisplayVersion", 0, winreg.REG_SZ, VER)
        winreg.SetValueEx(k, "InstallLocation", 0, winreg.REG_SZ, dest)
        winreg.SetValueEx(k, "DisplayIcon", 0, winreg.REG_SZ, exe)
        winreg.SetValueEx(k, "Publisher", 0, winreg.REG_SZ, "Prism")
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "UninstallString", 0, winreg.REG_SZ,
                          '"%s"' % os.path.join(dest, "uninstall.cmd"))
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


def write_uninstaller(dest):
    bat = "\r\n".join([
        "@echo off",
        "echo 正在卸载 %s ..." % DISPLAY,
        "timeout /t 1 >nul",
        'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion'
        '\\Uninstall\\%s" /f >nul 2>&1' % APP,
        'del "%s" >nul 2>&1' % shortcut_path(),
        'del "%s" >nul 2>&1' % desktop_shortcut_path(),
        "cd /d %%TEMP%%",
        'rmdir /s /q "%s"' % dest,
        "echo 已卸载。",
        "timeout /t 2 >nul",
    ])
    try:
        with open(os.path.join(dest, "uninstall.cmd"), "w",
                  encoding="gbk", errors="ignore") as fh:
            fh.write(bat)
    except Exception:
        pass


def app_running():
    """Prism 正在运行时不能覆盖它的 dll（Windows 文件锁）。"""
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Prism.exe", "/NH"],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return "Prism.exe" in (out or "")
    except Exception:
        return False


def close_app():
    try:
        subprocess.run(["taskkill", "/IM", "Prism.exe", "/F"],
                       capture_output=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        time.sleep(1.2)
        return not app_running()
    except Exception:
        return False


def extract_to(dest, progress):
    src = payload_path()
    if not os.path.exists(src):
        raise RuntimeError("安装包损坏：找不到内置数据。")
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(src) as zf:
        names = zf.namelist()
        total = max(1, len(names))
        for i, name in enumerate(names):
            zf.extract(name, dest)
            if i % 60 == 0:
                progress("正在解压… %d%%" % int(100 * i / total))
    try:
        with open(os.path.join(dest, "version.txt"), "w") as fh:
            fh.write(VER)
    except Exception:
        pass
    return os.path.join(dest, APP + ".exe")


def silent_main(args):
    """无界面安装：/S 装到本机，/S --portable 就地解压。用于脚本化部署。"""
    portable = "--portable" in args or "/portable" in args
    dest = portable_target() if portable else install_target()
    if app_running():
        close_app()          # 静默模式下自动关闭，否则必然覆盖失败
    try:
        exe = extract_to(dest, lambda s: None)
        if not portable:
            make_shortcut(exe)
            make_shortcut(exe, desktop_shortcut_path())
            register_uninstall(dest, exe)
            write_uninstaller(dest)
    except Exception as exc:
        sys.stderr.write("install failed: %s\n" % exc)
        return 1
    return 0


def _dpi_aware():
    """声明 DPI 感知。

    不声明的话，高缩放比下 Windows 会按 96 DPI 虚拟化再位图放大，
    控件实际可用尺寸比我们算的小，底部的按钮就会被裁掉 —— 表现就是
    「安装界面没有确认按钮」。主程序 Prism 本身就是声明了的，这里保持一致。
    """
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "/s" in args or "--silent" in args or "-s" in args:
        return silent_main(args)
    import tkinter as tk
    from tkinter import messagebox, filedialog

    _dpi_aware()
    root = tk.Tk()
    root.title("安装 %s" % DISPLAY)
    root.configure(bg="#181b20")
    try:
        ui = max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        ui = 1.0

    def px(v):
        return int(round(v * ui))

    # 这里原来是固定的 560x300 物理像素，而字体与内边距都按 DPI 放大，
    # 200% 缩放下内容把窗口撑爆，底部按钮被挤出可视区域 —— 就是「没有确认按钮」。
    root.geometry("%dx%d" % (px(620), px(380)))
    root.resizable(False, False)
    # 按钮栏先 pack，先 pack 的先分配空间，保证它一定在窗口内
    btnbar = tk.Frame(root, bg="#181b20")
    btnbar.pack(side="bottom", fill="x", pady=px(14))
    ico = os.path.join(_base(), "Prism.ico")
    try:
        if os.path.exists(ico):
            root.iconbitmap(ico)
    except Exception:
        pass
    try:
        root.eval("tk::PlaceWindow . center")
    except Exception:
        pass

    ui_font = ("Microsoft YaHei UI", 10)
    big = ("Microsoft YaHei UI", 13, "bold")
    small = ("Microsoft YaHei UI", 9)

    tk.Label(root, text=DISPLAY, font=big, bg="#181b20", fg="#f0f2f5").pack(
        pady=(22, 4))
    tk.Label(root, text="选择一种方式解压到本机", font=small, bg="#181b20",
             fg="#8a8f98").pack()

    box = tk.Frame(root, bg="#1f2329")
    box.pack(fill="x", padx=26, pady=(14, 0), ipady=6)
    p1 = tk.StringVar(value=install_target())
    p2 = tk.StringVar(value=portable_target())

    def row(title, var, tip):
        f = tk.Frame(box, bg="#1f2329")
        f.pack(fill="x", padx=12, pady=5)
        tk.Label(f, text=title, font=ui_font, bg="#1f2329", fg="#e6e8ec",
                 width=12, anchor="w").pack(side="left")
        e = tk.Entry(f, textvariable=var, font=small, bg="#15181d", fg="#cfd3da",
                     bd=0, highlightthickness=1, highlightbackground="#2c323a",
                     highlightcolor="#4c9aff")
        e.pack(side="left", fill="x", expand=True, ipady=3)
        b = tk.Button(f, text="…", font=small, bg="#2a2f37", fg="#e6e8ec",
                      relief="flat", bd=0, width=3, cursor="hand2",
                      command=lambda v=var: (v.set(
                          filedialog.askdirectory(parent=root,
                                                  initialdir=os.path.dirname(v.get()))
                          or v.get())))
        b.pack(side="left", padx=(6, 0))
        tk.Label(box, text=tip, font=small, bg="#1f2329",
                 fg="#6f7681", anchor="w").pack(fill="x", padx=(96, 12))

    row("安装到本机", p1, "会建开始菜单快捷方式，并在「应用和功能」里登记卸载项")
    row("就地解压", p2, "解到本 exe 旁边，绿色便携，不写注册表")

    opts = tk.Frame(root, bg="#181b20")
    opts.pack(fill="x", padx=26, pady=(10, 0))
    want_start = tk.IntVar(value=1)
    want_desk = tk.IntVar(value=1)
    for var, text in ((want_start, "创建开始菜单快捷方式"),
                      (want_desk, "创建桌面快捷方式")):
        cb = tk.Checkbutton(
            opts, text=text, variable=var, font=small, bg="#181b20",
            fg="#c9ced6", activebackground="#181b20", activeforeground="#ffffff",
            selectcolor="#15181d", bd=0, highlightthickness=0, anchor="w",
            cursor="hand2")
        cb.pack(side="left", padx=(0, 18))

    status = tk.Label(root, text="", font=small, bg="#181b20", fg="#8a8f98")
    status.pack(pady=(10, 0))

    # 按钮栏已在上面创建并占住底部

    def start(mode):
        if app_running():
            ans = messagebox.askyesno(
                "Prism 正在运行",
                "检测到 Prism 正在运行。\n\n"
                "安装需要写入程序文件，正在运行的程序会锁定这些文件，"
                "导致解压中途失败。\n\n是否自动关闭 Prism 并继续？",
                parent=root)
            if not ans:
                status.configure(text="已取消：请手动关闭 Prism 后再试",
                                 fg="#ffd479")
                return
            status.configure(text="正在关闭 Prism…")
            root.update()
            if not close_app():
                status.configure(
                    text="无法关闭 Prism，请手动退出后重试", fg="#ff8a80")
                return
        for w in btnbar.winfo_children():
            w.configure(state="disabled")

        def progress(text):
            status.configure(text=text)
            root.update_idletasks()
            root.update()

        try:
            if mode == "install":
                dest = p1.get().strip() or install_target()
                exe = extract_to(dest, progress)
                made = []
                if want_start.get():
                    progress("正在创建开始菜单快捷方式")
                    if make_shortcut(exe):
                        made.append("开始菜单")
                if want_desk.get():
                    progress("正在创建桌面快捷方式")
                    if make_shortcut(exe, desktop_shortcut_path()):
                        made.append("桌面")
                register_uninstall(dest, exe)
                write_uninstaller(dest)
                # 把结果写清楚：桌面的真实路径会被系统重定向（本机就在 D: 盘），
                # 不显示出来用户根本不知道去哪儿找。
                want = []
                if want_start.get():
                    want.append("开始菜单" + ("✓" if "开始菜单" in made else "✗"))
                if want_desk.get():
                    want.append("桌面" + ("✓" if "桌面" in made else "✗"))
                note = "已安装　" + "　".join(want)
            else:
                dest = p2.get().strip() or portable_target()
                exe = extract_to(dest, progress)
                made = []
                if want_desk.get():
                    progress("正在创建桌面快捷方式")
                    if make_shortcut(exe, desktop_shortcut_path()):
                        made.append("桌面")
                note = ("已就地解压（不写注册表）　桌面" +
                        ("✓" if made else ("✗" if want_desk.get() else "—")))
        except Exception as exc:
            status.configure(text="失败：" + str(exc)[:60], fg="#ff8a80")
            for w in btnbar.winfo_children():
                w.configure(state="normal")
            return
        show_done(dest, exe, note)

    def open_dir(path):
        try:
            os.startfile(path)
        except Exception:
            pass

    def show_done(dest, exe, note):
        for w in list(root.winfo_children()):
            if w is not btnbar:
                w.destroy()
        btnbar.pack_forget()
        tk.Label(root, text="完成", font=big, bg="#181b20", fg="#7ee787").pack(
            pady=(30, 6))
        tk.Label(root, text=note, font=ui_font, bg="#181b20", fg="#e6e8ec").pack()
        tk.Label(root, text=dest, font=small, bg="#181b20", fg="#8a8f98",
                 wraplength=500).pack(pady=(10, 0), padx=20)
        if "桌面✓" in note:
            tk.Label(root, text="桌面快捷方式在：" + desktop_shortcut_path(),
                     font=small, bg="#181b20", fg="#6f7681",
                     wraplength=520).pack(pady=(6, 0), padx=20)
        bar = tk.Frame(root, bg="#181b20")
        bar.pack(pady=22)

        def mk(text, cmd, accent=False):
            b = tk.Button(bar, text=text, font=ui_font, bd=0, relief="flat",
                          padx=16, pady=6, cursor="hand2", command=cmd,
                          bg="#4c9aff" if accent else "#2a2f37",
                          fg="#0d1014" if accent else "#e6e8ec",
                          activebackground="#6bb0ff" if accent else "#353b44",
                          activeforeground="#0d1014" if accent else "#ffffff")
            b.pack(side="left", padx=6)
            return b

        mk("启动 Prism", lambda: (subprocess.Popen([exe],
                                                cwd=os.path.dirname(exe)),
                                root.after(400, root.destroy)), True)
        mk("打开文件夹", lambda: open_dir(dest))
        mk("关闭", root.destroy)

    def on_install():
        start("install")

    def on_portable():
        start("portable")

    b1 = tk.Button(btnbar, text="安装到本机", font=ui_font, bd=0, relief="flat",
                   padx=18, pady=7, cursor="hand2", bg="#4c9aff", fg="#0d1014",
                   activebackground="#6bb0ff", activeforeground="#0d1014",
                   command=on_install)
    b1.pack(side="left", padx=6)
    b2 = tk.Button(btnbar, text="就地解压（便携）", font=ui_font, bd=0,
                   relief="flat", padx=18, pady=7, cursor="hand2", bg="#2a2f37",
                   fg="#e6e8ec", activebackground="#353b44",
                   activeforeground="#ffffff", command=on_portable)
    b2.pack(side="left", padx=6)

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
