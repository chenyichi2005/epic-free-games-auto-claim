﻿# 安裝程式：檢查環境 → 必要時安裝 Python → 安裝套件到 lib → 建立每週五 12:00 的排程
# 一般使用者請直接雙擊「安裝.bat」
$dir = $PSScriptRoot
$taskName = "Epic 免費遊戲自動領取"
$minVersion = [version]"3.10"

function Write-Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   [OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   [注意] $msg" -ForegroundColor Yellow }
function Stop-Setup($msg) { Write-Host "   [失敗] $msg" -ForegroundColor Red; exit 1 }

# 回傳可用（3.10 以上）的 python.exe 路徑，找不到回傳 $null
function Find-Python {
    $candidates = @()
    foreach ($name in "python", "py") {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # WindowsApps 裡的 python.exe 只是開啟 Microsoft Store 的捷徑，不算
        if ($cmd -and $cmd.Source -notlike "*\WindowsApps\*") { $candidates += $cmd.Source }
    }
    foreach ($pattern in "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe",
                         "$env:ProgramFiles\Python3*\python.exe",
                         "C:\Python3*\python.exe") {
        $candidates += Get-ChildItem $pattern -ErrorAction SilentlyContinue | ForEach-Object FullName
    }
    foreach ($exe in $candidates | Select-Object -Unique) {
        try {
            $pyArgs = if ((Split-Path $exe -Leaf) -eq "py.exe") { @("-3", "-c") } else { @("-c") }
            $out = & $exe @pyArgs "import sys; print(sys.version.split()[0]); print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out.Count -ge 2 -and [version]$out[0] -ge $minVersion) {
                return [pscustomobject]@{ Path = $out[1]; Version = $out[0] }
            }
        } catch {}
    }
    return $null
}

Write-Host "Epic 免費遊戲自動領取 - 安裝程式" -ForegroundColor White

# 1. Python
Write-Step "檢查 Python（需要 $minVersion 以上）"
$py = Find-Python
if ($py) {
    Write-Ok "已安裝 Python $($py.Version)，略過安裝：$($py.Path)"
} else {
    Write-Warn "找不到可用的 Python，開始自動安裝 Python 3.13（約 1~3 分鐘）"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Start-Process "https://www.python.org/downloads/windows/"
        Stop-Setup "這台電腦沒有 winget，無法自動安裝。已開啟 Python 官網，請下載安裝（記得勾選 Add python.exe to PATH），裝好後再執行一次安裝.bat"
    }
    winget install --exact --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements
    $py = Find-Python
    if (-not $py) { Stop-Setup "Python 安裝失敗，請到 https://www.python.org/downloads/windows/ 手動安裝後再執行一次安裝.bat" }
    Write-Ok "Python $($py.Version) 安裝完成：$($py.Path)"
}
# 記下 Python 路徑給 run.bat 使用（排程執行時 PATH 不一定有更新）
Set-Content -Path "$dir\python_path.txt" -Value $py.Path -Encoding ASCII -NoNewline

# 2. 套件
Write-Step "安裝套件到 lib 資料夾"
& $py.Path -m pip install --disable-pip-version-check --upgrade --target "$dir\lib" -r "$dir\requirements.txt"
if ($LASTEXITCODE -ne 0) { Stop-Setup "套件安裝失敗，請確認網路連線後再執行一次" }
Write-Ok "套件安裝完成"

# 3. 環境檢查（不符合只提醒，不中止）
Write-Step "檢查 Epic 啟動器與繁體中文 OCR"
if (Test-Path "Registry::HKEY_CLASSES_ROOT\com.epicgames.launcher") {
    Write-Ok "已安裝 Epic Games 啟動器（請確認已登入，且介面語言是繁體中文）"
} else {
    Write-Warn "找不到 Epic Games 啟動器，請先安裝並登入：https://store.epicgames.com/download"
}
try {
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
    $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | ForEach-Object LanguageTag
    if ($langs | Where-Object { $_ -match "^zh-(Hant|TW)" }) {
        Write-Ok "已有繁體中文 OCR"
    } else {
        Write-Warn "沒有繁體中文 OCR，請到「設定 → 時間與語言 → 語言與地區」新增「中文（台灣）」"
    }
} catch {
    Write-Warn "無法檢查 OCR 語言，請確認已安裝「中文（台灣）」語言"
}

# 4. 排程
Write-Step "建立排程"
$action = New-ScheduledTaskAction -Execute "$dir\run.bat" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 12:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "每週五自動在 Epic 啟動器領取免費遊戲" -Force -ErrorAction Stop | Out-Null
} catch {
    Stop-Setup "排程建立失敗：$($_.Exception.Message)"
}
Write-Ok "排程「$taskName」已建立，每週五 12:00 執行"

Write-Host ""
Write-Host "安裝完成！想立刻試跑一次，雙擊 run.bat 即可。" -ForegroundColor Green
