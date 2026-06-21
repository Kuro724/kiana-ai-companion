@echo off
REM ─── Kiana Launcher ───────────────────────────────────────────────────────
cd /d D:\kiana

echo [Kiana] Starting Flask backend...
start "Kiana-Backend" /min cmd /c "cd /d D:\kiana && python app.py"

timeout /t 3 /nobreak > nul

echo [Kiana] Starting 3D Mascot (Edge WebView2)...
python mascot.py
