# Prism 插件索引

12 个自带插件 + 一份官方可安装清单。清单 `index.json` 同时是应用内「插件市场」的数据源；
下面的两块表格由 `tools/make_plugin_index.py` 从**插件源码 + index.json**生成，不要手改表格内容
（改完跑一次脚本，或用 `--check` 看是否最新）。

## 自带插件（随程序提供）

<!-- BEGIN GENERATED builtin -->
| id | 名称 / 版本 | 参数（控件 · 范围 · 默认） | 说明 | 联网 | 写文件 | 源码 |
| --- | --- | --- | --- | --- | --- | --- |
| crop169 | 16比9裁剪 2.0 | select 目标比例（16:9 / 9:16 / 4:3 / 1:1） · select 对齐（居中 / 偏上 / 偏下） | 按目标比例居中裁剪，做视频封面和 PPT 配图 | 否 | 否 | `16比9裁剪.py` |
| god_rays | 丁达尔光 1.0 | slider 取光门槛 50–98（86） · slider 光束长度 20–220（110） · slider 角度 -60–60（14） · slider 强度 10–100（55） | 把高光沿一个方向拖成光束，模拟逆光丁达尔效应 | 否 | 否 | `丁达尔光.py` |
| pixelate | 像素化 2.0 | slider 方块大小 4–160（24） · select 取样方式（平均 / 放大镜） · checkbox 画方块边 | 马赛克。可调方块大小、取样方式与描边 | 否 | 否 | `像素化.py` |
| watermark | 加文字 2.1 | text 署名文字 · slider 字号占比 1–8（3.2） · slider 边距占比 0–8（2） · checkbox 描边 | 右下角加一行署名，文字内容可自定义 | 否 | 否 | `加文字.py` |
| avatar | 圆形头像 2.0 | slider 输出边长 128–1024（512） · slider 留白比例 0–30（0） · select 背景（透明 / 白色 / 黑色） | 圆形蒙版头像。可调留白、背景色与输出尺寸 | 否 | 否 | `圆形头像.py` |
| sepia | 复古胶片 2.0 | slider 褐色强度 0–100（70） · slider 对比度 50–150（96） · slider 暗角 0–100（35） | 暖褐色调。可调强度、对比与暗角 | 否 | 否 | `复古胶片.py` |
| glitch | 故障艺术 1.0 | slider 通道错位 0–30（8） · slider 切片数量 0–40（12） · slider 随机种子 0–99（7） · checkbox 扫描线 | RGB 通道错位与横向切片位移，做数字故障效果 | 否 | 否 | `故障艺术.py` |
| border | 白边框 2.0 | slider 边框宽度 1–20（4） · select 颜色（白色 / 黑色 / 米白） · checkbox 内侧细线 | 四周加边框。可调宽度、颜色与内侧细线 | 否 | 否 | `白边框.py` |
| tilt_shift | 移轴微缩 1.0 | slider 清晰带 4–80（26） · slider 虚化强度 1–30（12） · slider 饱和提升 0–100（45） · select 清晰带位置（居中 / 偏上 / 偏下） | 横向清晰带 + 上下渐进虚化，做微缩模型效果 | 否 | 否 | `移轴微缩.py` |
| autolevel | 自动色阶 2.0 | slider 裁切比例 0–5（0.4） · slider 强度 0–100（100） | 把直方图拉满，去掉灰蒙蒙的感觉 | 否 | 否 | `自动色阶.py` |
| sharpen | 锐化 2.0 | slider 半径 0.5–5（1.4） · slider 强度 % 10–300（90） · slider 阈值 0–20（3） | USM 锐化。可调半径、强度与阈值 | 否 | 否 | `锐化.py` |
| bw | 黑白 2.0 | slider 对比增强 0–100（20） | 最简示例：一个插件最小可以多短。可调对比增强 | 否 | 否 | `黑白.py` |
<!-- END GENERATED builtin -->

参数默认值以源码 `PARAMS` 为准。改完保存，Prism 约 1.5 秒自动热重载。

## 官方清单（插件市场可一键安装）

<!-- BEGIN GENERATED catalog -->
| id | 名称 / 版本 | 参数摘要 | 说明 | SHA-256（前 12 位） | 安装文件 |
| --- | --- | --- | --- | --- | --- |
| grad-nd | 渐变减光 1.0 | slider 减光强度 0–100（45） · select 压暗一侧（顶部 / 底部） · slider 过渡宽度 5–100（45） | 从画面一侧平滑压暗，模拟中灰渐变镜；常用来压天空 | `cf8552bd0a43…` | `demo-grad-nd.py` |
| soft-glow | 柔光 1.0 | slider 强度 0–100（45） · slider 半径 1–40（18） · slider 高光门槛 0–100（55） | 高光溢出 + 轻微模糊叠加，人像与逆光更柔和 | `a6935f32b593…` | `soft-glow.py` |
| duotone | 双色调 1.0 | select 暗部颜色（深蓝 / 暗红 / 墨绿 / 紫夜 / 黑） · select 亮部颜色（米白 / 浅橙 / 天蓝 / 薄荷 / 白） · slider 强度 0–100（100） | 明度映射到暗部/亮部两种颜色，做海报与封面配色 | `d05950554b55…` | `duotone.py` |
<!-- END GENERATED catalog -->

