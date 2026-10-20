**中文** · [English](code-signing.en.md) · [日本語](code-signing.ja.md)

# 代码签名（Windows）

**现状**：安装包没有代码签名，所以 Windows SmartScreen 会提示「未知发布者」。
这不是 bug，需要一张代码签名证书；本文说明买什么、怎么接到发布脚本里。

## 为什么需要

- 未签名 exe 首次下载运行时，SmartScreen 会拦截，需要点「更多信息 → 仍要运行」。
- 签名后仍可能提示，直到该证书积累足够下载信誉；**EV 证书**通常能立即建立信誉，
  **OV 证书**需要时间累积。
- 签名只能证明「这个文件来自证书持有者、且发布后没被改过」，不能证明软件没有漏洞。

## 需要什么

1. 代码签名证书（OV 或 EV），常见颁发机构：DigiCert、Sectigo、SSL.com。
2. 证书通常以硬件令牌 / 云 HSM 形式交付；纯 `.pfx` 文件只适合测试或托管签名服务。
3. Windows SDK 里的 `signtool.exe`（或云签名服务提供的签名工具）。

## 发布脚本已留好钩子

`make_release.ps1` 在构建完 `Prism.exe` 与自解压安装包后，会调用 `Sign-PrismExe`。
不设环境变量时它什么也不做；设置了才会签名：

```powershell
# 方式一：PFX 文件（测试/内部）
$env:PRISM_SIGN_CERT = "D:\keys\prism.pfx"
$env:PRISM_SIGN_PASSWORD = "证书密码"
# 方式二：证书指纹（证书已装进当前用户/机器证书库）
$env:PRISM_SIGN_THUMBPRINT = "ABCDEF...".Replace(" ", "")
# signtool 不在 PATH 时指定完整路径
$env:PRISM_SIGNTOOL = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"

powershell -ExecutionPolicy Bypass -File .\make_release.ps1
```

时间戳用 DigiCert 的 RFC3161 服务；签名失败会直接让发布流程报错，不会悄悄产出未签名包。

## 验证

```powershell
Get-AuthenticodeSignature .\Prism.exe | Format-List Status,SignerCertificate
# Status 应为 Valid；再用 signtool verify /pa /all Prism.exe 复核
```

## 还没做的部分

- 证书采购与身份验证需要账号持有人完成，代码侧无法代劳。
- 目前只签 `Prism.exe` 与自解压安装包；其它平台包（macOS/Linux）是源码压缩包，不需要 Windows 签名。
- CI 里签名需要把 PFX/密码放进 Actions Secrets，并用 base64 解码到临时文件；
  等 `workflow` 权限开通后可以补进 `pages.yml` 之外的发布 workflow。
