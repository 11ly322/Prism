# Prism 发布脚本：打包主程序 -> 生成自解压安装包 -> 删除旧版本发布物
# 用法：powershell -ExecutionPolicy Bypass -File make_release.ps1
param([switch]$SkipApp, [switch]$CheckOnly, [switch]$VerifySite)

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
$py = 'C:\Users\75643\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe'
$env:PYTHONIOENCODING = 'utf-8'

$ver = (Select-String -Path (Join-Path $root 'src\Prism.pyw') -Pattern 'APP_VERSION = "(.*)"').Matches[0].Groups[1].Value

# ---- 可选代码签名：设置 PRISM_SIGN_CERT(.pfx) 或 PRISM_SIGN_THUMBPRINT 才生效 ----
function Sign-PrismExe {
    param([string]$Path)
    if (-not $env:PRISM_SIGN_CERT -and -not $env:PRISM_SIGN_THUMBPRINT) { return }
    $signtool = $env:PRISM_SIGNTOOL
    if (-not $signtool) {
        $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
        if ($cmd) { $signtool = $cmd.Source }
    }
    if (-not $signtool) {
        throw '找不到 signtool.exe：安装 Windows SDK 或设置 PRISM_SIGNTOOL'
    }
    $a = @('sign', '/fd', 'SHA256', '/tr', 'http://timestamp.digicert.com', '/td', 'SHA256')
    if ($env:PRISM_SIGN_THUMBPRINT) {
        $a += @('/sha1', $env:PRISM_SIGN_THUMBPRINT)
    } else {
        $a += @('/f', $env:PRISM_SIGN_CERT)
        if ($env:PRISM_SIGN_PASSWORD) { $a += @('/p', $env:PRISM_SIGN_PASSWORD) }
    }
    & $signtool @a $Path
    if ($LASTEXITCODE -ne 0) { throw ('代码签名失败：' + $Path) }
    Write-Host ('   已签名 ' + (Split-Path $Path -Leaf))
}

# ---- 发布后线上验收：push 之后跑这个，不打包 ----
if ($VerifySite) {
    & $py (Join-Path $root 'tools\verifysite.py') --ver $ver
    exit $LASTEXITCODE
}

