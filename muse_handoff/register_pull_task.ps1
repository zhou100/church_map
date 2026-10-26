# Registers the Windows scheduled task "ChurchMapMusePull" that runs drive_pull_hourly.sh every
# hour (and at logon). It runs as the current user, only while logged on: Google Drive for
# desktop's G: exists only in that session. No admin rights needed. Re-running replaces the task.
#
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File \\wsl$\Ubuntu\home\yujunz\llm_projects\holyhub\muse_handoff\register_pull_task.ps1
#
# Remove with: schtasks.exe /Delete /TN ChurchMapMusePull /F
$script = '/home/yujunz/llm_projects/holyhub/muse_handoff/drive_pull_hourly.sh'
$action = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless wsl.exe -d Ubuntu -u root -- bash $script"
$start = (Get-Date).Date.AddHours((Get-Date).Hour + 1).AddMinutes(5)
$hourly = New-ScheduledTaskTrigger -Once -At $start -RepetitionInterval (New-TimeSpan -Hours 1)
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 50)
Register-ScheduledTask -TaskName ChurchMapMusePull -Action $action -Trigger $hourly, $logon `
    -Principal $principal -Settings $settings -Force `
    -Description 'Hourly Muse Drive pull (holyhub muse_handoff/drive_pull_hourly.sh)' | Out-Null
Get-ScheduledTask ChurchMapMusePull | Get-ScheduledTaskInfo | Format-List TaskName, NextRunTime
