# CI 与 Pages 部署

已启用（2026-10-20）：

- `.github/workflows/ci.yml`：push / PR 跑静态门禁（词条、插件索引、三语文档、
  文档 HTML、版本号），一个 Ubuntu 静态 job（清单/文档/HTML/版本），
  另有一个 `continue-on-error` 的 GUI 回归任务（插件/市场/三语/启动）。
- `.github/workflows/plugin-pr.yml`：PR 改 `plugins/index.json`、`plugins/*.py`
  或 `docs/plugins/**` 时自动校验 id 规则、schema、SHA-256、内置冲突与 README 索引。
- `.github/workflows/pages.yml`：push `docs/**` 或手动触发时，用
  `actions/deploy-pages` 发布 `docs/`。

Pages 的 Source 已切成 **GitHub Actions**；legacy 分支部署不再使用。
回退方式：Settings → Pages → Source 改回 `Deploy from a branch` → `main` / `/docs`。

`main` 分支保护已启用：PR 合并前要求 `static` + `static-linux` 通过
（`gui` 仍 `continue-on-error`，不阻塞）；管理员可直接推送。

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
- GUI 任务依赖 GitHub Windows runner 的桌面会话；失败时不会阻塞 CI 主结论
  （`continue-on-error: true`），但会在日志里保留原因。
