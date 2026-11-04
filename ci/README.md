# CI 与 Pages 部署

已启用（2026-10-20）：

- `.github/workflows/ci.yml`：push / PR 跑静态门禁（词条、插件索引、三语文档、
  文档 HTML、版本号），Ubuntu 与 macOS 各一个静态 job（清单/文档/HTML/版本），
  另有一个 GUI 回归任务（插件/市场/三语/启动）。
- `.github/workflows/plugin-pr.yml`：PR 改 `plugins/index.json`、`plugins/*.py`
  或 `docs/plugins/**` 时自动校验 id 规则、schema、SHA-256、内置冲突与 README 索引。
- `.github/workflows/pages.yml`：push `docs/**` 或手动触发时，用
  `actions/deploy-pages` 发布 `docs/`。

Pages 的 Source 已切成 **GitHub Actions**；legacy 分支部署不再使用。
回退方式：Settings → Pages → Source 改回 `Deploy from a branch` → `main` / `/docs`。

`main` 分支保护已启用：PR 合并前要求 `static` + `static-linux` + `static-macos` + `gui`
通过；管理员可直接推送。

## 权限

推送/修改 workflow 需要 token 带 `workflow` scope。当前账号已授权：

```bash
gh auth refresh --hostname github.com --scopes workflow
```

以前因缺这个 scope 暂存的 `ci.yml.pending` / `pages.yml.pending` 已删除；
`.github/workflows/` 是唯一来源。

## 注意

- Windows runner 的输出编码靠 job 里的 `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`。
- `.gitattributes` 强制 `.py` / `.md` / `.json` 等用 LF；否则 Windows 检出的 CRLF
  会让 `plugins/index.json` 的 SHA-256 与文件不一致，市场安装会被拒绝。
- GUI 任务依赖 GitHub Windows runner 的桌面会话；转正后失败会使 CI 结论失败，
  日志保留原因；Windows runner 无桌面导致持续失败时，恢复 `continue-on-error`。

## GUI job 转正记录

- 2026-10-20 启用观察；启用当天的前两次 CI 因 Windows 输出编码和插件 SHA 行尾问题
  失败，修复后从 13:16Z 起恢复正常。
- 到 **2026-11-03** 复核：修复后共 96 次 CI 运行，`gui` job 全部 success；因此已删除
  `.github/workflows/ci.yml` 里 `gui` 的 `continue-on-error: true`。
- `gui` 现在是普通 job，并已加入 `main` 的必需检查；失败会阻止合并。
- 如果 Windows runner 没有可用桌面导致持续失败，恢复 `continue-on-error` 并把它从
  必需检查移除，把失败原因记进 issue。
