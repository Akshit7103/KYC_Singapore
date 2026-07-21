@echo off
echo ============================================
echo   KYC Verifier - stopping
echo ============================================
powershell -NoProfile -Command "$c = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue; if ($c) { $c.OwningProcess | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force; Write-Host ('Stopped server (PID ' + $_ + ').') } } else { Write-Host 'KYC Verifier is not running on port 8000.' }"
echo.
pause
