**中文** · [English](plugin-api.en.md) · [日本語](plugin-api.ja.md)

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

## 参数记忆（9.4.0）

Prism 按 PLUGIN.id 记住每个插件上次用的参数，存在 `Prism_settings.json` 的
`plugin_params` 里，重启后仍在。下次运行同一个插件时自动恢复。

- 范围外的旧值会被夹到新的 min/max。
- 已删除的选项回落到新的 default。
- 换了 id 等于换了一个插件，旧参数不会套上去。
- 结果窗口的「恢复默认」会清空这个插件的记忆。

插件不需要为此写任何代码；PARAMS 里声明的默认值仍然是首次运行时的值。

## 安装与分发

### 插件市场（9.5.0）

插件窗口 →「插件市场」：列表来自官方清单 `plugins/index.json`，可看
「已安装 / 可更新 / 未安装」，点按钮直接安装或更新。

- 清单地址默认 `https://11ly322.github.io/Prism/plugins/index.json`；
  环境变量 `PRISM_PLUGIN_CATALOG` 可以指向自己的清单（自建市场 / 内网镜像 / 测试）。
- 拉清单失败时自动用上次成功拉取的缓存（`plugin_catalog.json`，与设置文件同目录），
  窗口里会标明「离线缓存」。
- 安装/更新流程与「从网址安装」完全一致：下载 → 只解析 AST → 校验 SHA-256 → 确认 → 写盘。
  更新会写回原来的文件名，避免同一个 id 出现两份。
- 清单里的 `version` 用来判断「可更新」：按数字段比较（`1.10 > 1.9`）。

清单格式（schema 1）：

~~~json
{
  "schema": 1,
  "updated": "2026-10-19",
  "homepage": "https://11ly322.github.io/Prism/",
  "plugins": [
    {
      "id": "grad-nd",
      "name": {"zh": "渐变减光", "en": "Grad ND", "ja": "グラデ ND"},
      "version": "1.0",
      "api": 2,
      "author": "Prism",
      "description": {"zh": "…", "en": "…", "ja": "…"},
      "network": false,
      "writes_files": false,
      "url": "https://11ly322.github.io/Prism/plugins/demo-grad-nd.py",
      "sha256": "cf8552bd0a4393e5a798582c00970b2981d6a7f8e14182c682c2eabe666e54ee",
      "source": "docs/plugins/demo-grad-nd.py"
    }
  ]
}
~~~

- `name` / `description` 三语至少要 zh；缺当前语言时回落中文。
- `url` 必须是 http(s)，文件名要和 `source` 一致；`sha256` 必须与源码逐字节一致。
- `source` 只用于仓库内校验与生成 README，应用不读它。
- 仓库里 `plugins/index.json` 是唯一数据源；`tools/make_plugin_index.py`
  会校验它、生成 `plugins/README.md` 的两块表格，并复制到 `docs/plugins/index.json`。
  发布门禁会跑 `make_plugin_index.py --check`。

### 从网址安装（9.4.0）

插件窗口 →「从网址安装…」：填一个 `.py` 的 http(s) 直链，可选再填 SHA-256。

1. 后台线程下载，单文件上限 2 MB，15 秒超时。
2. **只解析 AST，不执行代码**：必须有 `PLUGIN` 字面量字典与 `run()`，
   `api` 必须在支持范围内。
3. 填了 SHA-256 就强制比对；不符直接拒绝。
4. 弹确认框（名字 / 版本 / 作者 / 联网 / 写文件），确认后才写入插件目录。
5. 文件名取 `PLUGIN.id` 清洗后的结果（只留 ASCII 字母数字与 `-` `_`），
   已存在同名文件会再问一次是否覆盖。

因此 `id` 建议只用小写字母、数字、`-`、`_`：它同时是日志里的标识和安装后的文件名。
SHA-256 只能证明文件没被改过，不能证明作者可信；装之前仍然要自己判断。

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

- 不联网：默认不得发起网络请求、不得上传用户图片。确实需要联网的插件必须在
  PLUGIN.network 里如实声明，安装确认框会把这条声明显示给用户。
- 不写原图路径之外的任何文件（日志由 Prism 自己写）。需要写文件的插件必须在
  PLUGIN.writes_files 里如实声明。
- 不读用户未授权的目录。
- 不修改调用方传入的 img 对象。

## 自带插件

12 个插件的 id、参数与源码见 plugins/README.md；模板见 plugins/_template.py；
小工具见 plugins/_utils.py。示例安装插件 grad-nd 的源码在 docs/plugins/demo-grad-nd.py。
