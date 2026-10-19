# 自带插件

12 个插件全是 **api 2**，源码就在本目录，改完约 1.5 秒自动热重载。
想照着写：先看 _template.py，再看 黑白.py（最短）。

| id | 名称 | 参数（控件 / 默认） | 适用场景 | 源码 |
| --- | --- | --- | --- | --- |
| pixelate | 像素化 | slider 方块大小 4~160（24）· select 取样方式 · checkbox 画方块边 | 马赛克 / 像素风头像 | 像素化.py |
| sepia | 复古胶片 | slider 褐色强度（70）· slider 对比度（96）· slider 暗角（35） | 做旧照片、胶片感 | 复古胶片.py |
| avatar | 圆形头像 | slider 输出边长（512）· slider 留白比例（8）· select 背景 | 社交平台圆形头像 | 圆形头像.py |
| border | 白边框 | slider 宽度（28）· select 颜色 · checkbox 内侧细线 | 拍立得式白边 | 白边框.py |
| sharpen | 锐化 | slider 半径（1.6）· slider 强度（80）· slider 阈值（3） | 风景/人像收尾锐化 | 锐化.py |
| bw | 黑白 | slider 对比增强（20） | 最简示例，照着改最快 | 黑白.py |
| autolevel | 自动色阶 | slider 裁切比例（0.4）· slider 强度（100） | 灰蒙蒙的扫描件快修 | 自动色阶.py |
| watermark | 加文字 | select 署名 · slider 字号（3.2）· slider 边距（2.0）· checkbox 描边 | 作品右下角署名 | 加文字.py |
| crop169 | 16:9 裁剪 | select 目标比例 · select 对齐 | 视频封面、PPT 配图 | 16比9裁剪.py |

## 开发流程

1. 复制 _template.py 为 myplugin.py（不要以下划线开头）
2. 改 PLUGIN / PARAMS / run
3. 保存，Prism 约 1.5 秒自动重载（插件窗口也能点「重载插件」）
4. 临时关掉某个插件：改名成 xxx.py.disabled

## 三种控件

| type | 必填字段 | 传给 run 的类型 | 旧写法（仍兼容）|
| --- | --- | --- | --- |
| slider | min / max / default，可选 step | float | 省略 type 或写 range |
| select | options / default | str | type=choice + choices |
| checkbox | default | bool | type=bool |
| text | default（可为空串）| str | 无（8.3.0 新增）|

## 复用函数

_utils.py 提供 preview_then_export / downscale_if_needed / upscale_back / preserve_alpha /
split_alpha / to_rgb / clamp_params，不是框架，复制走也行。
preview_then_export(func, img) 最省事：降采样 → 跑 func → 放大回原尺寸 → 贴回 alpha。
导入前需要把插件目录加进 sys.path（见该文件头注释）。