- 应用内入口：插件窗口 →「插件市场」。可浏览、看「已安装 / 可更新 / 未安装」状态，一键安装或更新。
- 清单地址：`https://11ly322.github.io/Prism/plugins/index.json`（仓库内源码 `plugins/index.json`，
  发布时复制到 `docs/plugins/index.json`）。
- 每个条目都带 SHA-256。下载后**只解析 AST、不执行代码**，确认框里显示作者与能力声明，确认后才写盘。
- 想用自己的清单：设环境变量 `PRISM_PLUGIN_CATALOG` 指向你的 `index.json`。
  schema 见 [docs/plugin-api.md](../docs/plugin-api.md)。
- 在线清单拉不到时，应用会用上次成功拉取的缓存（`plugin_catalog.json`，与设置文件同目录），
  并在窗口里标明「离线缓存」。

## 安装插件

三种方式，效果一样：

1. **插件市场**（9.5.0）：插件窗口 →「插件市场」→ 选一个 →「安装」/「更新」。
2. **从网址安装**：插件窗口 →「从网址安装…」→ 填 `.py` 的 http(s) 直链，可再填 SHA-256。
3. **放进目录**：把 `.py` 丢进插件目录（插件窗口顶部显示完整路径），点「重新扫描」或等 1.5 秒热重载。

临时停用：把 `xxx.py` 改名成 `xxx.py.disabled`，插件窗口会显示成「启用 xxx」按钮。

安装只解决「下载到的东西没被改过」（SHA-256），**不解决作者可信不可信**。
插件声明的 `network` / `writes_files` 会在确认框里显示，但那只是作者自己填的声明。

## 参数会被记住（9.4.0）

每个插件的参数按 `id` 存在设置文件里（`plugin_params`）。下次运行同一个插件时自动恢复上次的值，
包括重启 Prism 之后。点结果窗口的「恢复默认」会清掉这份记忆。

- 插件改了参数范围：超范围的值会被夹到新范围内。
- 插件删了某个选项：失效的选项回落到新的默认值。
- 插件换了 `id`：等于一个新插件，旧记忆不会套上去。

## 开发流程

1. 复制 `_template.py` 为 `myplugin.py`（文件名不要以下划线开头，那是给框架文件留的）
2. 改 `PLUGIN` / `PARAMS` / `run`
3. 保存，Prism 约 1.5 秒自动重载（插件窗口也能点「重载插件」）
4. 出错不会崩主程序：写 `logs/plugins.log`，原图回退

## 三种控件

| type | 必填字段 | 传给 run 的类型 | 旧写法（仍兼容） |
| --- | --- | --- | --- |
| slider | min / max / default，可选 step | float | 省略 type 或写 range |
| select | options / default | str | type=choice + choices |
| checkbox | default | bool | type=bool |
| text | default（可为空串） | str | 无（8.3.0 新增） |

## PLUGIN 字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| id | 是 | 唯一标识；参数记忆、安装文件名、市场清单都用它。建议 ASCII 字母数字与 `-` `_` |
| name | 是 | 列表里显示的名字 |
| version | 建议 | 显示在名字后面；市场用它判断是否可更新 |
| api | 建议 | 当前支持 1、2；`2` 是 `run(img, **params)` 写法 |
| author | 建议 | hover 提示里显示 |
| description | 建议 | hover 提示里显示 |
| network | 建议 | 是否联网，如实填写 |
| writes_files | 建议 | 是否写文件，如实填写 |

## 第三方插件怎么放进来

- 单文件、只依赖 Pillow 与 numpy（Prism 已带），不要起线程、不要改 Prism 的内部状态。
- 文件名用 ASCII，`id` 唯一；不要以 `_` 开头。
- 自己的插件请放用户插件目录（插件窗口顶部有完整路径），不要改安装目录里的自带插件。
- 想收进官方清单：提 PR 在 `plugins/index.json` 加一项，并把源码放到 `docs/plugins/`，
  补上 `source`、`url`、`sha256` 与 zh/en/ja 三语名与说明；`make_plugin_index.py --check` 必须通过。
- 带联网 / 写文件副作用的插件必须在 `PLUGIN` 里如实声明。

## 复用函数

`_utils.py` 提供 `preview_then_export` / `downscale_if_needed` / `upscale_back` / `preserve_alpha` /
`split_alpha` / `to_rgb` / `clamp_params`，不是框架，复制走也行。
`preview_then_export(func, img)` 最省事：降采样 → 跑 func → 放大回原尺寸 → 贴回 alpha。
导入前需要把插件目录加进 `sys.path`（见该文件头注释）。
