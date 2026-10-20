[中文](plugin-api.md) · **English** · [日本語](plugin-api.ja.md)

# Plugin API (api = 2)

## Minimal plugin

~~~python
PLUGIN = {"id": "bw", "name": "黑白", "version": "2.0", "api": 2,
          "author": "Prism", "description": "转黑白"}


def run(img, **params):
    return img.convert("L").convert("RGB")
~~~

## Signature

~~~python
def run(img, **params) -> PIL.Image
~~~

- img: a PIL.Image, possibly RGB / RGBA / L. **Do not modify it in place**.
- params: keys are PARAMS keys; values are already converted by type (slider=float, select=str,
  checkbox=bool), and keys that were not passed are filled in from default.
- Return value: a new PIL.Image; both size and mode may change.
- Called on the main thread: do not sleep, do not make network requests, do not start threads.
- Raise exceptions directly: the loader catches them, writes the log and falls back to the original
  image; the main program does not crash. **Do not swallow exceptions and return None**.

## Image contract (important)

| Scenario | What run receives |
| :--- | :--- |
| First run of the plugin | **Proxy image**: the current image with all adjustments applied, long edge no more than 2048 (small images are not scaled)|
| Dragging parameters in the result window | The same proxy image, recomputed on every change |
| Clicking "Save as…" | Recompute the whole pipeline at **full resolution**, then run the plugin once with the current parameters |

Therefore:

- Previews always finish in seconds, and even a 40MP image will not stutter; the exported result and
  the preview use the same set of parameters, so what you see is what you get.
- Even so, plugins are still advised to downsample themselves: the proxy image is capped at 2048, but
  processing a 2048 image pixel by pixel over and over will still slow the slider down. You can use
  the following code directly:
  ~~~python
  import os, sys
  sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
  from _utils import preview_then_export

  def run(img, **params):
      def work(small):
          return small.convert("L").convert("RGB")
      return preview_then_export(work, img)
  ~~~
- preview_then_export handles downsampling, upscaling back to the original size, and pasting the RGBA
  alpha back itself.
- To control it by hand, use downscale_if_needed / upscale_back; the logic is the same as above.

## PARAMS fields

| Field | Required | Description |
| :--- | :--- | :--- |
| key | Yes | Parameter name; also the key for kwargs in run |
| label | Yes | UI label; a string or {zh,en,ja} (9.6.0) |
| type | No | slider (default) / select / checkbox / text |
| min / max | Required for slider | Value range |
| step | No | Step size, default 1 |
| default | Yes | Default value |
| options | Required for select | Option list (the old choices is also accepted). Items may be strings or {value,label}; label may be localized |
| default | text | String, may be an empty string |

Three kinds of controls:

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

Backward compatibility: omitting type or writing range equals slider; type=choice + choices equals
select; type=bool equals checkbox. Old plugins need no changes. text is new in 8.3.0, and its value
is a string.

## PLUGIN fields

| Field | Required | Description |
| :--- | :--- | :--- |
| id | Yes | Unique identifier: lowercase letters/digits/`-`/`_`, must not start with `_` (also used as the install filename) |
| name | Yes | Display name; a string or {zh,en,ja} |
| version | Yes | The plugin's own version |
| api | Yes | Interface version; must currently be 2 |
| author | Yes | Author |
| description | Recommended | One-line description shown in the plugin window; a string or {zh,en,ja} |
| network | Optional | Capability declaration: whether it accesses the network (default False)|
| writes_files | Optional | Capability declaration: whether it writes files (default False)|

### Localized text (9.6.0)

`name`, `description` and `PARAMS.label` may be plain strings, or objects like
`{"zh": "...", "en": "...", "ja": "..."}`. A missing language falls back to Chinese.
Third-party plugins that only provide a string keep showing it as-is. With
`options` written as `{value, label}`, the UI shows the label while `run()` still
receives the value; plain strings display the value itself.


network / writes_files are shown in the plugin window purely to improve transparency;
**they are not enforced constraints** — plugins still run with full permissions.

## Parameter memory (9.4.0)

Prism remembers the parameters each plugin used last time, by PLUGIN.id, in `plugin_params` inside
`Prism_settings.json`; they survive a restart. The next run of the same plugin restores them
automatically.

- Old values outside the range are clamped to the new min/max.
- Removed options fall back to the new default.
- A changed id means a different plugin; the old parameters are not applied.
- "Restore defaults" in the result window clears this plugin's memory.

Plugins need to write no code for this; the defaults declared in PARAMS are still the values used on
the first run.

## Installation and distribution

