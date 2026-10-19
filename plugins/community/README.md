**中文** · [English](README.en.md) · [日本語](README.ja.md)

# 社区 / 官方插件目录

Prism 自带 12 个插件（索引见 `../README.md`）。外部插件有两种收录方式：

1. **进官方清单** `plugins/index.json`：用户在「插件市场」里能浏览、一键安装、检查更新。
2. **不进仓库**：给一个 `.py` 的 http(s) 直链 + SHA-256，用户用「插件 → 从网址安装…」装。

`plugins/README.md` 里的两张表格由 `tools/make_plugin_index.py` 从
**插件源码 + index.json** 生成，不手改表格。

## 收录标准

- 必须能读源码：不接受二进制、加密或混淆过的插件。
- 不联网上传：不得有网络请求，不得把用户图片外传；确有需要的必须在 `PLUGIN.network` 声明。
- 不破坏原图：只返回新图，不覆盖用户文件；写文件的必须在 `PLUGIN.writes_files` 声明。
- 必须声明 `api`，且与当前支持的版本（1 / 2）一致。
- 提交前请按 `.github/ISSUE_TEMPLATE/plugin-submission.yml` 填表。

## 进官方清单的 PR 要改什么

1. `docs/plugins/<文件名>.py`：插件源码（文件名用 ASCII）。
2. `plugins/index.json`：加一项，字段见 [docs/plugin-api.md](../../docs/plugin-api.md)：
   `id` / `name`（zh/en/ja）/ `version` / `api` / `author` / `description`（zh/en/ja）/
   `network` / `writes_files` / `url` / `sha256` / `source`。
3. 跑 `python tools/make_plugin_index.py --check`，必须通过（它会校验 SHA-256、
   三语字段、README 与 docs 副本是否最新）。

应用侧不会执行清单里的任何代码；安装时仍然只解析 AST，SHA-256 不符直接拒绝。