# ---- 打包环境预检：缺 PyInstaller 直接给安装命令，别打包到一半才失败 ----
if (-not $CheckOnly) {
    Write-Host '-- 0/4 打包环境检查'
    & $py (Join-Path $root 'tools\buildenvcheck.py')
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# ---- 词条门禁：新增界面文案必须三语，缺一条就不许发 ----
Write-Host '-- 0/4 词条自检（新增文案必须三语）'
& $py (Join-Path $root 'tools\i18ncheck_app.py') --strict
if ($LASTEXITCODE -ne 0) {
    Write-Host '词条自检失败：先跑 tools\i18ncheck_app.py --list 400 看缺什么' -ForegroundColor Red
    exit 1
}

# ---- 插件索引门禁：README 表格 / docs 清单必须与源码 + index.json 一致 ----
Write-Host '-- 0/4 插件索引自检'
& $py (Join-Path $root 'tools\make_plugin_index.py') --check
if ($LASTEXITCODE -ne 0) {
    Write-Host '插件索引不是最新：先跑 python tools\make_plugin_index.py' -ForegroundColor Red
    exit 1
}

# ---- 三语文档门禁：语言切换链接、相对链接、代码块、生成标记 ----
Write-Host '-- 0/4 三语文档自检'
& $py (Join-Path $root 'tools\docscheck.py')
if ($LASTEXITCODE -ne 0) {
    Write-Host '三语文档自检失败：看上面哪份文档的链接/标记不对' -ForegroundColor Red
    exit 1
}

# ---- 回归总表（快跑）：词条 / 索引 / 文档 / 插件 / 市场 / 三语界面 ----
Write-Host '-- 0/4 回归总表（快跑）'
& $py (Join-Path $root 'tools\runall.py') --fast
if ($LASTEXITCODE -ne 0) {
    Write-Host '回归失败：先修上面 FAIL 的套件，再发版' -ForegroundColor Red
    exit 1
}

# ---- 只做链接自检，不打包：提交前先跑这个 ----
if ($CheckOnly) {
    $pg = Join-Path $root 'docs\index.html'
    if (-not (Test-Path $pg)) { Write-Host '找不到 docs/index.html'; exit 1 }
    # 页面图片存在性自检：语言页引用本地化截图时，文件必须真的生成过（曾经的 404）
    $badImgs = @()
    $imgCount = 0
    foreach ($rel in @('docs\index.html', 'docs\en\index.html', 'docs\ja\index.html')) {
        $p = Join-Path $root $rel
        if (-not (Test-Path $p)) { continue }
        $h = Get-Content $p -Raw -Encoding UTF8
        foreach ($m in [regex]::Matches($h, '<img[^>]+src="([^"]+)"')) {
            $src = $m.Groups[1].Value
            if ($src -match '^(https?:|//|data:)') { continue }
            $imgCount++
            $full = [System.IO.Path]::GetFullPath((Join-Path (Split-Path $p) $src))
            if (-not (Test-Path -LiteralPath $full)) { $badImgs += ($rel + ' -> ' + $src) }
        }
    }
    if ($badImgs.Count -gt 0) {
        Write-Host ('页面缺图 ' + $badImgs.Count + ' 张：') -ForegroundColor Red
        $badImgs | ForEach-Object { Write-Host ('   ' + $_) }
        exit 1
    }
    Write-Host ('页面图片自检通过：三份页面共 ' + $imgCount + ' 张，引用全部存在')
    $html = Get-Content $pg -Raw -Encoding UTF8
    $hrefs = [regex]::Matches($html, 'href="(https://github\.com/11ly322/Prism/releases/download/[^"]+)"') |
             ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    if ($hrefs.Count -eq 0) { Write-Host '页面里没有任何 release 下载链接'; exit 1 }
    $bad = @()
    foreach ($u in $hrefs) {
        $code = 0
        foreach ($attempt in 1..5) {
            try {
                $r = Invoke-WebRequest -Uri $u -Method Head -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 25
                $code = [int]$r.StatusCode
            } catch { try { $code = [int]$_.Exception.Response.StatusCode.value__ } catch { $code = 0 } }
            if ($code -eq 200) { break }
            Start-Sleep -Seconds 6
        }
        $name = ($u -replace '.*/download/', '')
        Write-Host ("   {0}  {1}" -f $name.PadRight(34), $code)
        if ($code -ne 200) { $bad += $name }
    }
    if ($bad.Count -gt 0) {
        Write-Host ("链接自检失败：{0} 条不可用" -f $bad.Count) -ForegroundColor Red
        exit 1
    }
    Write-Host ("链接自检通过：{0} 条全部 200（页面版本 {1}）" -f $hrefs.Count, $ver)
    exit 0
}
Write-Host "== 打包 Prism $ver =="

Get-Process -Name Prism -ErrorAction SilentlyContinue | ForEach-Object { $_.Kill() }
Start-Sleep -Milliseconds 600

$build = Join-Path $root '_build'
if (Test-Path -LiteralPath $build) { Remove-Item -LiteralPath $build -Recurse -Force }
New-Item -ItemType Directory -Path $build -Force | Out-Null

if (-not $SkipApp) {
    Write-Host '-- 1/4 主程序（onedir）'
    $a = @('-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed','--name','Prism',
           '--icon',"$root\src\Prism.ico",'--add-data',"$root\src\Prism.ico;.",
           '--add-data',"$root\src\Prism.png;.",'--hidden-import','lang_data',
           '--distpath',"$build\dist",
           '--workpath',"$build\work",'--specpath',$build,"$root\src\Prism.pyw")
    & $py @a *> $null
    if (-not (Test-Path -LiteralPath "$build\dist\Prism\Prism.exe")) { throw '主程序构建失败' }
    Sign-PrismExe "$build\dist\Prism\Prism.exe"
    Remove-Item -LiteralPath (Join-Path $root 'Prism.exe') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $root '_internal') -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item -Path "$build\dist\Prism\*" -Destination $root -Recurse -Force
    Write-Host '   完成：Prism.exe + _internal'
} else {
    Write-Host '-- 1/4 主程序：跳过（沿用现有）'
}

