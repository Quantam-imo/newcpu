# AstroQuant Windows Auto-Start

This setup starts AstroQuant automatically when Windows starts:

1. Backend (FastAPI)
2. Trading engine (MultiSymbolRunner via API)
3. Dashboard
4. Optional watchdog for crash recovery

## Files Added

- `astroquant/start_astroquant.bat`
- `astroquant/watchdog_astroquant.ps1`
- `astroquant/stop_astroquant.bat`
- `astroquant/install_autostart_task.ps1`
- `astroquant/auto_setup_windows.bat`

## 0) Fully Automatic Setup (Fastest)

After you pull latest code on Windows, run this once as Administrator:

```bat
auto_setup_windows.bat
```

This does everything automatically:

1. Installs Task Scheduler autostart task
2. Starts AstroQuant immediately
3. Enables start on every logon

## 1) One-Time Path Check

Expected layout on Windows machine:

- `C:\newcpu-main\newcpu-main\astroquant`
- `C:\newcpu-main\newcpu-main\.venv\Scripts\python.exe`

The batch script auto-detects paths based on where the batch file is located. Keep the script inside the `astroquant` folder.

## 2) Manual Test

Double-click:

- `start_astroquant.bat`

Expected result:

- Backend command window opens
- Dashboard opens at `http://127.0.0.1:8000`
- Engine starts via `POST /engine/start`
- Watchdog starts minimized and writes logs to `logs/watchdog.log`

## 3) One-Click Task Scheduler Install (Manual Alternative)

Run PowerShell as Administrator in `astroquant` folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart_task.ps1
```

Optional custom name/delay:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_autostart_task.ps1 -TaskName "AstroQuant Auto Start" -DelaySeconds 30
```

After this, AstroQuant starts automatically at logon.

## 4) Manual Task Scheduler Method (Alternative)

Use Task Scheduler instead of Startup folder for better reliability.

1. Open `Task Scheduler`.
2. Create Task (not Basic Task).
3. General tab:
   - Name: `AstroQuant Auto Start`
   - Check: `Run with highest privileges`
   - Configure for your Windows version.
4. Triggers tab:
   - New Trigger: `At log on` (your user).
   - Optional delay: 20-30 seconds.
5. Actions tab:
   - Program/script: `C:\newcpu-main\newcpu-main\astroquant\start_astroquant.bat`
6. Conditions tab:
   - Uncheck `Start the task only if the computer is on AC power` if needed.
7. Settings tab:
   - Check `Allow task to be run on demand`.
   - Check `If the task fails, restart every` and set retries.

## 5) Auto-Start Method B: Startup Folder

1. Press `Win + R` and run `shell:startup`
2. Copy shortcut of `start_astroquant.bat` into that folder

This method is simpler but less robust than Task Scheduler.

## 6) Stop AstroQuant Cleanly

Use:

- `stop_astroquant.bat`

This sends `/engine/stop`, then stops watchdog and backend processes.

## 7) Production Notes

- Keep `ORDER_EXECUTION_MODE=confirm-token` for safety until fully validated.
- Review watchdog logs in `logs/watchdog.log`.
- If dashboard does not load, check backend window output first.
- Watchdog recovery coverage:
   - backend process crash -> auto restart
   - engine not running -> auto start via `/engine/start`
   - Playwright disconnected/stale -> auto reconnect via `/execution/reconnect?force=true`
   - Telegram inactive -> auto recovery test via `/telegram/test`
- Watchdog sends Telegram recovery alerts when recovery actions occur (if Telegram is configured).
