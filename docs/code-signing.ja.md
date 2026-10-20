[中文](code-signing.md) · [English](code-signing.en.md) · **日本語**

# コード署名（Windows）

**現状**：リリース版は未署名のため、Windows SmartScreen が「不明な発行元」と表示します。
これは不具合ではなく、コード署名証明書が必要です。このページでは購入するものと、
リリーススクリプトへの組み込み方法を説明します。

## なぜ必要か

- 未署名の exe をダウンロードして実行すると SmartScreen が警告し、
  「詳細情報 → 実行」を押す必要があります。
- 署名しても、その証明書に十分な評価が貯まるまでは警告が出ることがあります。
  **EV 証明書**は通常すぐに評価が付き、**OV 証明書**は時間がかかります。
- 署名が証明するのは「証明書の持ち主が配布し、署名後に改変されていない」ことだけです。
  ソフトウェアに脆弱性がないことを保証するものではありません。

## 必要なもの

1. コード署名証明書（OV または EV）。例：DigiCert、Sectigo、SSL.com。
2. 証明書は通常ハードウェアトークンまたはクラウド HSM で提供されます。
   テスト用途なら `.pfx` ファイルでも構いません。
3. Windows SDK の `signtool.exe`、または CA が提供する署名ツール。

## リリーススクリプトのフック

`make_release.ps1` は `Prism.exe` と自己解凍インストーラのビルド後に
`Sign-PrismExe` を呼びます。環境変数が無ければ何もしません：

```powershell
# 方法 1：PFX ファイル（テスト・社内用）
$env:PRISM_SIGN_CERT = "D:\keys\prism.pfx"
$env:PRISM_SIGN_PASSWORD = "証明書のパスワード"
# 方法 2：証明書の拇印（証明書ストアにインストール済みの場合）
$env:PRISM_SIGN_THUMBPRINT = "ABCDEF...".Replace(" ", "")
# signtool が PATH に無い場合
$env:PRISM_SIGNTOOL = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"

powershell -ExecutionPolicy Bypass -File .\make_release.ps1
```

タイムスタンプは DigiCert の RFC3161 サービスを使用します。署名に失敗すると
リリース処理はエラーで停止し、未署名のまま配布されることはありません。

## 確認

```powershell
Get-AuthenticodeSignature .\Prism.exe | Format-List Status,SignerCertificate
# Status が Valid であること。signtool verify /pa /all Prism.exe でも確認できます
```

## 未対応

- 証明書の購入と本人確認はアカウント所有者が行う必要があります。
- 署名対象は `Prism.exe` とインストーラのみ。macOS/Linux はソースアーカイブです。
- CI での署名には PFX/パスワードを Actions Secrets に入れ、一時ファイルへデコードする
  必要があります。`workflow` 権限が付与されたら追加できます。