Write-Host '-- 2/4 打 payload'
$payload = Join-Path $build 'payload.zip'
$stage = Join-Path $build 'stage'
New-Item -ItemType Directory -Path $stage -Force | Out-Null
foreach ($n in @('Prism.exe','_internal','README.md','CHANGELOG.md','使用说明.txt','plugins')) {
    $p = Join-Path $root $n
    if (Test-Path -LiteralPath $p) { Copy-Item -LiteralPath $p -Destination $stage -Recurse -Force }
}
Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $payload -CompressionLevel Optimal
Write-Host ('   payload.zip ' + [math]::Round((Get-Item $payload).Length/1MB,1) + ' MB')

Write-Host '-- 3/4 自解压安装包'
$inst = Join-Path $root 'src\installer.pyw'
$txt = Get-Content -LiteralPath $inst -Raw -Encoding UTF8
$txt = [regex]::Replace($txt, 'VER = "[\d.]+"', ('VER = "' + $ver + '"'))
Set-Content -LiteralPath $inst -Value $txt -Encoding UTF8 -NoNewline
$b = @('-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed','--name',"Prism $ver 自解压安装",
       '--icon',"$root\src\Prism.ico",'--add-data',"$payload;.",'--add-data',"$root\src\Prism.ico;.",
       '--distpath',"$build\distinst",'--workpath',"$build\workinst",'--specpath',$build,$inst)
& $py @b *> $null
$newInst = Join-Path $build "distinst\Prism $ver 自解压安装.exe"
if (-not (Test-Path -LiteralPath $newInst)) { throw '安装包构建失败' }
Sign-PrismExe $newInst

Write-Host '-- 4/4 清理旧版本'
Get-ChildItem -LiteralPath $root -Filter 'Prism * 自解压安装.exe' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host ('   删除旧安装包 ' + $_.Name) }
Get-ChildItem -LiteralPath $root -Filter 'Prism * win64.zip' -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host ('   删除旧便携包 ' + $_.Name) }
Copy-Item -LiteralPath $newInst -Destination (Join-Path $root "Prism $ver 自解压安装.exe") -Force
Remove-Item -LiteralPath $build -Recurse -Force

Write-Host ''
Write-Host '== 结果 =='
$instName = "Prism $ver 自解压安装.exe"
foreach ($f in @('Prism.exe', $instName, 'README.md', 'CHANGELOG.md')) {
    $p = Join-Path $root $f
    if (Test-Path -LiteralPath $p) { Write-Host ('   ' + $f.PadRight(28) + [math]::Round((Get-Item $p).Length/1MB,1) + ' MB') }
    else { Write-Host ('   ' + $f + '  缺失!') }
}

# 同步其余平台包（看图版 / macOS / Linux），并删除旧版本
Write-Host '== 打包其余平台 =='
& $py (Join-Path $root 'make_platforms.py')

# 把安装包同步进 docs（网站下载目录），并删掉旧版本的安装包
$ver = (Select-String -Path "$root\src\Prism.pyw" -Pattern 'APP_VERSION = "(.*?)"').Matches[0].Groups[1].Value
$instSrc = Join-Path $root ("Prism " + $ver + " 自解压安装.exe")
if (Test-Path -LiteralPath $instSrc) {
    Copy-Item -LiteralPath $instSrc -Destination (Join-Path $root ("docs\Prism-Setup-" + $ver + ".exe")) -Force
    Get-ChildItem -LiteralPath (Join-Path $root 'docs') -Filter 'Prism-Setup-*.exe' |
        Where-Object { $_.Name -ne ("Prism-Setup-" + $ver + ".exe") } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host ('   删除旧安装包 ' + $_.Name) }
    Write-Host ('   docs\Prism-Setup-' + $ver + '.exe 已就位')
}

