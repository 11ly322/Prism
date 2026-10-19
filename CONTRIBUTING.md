# 贡献指南

Prism 用 MIT 协议开源（见 LICENSE）。欢迎提 issue、提 PR、写插件。

## 提交插件

1. 复制 plugins/_template.py，按注释填好 PLUGIN 与 PARAMS。
2. 在本机用 Prism 实际跑一遍，确认不报错、效果符合预期。
3. 提 PR 时把一个 .py 文件放进 plugins/，并同步更新 plugins/README.md 的表格。
4. PR 描述里写清楚：插件做什么、有哪些参数、在什么图上测试过。

## API 兼容版本

插件头部必须声明它按哪一版接口写的：

~~~
PLUGIN = {"id": "sepia", "name": "复古胶片", "version": "3.0",
          "api": 2, "author": "你的名字"}
~~~

- api 2 是当前版本，run 签名为 run(img, **params)。
- api 1 是旧版本（run(img, path=None, params=None)），仍可加载但不再推荐。
- Prism 只加载 api 等于自身支持的插件；版本更高会被跳过并在插件窗口提示，
  不会崩溃，也不会静默忽略。
- 改动接口时，README、plugins/_template.py、自带插件必须同时更新。

## 能力声明与收录

插件建议在 PLUGIN 里如实声明两个字段：

~~~python
PLUGIN = {"id": "x", "name": "X", "version": "1.0", "api": 2,
          "author": "你", "network": False, "writes_files": False}
~~~

它们会显示在插件窗口里，只是透明度，不是沙箱。
收录社区插件请用 .github/ISSUE_TEMPLATE/plugin-submission.yml 填表，索引放在 plugins/community/README.md。

## 版本兼容

API 只增不改；破坏性变更升主版本（api 3），并至少保留旧版一个版本周期。Prism 只加载可支持的 api，更高的会被跳过并提示，不崩溃。

## 收录标准

会被拒绝的插件：

- **恶意代码**：读写无关目录、改注册表、弹窗骚扰、伪装成别的插件。
- **联网上传**：任何形式的网络请求、把用户图片外传。Prism 的原则是不联网。
- **破坏原图**：直接覆盖用户的原文件，而不是返回新图。
- **打包二进制**：附带 exe/dll 或以加密方式隐藏逻辑，无法审阅。

会被建议修改的插件：

- 一次运行超过 200ms（大图请先降采样，见 docs/plugin-api.md）。
- 参数超过 6 个，或默认值会让图像明显失真。
- 依赖 Pillow 之外的第三方库（会增大安装包体积）。

## 代码风格

- 单文件、单入口 run(img, **params)，不要有 import 期的副作用。
- 顶部写 PLUGIN 与 PARAMS；不要修改全局状态。
- 中文注释即可，和现有插件保持一致。

## 安全声明

插件以 **完整权限** 运行，没有沙箱。这是为了让插件能做任何 Pillow 能做的事，
代价是必须只安装你信任的插件。这条声明在任何情况下都不会弱化。

## 发版检查清单

1. 改 APP_VERSION（唯一来源：src/Prism.pyw），跑 python check_versions.py 确认没有旧版本号残留。
2. 跑三套测试：tools/selfcheck.py、tools/newcheck.py、tools/beautycheck.py。
3. 执行 make_release.ps1 —— 会自动调用 make_platforms.py 生成四平台包 + 便携版，
   并清理 docs/ 里的旧版本包。
4. 更新 docs/index.html 的 SHA-256、安装包大小与下载链接版本号。
5. git add -A && git commit && git push。
6. 线上核验要重试：GitHub Pages 对新推的大文件有 CDN 延迟，实测前两次 HEAD 可能 404，
   约 40 秒后变 200。脚本里请循环重试 3~6 次，别看到一次 404 就判定失败。

## 性能改动约定

- 只改最后一位版本号（如 8.3.2 -> 8.3.3）。
- 每项优化必须用 python tools/bench.py --repeat 3 做前后对照，把数字写进 CHANGELOG。
- bench 的 --repeat 每轮都在独立子进程里跑，内存峰值才可信；
  同一进程连跑会让 Tk 资源累积，内存虚高 60% 以上（曾经踩过）。