### Plugin marketplace (9.5.0)

Plugin window → "Plugin marketplace": the list comes from the official catalog `plugins/index.json`,
which shows "Installed / Update available / Not installed"; clicking the button installs or updates
directly.

- The catalog URL defaults to `https://11ly322.github.io/Prism/plugins/index.json`; the environment
  variable `PRISM_PLUGIN_CATALOG` can point to your own catalog (self-hosted marketplace / intranet
  mirror / testing).
- If fetching the catalog fails, the cache from the last successful fetch is used automatically
  (`plugin_catalog.json`, in the same directory as the settings file), and the window labels it
  "offline cache".
- The install/update flow is exactly the same as "Install from URL…": download → parse the AST only →
  verify SHA-256 → confirm → write to disk. Updates are written back to the original filename, so the
  same id never appears twice.
- The `version` in the catalog is used to decide "update available": numeric segments are compared
  (`1.10 > 1.9`).

Catalog format (schema 1):

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

- `name` / `description` must include at least zh among the three languages; when the current
  language is missing, they fall back to Chinese.
- `url` must be http(s), and the filename must match `source`; `sha256` must match the source byte for
  byte.
- `source` is used only for in-repo validation and README generation; the app does not read it.
- In the repository, `plugins/index.json` is the single source of truth;
  `tools/make_plugin_index.py` validates it, generates the two tables in `plugins/README.en.md`, and
  copies it to `docs/plugins/index.json`. The release gate runs `make_plugin_index.py --check`.

### Install from URL (9.4.0)

Plugin window → "Install from URL…": enter a direct http(s) link to a `.py` file, and optionally a
SHA-256.

1. Downloaded on a background thread; single-file limit 2 MB, 15-second timeout.
2. **Only the AST is parsed; no code is executed**: there must be a `PLUGIN` literal dict and a
   `run()`, and `api` must be within the supported range.
3. If a SHA-256 was entered, it is compared strictly; a mismatch is rejected outright.
4. A confirmation dialog appears (name / version / author / network / file writes); only after you
   confirm is the plugin written to the plugin directory.
5. The filename is the sanitized `PLUGIN.id` (only ASCII letters, digits and `-` `_` are kept); if a
   file with the same name already exists, you are asked once more whether to overwrite it.

Therefore `id` should use only lowercase letters, digits, `-` and `_`: it is both the identifier in
logs and the installed filename.
SHA-256 only proves the file has not been modified; it cannot prove the author is trustworthy. You
still have to judge for yourself before installing.

## Hot reload and dev mode

- Hot reload is on by default: the plugin directory's mtime is checked every 1.5 seconds, and any
  change reloads the plugins and refreshes the plugin window. The plugin window also has a
  "Reload plugins" button to trigger it manually.
- Startup flag --plugin-dev: the log records each plugin's load time and execution time, the UI shows
  "plugin X took Nms", and on error it shows the plugin name + exception type + first line of the
  message.

## Error log format

Written uniformly to logs/plugins.log (in the same directory as Prism_settings.json):

~~~
[2026-10-18 14:02:11] plugin=skin_smooth api=2 run failed: ValueError: 参数 '强度' 超出范围 (got 120, max 100)
~~~

Field order: time, plugin id, api version, stage (load / run / reload), exception type, first line of
the message. Under --plugin-dev, the full traceback is appended as well.

## Version compatibility policy

- The API **only grows, and is never changed**: new fields and new control types can be added, and
  the semantics of existing fields stay the same.
- Breaking changes bump the **major version** (api 3), and api 2 is kept for at least one release
  cycle.
- Prism loads only plugins whose api equals the range it supports; higher ones are skipped, and the
  plugin window shows "plugin X requires API N, current is M", with no crash and no traceback spam.

## Enabling / disabling

Rename plugin.py to plugin.py.disabled to disable it, and rename it back to enable it. The plugin
window lists disabled items.

## Hard constraints

- No network: by default a plugin must not make network requests or upload user images. A plugin that
  genuinely needs the network must declare so truthfully in PLUGIN.network, and the install
  confirmation dialog shows this declaration to the user.
- Do not write any files outside the original image's path (logs are written by Prism itself). A
  plugin that needs to write files must declare so truthfully in PLUGIN.writes_files.
- Do not read directories the user has not authorized.
- Do not modify the img object passed in by the caller.

## Bundled plugins

The ids, parameters and source of the 12 plugins are in plugins/README.en.md; the template is
plugins/_template.py; the helper utilities are plugins/_utils.py. The source of the example
installable plugin grad-nd is in docs/plugins/demo-grad-nd.py.
