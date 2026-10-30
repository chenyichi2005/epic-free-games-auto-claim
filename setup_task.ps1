# 安裝套件到 lib 資料夾，並建立每週五 12:00 執行的 Windows 排程
$dir = $PSScriptRoot
$taskName = "Epic 免費遊戲自動領取"

python -m pip install --target "$dir\lib" -r "$dir\requirements.txt"

$action = New-ScheduledTaskAction -Execute "$dir\run.bat" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 12:00
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Description "每週五自動在 Epic 啟動器領取免費遊戲" -Force | Out-Null

Write-Host "完成！排程「$taskName」已建立，每週五 12:00 執行。"
