@echo off
:: AstroQuant — Add Windows Firewall rule for Chrome CDP port 9222
:: Double-click this file on Windows. Windows will ask for admin permission.
:: This is required once so WSL2 can reach Chrome's debugging port.

echo Adding AstroQuant CDP firewall rule (port 9222)...
netsh advfirewall firewall delete rule name="AstroQuant-CDP" >nul 2>&1
netsh advfirewall firewall add rule name="AstroQuant-CDP" dir=in action=allow protocol=TCP localport=9222

echo.
echo Done. Port 9222 is now open for AstroQuant.
echo You can close this window.
pause
