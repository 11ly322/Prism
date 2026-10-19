# 插件 API（api = 2）

## 最小插件

~~~python
PLUGIN = {"id": "bw", "name": "黑白", "version": "2.0", "api": 2,
          "author": "Prism", "description": "转黑白"}


def run(img, **params):
    return img.convert("L").convert("RGB")
~~~

## 签名

~~~python
def run(img, **params) -> PIL.Image
~~~

- img：PIL.Image，可能是 RGB / RGBA / L。**不要原地修改它**。
- params：键为 PARAMS 的 key，值已按类型转换（slider=float、select=str、checkbox=bool），
  没传的键用 default 补齐。
- 返回值：新的 PIL.Image，尺寸与模式都可以变。
- 在主线程调用：不要 sleep、不要网络请求、不要开线程。
- 异常直接抛：loader 捕获后写日志并回退原图，主程序不崩。**不要吞异常返回 None**。

## 图像契约（重要）

| 场景 | run 拿到什么 |
| :--- | :--- |
| 首次运行插件 | **代理图**：当前图片 + 全部调整后的结果，长边不超过 2048（小图不缩）|
| 结果窗口里拖参数 | 同一张代理图，每动一次重算一次 |
| 点「保存为…」 | 按**原分辨率**把整条管线重算一遍，再用当前参数跑一次插件 |

因此：

- 预览永远是秒级的，40MP 的图也不会卡；导出结果与预览用同一套参数，
  所见即所得。
- 即便如此，插件内仍建议自己降采样：代理图上限是 2048，但一张 2048 的图
  反复逐像素处理也会拖慢滑杆。可以直接用下面的写法：
  ~~~python
  import os, sys
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  from _utils import preview_then_export

  def run(img, **params):
      def work(small):
          return small.convert("L").convert("RGB")
      return preview_then_export(work, img)
  ~~~
- preview_then_export 会自己处理降采样、放大回原尺寸、RGBA 的 alpha 贴回。
- 想手工控制时用 downscale_if_needed / upscale_back，逻辑同上。

## PARAMS 字段

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| key | 是 | 参数名，也是 run 里 kwargs 的键 |
| label | 是 | 界面标签 |
| type | 否 | slider（默认）/ select / checkbox / text |
| min / max | slider 必填 | 取值范围 |
| step | 否 | 步长，默认 1 |
| default | 是 | 默认值 |
| options | select 必填 | 选项列表（旧的 choices 也兼容）|
| default | text | 字符串，可为空字符串 |

三种控件：

~~~python
PARAMS = [
    {"key": "amount", "label": "强度", "type": "slider",
     "min": 0, "max": 100, "default": 60, "step": 5},
    {"key": "mode", "label": "风格", "type": "select",
     "options": ["原样", "偏暖", "偏冷"], "default": "偏暖"},
    {"key": "vignette", "label": "加暗角", "type": "checkbox", "default": False},
    {"key": "caption", "label": "说明文字", "type": "text", "default": ""},
]
~~~

向后兼容：省略 type 或写 range 等于 slider；type=choice + choices 等于 select；
type=bool 等于 checkbox。老插件不用改。text 是 8.3.0 新增，值为字符串。

## PLUGIN 字段

| 字段 | 必填 | 说明 |
| :--- | :--- | :--- |
| id | 是 | 唯一标识，小写字母/数字/下划线，用于日志与禁用 |
| name | 是 | 显示名 |
| version | 是 | 插件自身版本 |
| api | 是 | 接口版本，当前必须是 2 |
| author | 是 | 作者 |
| description | 建议 | 插件窗口里的一行说明 |
| network | 可选 | 能力声明：是否联网（默认 False）|
| writes_files | 可选 | 能力声明：是否写文件（默认 False）|

network / writes_files 会在插件窗口显示出来，只用于提高透明度，
**不是强制约束** —— 插件仍然以完整权限运行。

## 热重载与开发模式

- 默认开启热重载：插件目录每 1.5 秒检查一次 mtime，改动即重新加载并刷新插件窗口。
  插件窗口里也有「重载插件」按钮可手动触发。
- 启动参数 --plugin-dev：日志里记录每个插件的加载耗时与执行耗时，
  界面上提示「插件 X 执行耗时 Nms」，异常时提示插件名 + 异常类型 + 首行信息。

## 错误日志格式

统一写在 logs/plugins.log（与 Prism_settings.json 同层）：

~~~
[2026-10-18 14:02:11] plugin=skin_smooth api=2 run failed: ValueError: 参数 '强度' 超出范围 (got 120, max 100)
~~~

字段顺序：时间、插件 id、api 版本、阶段（load / run / reload）、异常类型、首行信息。
--plugin-dev 下会额外追加完整 traceback。

## 版本兼容策略

- API **只增不改**：新字段、新控件类型都可以加，已有字段语义不变。
- 破坏性变更会升**主版本**（api 3），并至少保留 api 2 一个版本周期。
- Prism 只加载 api 等于自身支持范围的插件；更高的会被跳过，并在插件窗口提示
  「插件 X 需要 API N，当前为 M」，不崩溃、不刷 traceback。

## 启用 / 禁用

把 插件.py 改名为 插件.py.disabled 即禁用，改回来即启用。插件窗口会列出已禁用项。

## 硬性约束

- 不联网：不得发起网络请求，不得上传用户图片。
- 不写原图路径之外的任何文件（日志由 Prism 自己写）。
- 不读用户未授权的目录。
- 不修改调用方传入的 img 对象。

## 自带插件

9 个插件的 id、参数与源码见 plugins/README.md；模板见 plugins/_template.py；
小工具见 plugins/_utils.py。