# ---- 便携版 zip（完整版解压即用，不写注册表）----
# 先清掉历史便携包，否则 docs/ 会越堆越大（曾经堆到 589MB / .git 7.2GB）
Get-ChildItem (Join-Path $root 'docs') -Filter 'Prism-Portable-*.zip' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne ("Prism-Portable-{0}.zip" -f $ver) } |
    ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force; Write-Host ('   删除旧便携包 ' + $_.Name) }
$portable = Join-Path (Join-Path $root 'docs') ("Prism-Portable-{0}.zip" -f $ver)
if ((Test-Path (Join-Path $root 'Prism.exe')) -and (Test-Path (Join-Path $root '_internal'))) {
    if (Test-Path $portable) { Remove-Item $portable -Force }
    Compress-Archive -Path (Join-Path $root 'Prism.exe'), (Join-Path $root '_internal') -DestinationPath $portable -CompressionLevel Optimal
    Write-Host ("   -> Prism-Portable-{0}.zip   {1:N1} MB" -f $ver, ((Get-Item $portable).Length / 1MB))
} else {
    Write-Host '   !! 未找到 onedir 构建，跳过便携版'
}

Write-Host '== 生成文档 HTML =='
& $py (Join-Path $root 'tools\make_docs_html.py')
if ($LASTEXITCODE -ne 0) { throw '文档 HTML 生成失败' }

Write-Host '== 重新生成网页效果图 =='
$sample = Join-Path $root 'design\sample.jpg'
if (Test-Path $sample) {
    & $py (Join-Path $root 'tools\make_shots.py') $sample
}

Write-Host '== 外观回归截图 =='
& $py (Join-Path $root 'tools\uishot.py')

