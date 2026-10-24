# Prism 源码交接

最后更新：2026-10-24  
当前版本：**9.15.10alpha**（预发布；最后一个稳定版是 9.15.9）

## 换电脑后先做这一步

```powershell
git clone https://github.com/11ly322/Prism.git
cd Prism
git checkout main
git pull
```

仓库里已经有全部 Prism 源码、文档、设计记录、测试、插件和构建脚本。
安装包、`Prism.exe`、`_internal/`、日志与本地设置没有进 Git，发布产物在 GitHub Releases。

## 依赖

源码运行只需要 Python 3.12+ 和 Pillow；美颜相关测试建议装 numpy。

```powershell
python -m pip install pillow numpy
```

打包/发版再装：

```powershell
python -m pip install -r requirements-build.txt
```

`requirements-build.txt` 包含 PyInstaller、Pillow、numpy 的锁定版本。

## 常用命令

```powershell
python src/Prism.pyw                 # 直接启动
python tools/runall.py --fast        # 20 套快速回归
python tools/beautycheck.py          # 美颜全量回归
python tools/motioncheck.py          # 动效/开关/退出清理
python check_versions.py             # 版本号一致性
```

Windows 发版：

```powershell
powershell -ExecutionPolicy Bypass -File .\make_release.ps1
```

发版脚本会跑词条、文档、插件索引和快速回归，然后打包 8 个产物、更新网站、
创建/更新 GitHub Release，并做下载链接自检。需要本机已登录 `gh`。

只做页面和链接检查、不打包：

```powershell
powershell -ExecutionPolicy Bypass -File .\make_release.ps1 -CheckOnly
```

## 源码地图

| 路径 | 内容 |
| :--- | :--- |
| `src/Prism.pyw` | 主程序：查看器、右侧修图栏、美颜、动效 |
| `src/installer.pyw` | 自解压安装器 |
| `src/lang_data.py` | 中文 / English / 日本語界面词条 |
| `plugins/` | 自带插件源码 |
| `tools/` | 回归测试、质量台架、打包与站点生成 |
| `docs/` | 官网、三语文档、插件文档；二进制由 Release 提供 |
| `design/` | 设计记录、截图、外观基线、质量台架 JSON |
| `.github/` | CI 与 Pages 工作流 |
| `make_release.ps1` / `make_platforms.py` | 发版与跨平台打包 |

## 不会进 Git 的本地文件

- `Prism_settings.json`、`src/Prism_settings.json`：本机设置
- `plugin_catalog.json`、`src/plugin_catalog.json`：运行时/构建生成的清单缓存
- `logs/`、`*.log`：日志
- `Prism.exe`、`_internal/`、`*.spec`、`_build/`：构建产物
- 根目录的 `Prism * 自解压安装.exe`、`docs/*.exe`、`docs/*.zip`：发布产物
- `dsh-preset-switch-bundle/`：DSH 插件，不是 Prism 源码，已被 `.git/info/exclude` 排除

这些都可以从源码重新生成；不要为了“全量上传”把安装包或本机设置提交进仓库。

## Alpha 说明

`9.15.10alpha` 是预发布版：

- 应用标题、安装器、网站、资产文件名统一带 `alpha`。
- GitHub Release 标记为 prerelease，不会成为 `latest`。
- 更新检查能正确比较 `9.15.10alpha` 与稳定版，不会把旧稳定版误报成新版本。
- 若要让新电脑继续开发，直接基于 `main` 开分支即可；不要把 alpha 标签当稳定版。

## 发布后检查

```powershell
python tools/verifysite.py --ver 9.15.10alpha
```

检查首页版本、三语页面、8 个下载链接和插件清单。CI/Pages 在 GitHub Actions 里看
`CI` 与 `Deploy Pages` 两个 workflow。
