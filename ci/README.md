# CI 与 Pages 部署（待启用）

当前 GitHub token 只有 `repo / read:org / gist`，**没有 `workflow` 权限**，所以
`.github/workflows/` 下的文件推不上去（会报 `refusing to allow an OAuth App to create
or update workflow ... without workflow scope`）。

启用方式（二选一）：

1. **网页端添加**：在 GitHub 网页新建
   - `.github/workflows/ci.yml` ← 复制 `ci/ci.yml.pending`
   - `.github/workflows/pages.yml` ← 复制 `ci/pages.yml.pending`
2. **本地授权**：
   ```bash
   gh auth refresh -s workflow
   mkdir -p .github/workflows
   cp ci/ci.yml.pending .github/workflows/ci.yml
   cp ci/pages.yml.pending .github/workflows/pages.yml
   git add .github/workflows && git commit -m "ci: enable workflows" && git push
   ```

## Pages 切换到 Actions 的顺序（重要）

`pages.yml` 只有在仓库里**已经存在**之后，才能把 Pages 的 Source 改成 GitHub Actions；
顺序反了站点会 404：

1. 先让 `pages.yml` 出现在 `main`；
2. Settings → Pages → Build and deployment → Source 选 **GitHub Actions**；
3. 手动跑一次 Deploy Pages workflow，确认 `https://11ly322.github.io/Prism/` 200；
4. 之后 push `docs/` 自动部署，不再依赖 legacy build。

回退：Source 改回 `Deploy from a branch` → `main` / `/docs`。

## 两个 workflow 做什么

- `ci.yml`：push / PR 时跑静态门禁（词条、插件索引、三语文档、文档 HTML、版本号），
  另有一个 `continue-on-error` 的 GUI 回归任务（Windows runner）。
- `pages.yml`：push `docs/` 时用 `actions/deploy-pages` 发布静态站。
