[中文](code-signing.md) · **English** · [日本語](code-signing.ja.md)

# Code signing (Windows)

**Status**: release builds are unsigned, so Windows SmartScreen shows “Unknown publisher”.
That is not a bug — it needs a code-signing certificate. This page explains what to buy and
how the release script already wires it up.

## Why

- Unsigned executables downloaded from the internet trigger SmartScreen; users must click
  “More info → Run anyway”.
- After signing, reputation still has to build up. **EV certificates** usually establish
  reputation immediately; **OV certificates** accumulate it over time.
- A signature proves the file came from the certificate holder and was not modified after
  signing. It does not prove the software is free of bugs.

## What you need

1. A code-signing certificate (OV or EV) from a CA such as DigiCert, Sectigo or SSL.com.
2. Certificates are usually delivered on a hardware token or cloud HSM; a plain `.pfx` is
   fine for internal/testing use.
3. `signtool.exe` from the Windows SDK, or the signing tool provided by the CA.

## The release script already has the hook

`make_release.ps1` calls `Sign-PrismExe` after building `Prism.exe` and the self-extracting
installer. With no environment variables set it does nothing; set them to sign:

```powershell
# Option 1: PFX file (internal/testing)
$env:PRISM_SIGN_CERT = "D:\keys\prism.pfx"
$env:PRISM_SIGN_PASSWORD = "certificate password"
# Option 2: certificate thumbprint (already installed in the certificate store)
$env:PRISM_SIGN_THUMBPRINT = "ABCDEF...".Replace(" ", "")
# Point at signtool if it is not on PATH
$env:PRISM_SIGNTOOL = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.22621.0\x64\signtool.exe"

powershell -ExecutionPolicy Bypass -File .\make_release.ps1
```

Timestamps use DigiCert's RFC3161 service. A signing failure aborts the release; it never
silently produces an unsigned package.

## Verify

```powershell
Get-AuthenticodeSignature .\Prism.exe | Format-List Status,SignerCertificate
# Status should be Valid; also run signtool verify /pa /all Prism.exe
```

## Not done yet

- Buying the certificate and completing identity verification is up to the account owner.
- Only `Prism.exe` and the installer are signed; macOS/Linux packages are source archives.
- Signing in CI requires the PFX/password in Actions Secrets, decoded to a temporary file.
  That can be added once the `workflow` permission is granted.