# ---- 发布到 GitHub Release（仓库不保存二进制）----
$page = Join-Path $root 'docs\index.html'
$pageBak = "$page.bak"
$pushed = $false
try {
    $setup = Get-ChildItem (Join-Path $root 'docs') -File |
             Where-Object { $_.Name -eq ("Prism-Setup-{0}.exe" -f $ver) } |
             Select-Object -First 1
    if ($setup) {
        $sha = (Get-FileHash $setup.FullName -Algorithm SHA256).Hash
        $sizeMb = "{0:N1}" -f ($setup.Length / 1MB)
        if (Test-Path $page) {
            Copy-Item $page $pageBak -Force          # 自检失败时回滚用
            $html = Get-Content $page -Raw -Encoding UTF8
            $html = [regex]::Replace($html, '<code>[0-9A-Fa-f]{64}</code>', "<code>$sha</code>")
            $html = [regex]::Replace($html, '>\d+\.\d+ MB · Windows 10/11', ">$sizeMb MB · Windows 10/11")
            # 链接与文件名里的版本号（用 ${1} 明确分组，避免 $1 与版本号粘连）
            $html = [regex]::Replace($html, 'releases/download/v\d+\.\d+\.\d+/', "releases/download/v$ver/")
            $html = [regex]::Replace($html,
                '(Prism-(?:Viewer-Setup|Viewer|Portable|macOS|Linux|Setup)-)\d+\.\d+\.\d+(\.(?:exe|zip))',
                '${1}' + $ver + '${2}')
            # 页面上显示的版本号（品牌、meta、页脚）
            $html = [regex]::Replace($html, '<i>\d+\.\d+\.\d+</i>', "<i>$ver</i>")
            $html = [regex]::Replace($html, '版本 \d+\.\d+\.\d+', "版本 $ver")
            $html = [regex]::Replace($html, 'Prism \d+\.\d+\.\d+ ·', "Prism $ver ·")
            # data-ver 与 JSON-LD 里的软件版本不会出现在可见文字里，单独替换
            $html = [regex]::Replace($html, 'data-ver="\d+\.\d+\.\d+"', 'data-ver="' + $ver + '"')
            $html = [regex]::Replace($html, '"softwareVersion":"\d+\.\d+\.\d+"', '"softwareVersion":"' + $ver + '"')
            Set-Content -LiteralPath $page -Value $html -Encoding UTF8 -NoNewline
            Write-Host ("   页面已更新 SHA " + $sha.Substring(0, 12) + " / " + $sizeMb + " MB / 版本 $ver")
        }
        # 英文/日文页必须从更新后的中文页生成，否则版本号会落后一版
        Write-Host '== 生成英文/日文静态页 =='
        & $py (Join-Path $root 'tools\make_langpages.py')
        if ($LASTEXITCODE -ne 0) { throw '语言页生成失败' }
        & $py (Join-Path $root 'check_versions.py')
        if ($LASTEXITCODE -ne 0) { throw '版本号不一致：页面已更新但仍有旧版本号' }
        $tag = "v$ver"
        & git -C $root tag -f $tag 2>&1 | Out-Null
        & git -C $root push origin $tag --force 2>&1 | Out-Null
        $assets = Get-ChildItem (Join-Path $root 'docs') -File |
                  Where-Object { $_.Extension -in '.exe', '.zip' } |
                  ForEach-Object { $_.FullName }
        $notes = "Prism $ver — 详见 CHANGELOG.md"
        if ($assets.Count -gt 0) {
            $existing = (& gh release view $tag --json tagName 2>$null)
            if ($LASTEXITCODE -eq 0 -and $existing) {
                & gh release upload $tag @assets --clobber
            } else {
                & gh release create $tag --title "Prism $ver" --notes $notes @assets
            }
            if ($LASTEXITCODE -ne 0) {
                throw ("gh release 失败（退出码 " + $LASTEXITCODE + "）")
            }
            Write-Host ("   已上传 " + $assets.Count + " 个产物到 Release " + $tag)
            $pushed = $true
        }

        # ---- 自检：页面里每条下载链接都必须 200 ----
        Start-Sleep -Seconds 3
        $html = Get-Content $page -Raw -Encoding UTF8
        $hrefs = [regex]::Matches($html, 'href="(https://github\.com/11ly322/Prism/releases/download/[^"]+)"') |
                 ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
        $bad = @()
        foreach ($u in $hrefs) {
            $code = 0
            # 资产刚上传后可能短暂 404，重试 5 次、每次间隔 6 秒
            foreach ($attempt in 1..5) {
                try {
                    $r = Invoke-WebRequest -Uri $u -Method Head -UseBasicParsing -MaximumRedirection 5 -TimeoutSec 30
                    $code = [int]$r.StatusCode
                } catch {
                    try { $code = [int]$_.Exception.Response.StatusCode.value__ } catch { $code = 0 }
                }
                if ($code -eq 200) { break }
                Start-Sleep -Seconds 6
            }
            if ($code -ne 200) { $bad += ("{0} -> {1}" -f ($u -replace '.*/download/', ''), $code) }
        }
        if ($bad.Count -gt 0) {
            Write-Host '   !! 下载链接自检失败，回滚页面：' -ForegroundColor Red
            $bad | ForEach-Object { Write-Host ("      " + $_) -ForegroundColor Red }
            if (Test-Path $pageBak) { Copy-Item $pageBak $page -Force; Write-Host '   页面已回滚到发布前状态' }
            throw "download links failed self-check"
        }
        Write-Host ("   自检通过：" + $hrefs.Count + " 条下载链接全部 200")
    }
} catch {
    Write-Host ("   发布流程出错：" + $_.Exception.Message) -ForegroundColor Red
    throw
} finally {
    if (Test-Path $pageBak) { Remove-Item $pageBak -Force -ErrorAction SilentlyContinue }
    if ($pushed) {
        Get-ChildItem (Join-Path $root 'docs') -File |
            Where-Object { $_.Extension -in '.exe', '.zip' } |
            ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
        Write-Host '   已清理 docs 下的二进制（定位见 GitHub Releases）'
    }
}
