[中文](README.md) · [English](README.en.md) · **日本語**

# コミュニティ / 公式プラグインディレクトリ

Prism には 12 個のプラグインが同梱されています（索引は `../README.md`）。外部プラグインの公開方法は 2 つです。

1. **公式カタログに追加** `plugins/index.json`：ユーザーは「プラグインマーケット」で一覧・ワンクリック導入・更新確認ができます。
2. **リポジトリに入れない**：`.py` の http(s) 直リンクと SHA-256 を用意し、ユーザーは「プラグイン → URL からインストール…」で導入します。

`plugins/README.md` の 2 つの表は `tools/make_plugin_index.py` が
**プラグインのソース + index.json** から生成します。表を手で編集しないでください。

## 収録基準

- ソースが読めること：バイナリ・暗号化・難読化は不可。
- ネットワークへのアップロードなし：ネットワークリクエストやユーザー画像の送信は不可。本当に必要な場合は `PLUGIN.network` で宣言すること。
- 元画像を壊さない：新しい画像を返し、ユーザーのファイルを上書きしない。ファイルを書き込む場合は `PLUGIN.writes_files` で宣言すること。
- `api` を宣言し、対応範囲（1 / 2）に収めること。
- 提出前に `.github/ISSUE_TEMPLATE/plugin-submission.yml` を記入すること。

## 公式カタログへの PR で変更するもの

1. `docs/plugins/<ファイル名>.py`：プラグインのソース（ファイル名は ASCII）。
2. `plugins/index.json`：1 項目を追加。フィールドは [plugin-api.ja.md](../../docs/plugin-api.ja.md) を参照：
   `id` / `name`（zh/en/ja）/ `version` / `api` / `author` / `description`（zh/en/ja）/
   `network` / `writes_files` / `url` / `sha256` / `source`。
3. `python tools/make_plugin_index.py --check` を実行し、合格すること（SHA-256、
   三言語、README と docs のコピーが最新かを検証します）。

アプリはカタログ内のコードを一切実行しません。インストール時も AST を解析するだけで、
SHA-256 が一致しない場合は拒否します。
