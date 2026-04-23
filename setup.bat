@echo off
title Renegade Records — Setup Wizard
color 0A

echo.
echo  =====================================================
echo   RENEGADE RECORDS — Discovery Engine Setup Wizard
echo  =====================================================
echo.
echo  This wizard will:
echo   1. Check Python + Node.js
echo   2. Collect your API keys
echo   3. Install all dependencies
echo   4. Start everything automatically
echo.
pause

:: CHECK PYTHON
echo.
echo [1/5] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('python --version') do echo  Found: %%i

:: CHECK NODE
echo.
echo [2/5] Checking Node.js...
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ERROR: Node.js not found. Install from https://nodejs.org
    pause & exit /b 1
)
for /f "tokens=*" %%i in ('node --version') do echo  Found: Node.js %%i

:: COLLECT KEYS
echo.
echo  =====================================================
echo  [3/5] API Keys Setup
echo  =====================================================
echo.
echo  SPOTIFY API (Priority source — best artist data)
echo  Get from: https://developer.spotify.com/dashboard
echo  Create an app then copy Client ID and Client Secret
echo.
set /p SPOTIFY_ID="  Spotify Client ID: "
set /p SPOTIFY_SECRET="  Spotify Client Secret: "

echo.
echo  CLAUDE API KEY
echo  Get from: https://console.anthropic.com/settings/keys
echo.
set /p CLAUDE_KEY="  Claude API Key (sk-ant-...): "

echo.
echo  SUPABASE (optional — press ENTER to skip)
echo  Get from: https://supabase.com
echo.
set /p SUPABASE_URL="  Supabase URL (press ENTER to skip): "
set /p SUPABASE_KEY="  Supabase anon key (press ENTER to skip): "

:: WRITE .ENV FILES
echo.
echo  Writing .env files...

(
echo SPOTIFY_CLIENT_ID=%SPOTIFY_ID%
echo SPOTIFY_CLIENT_SECRET=%SPOTIFY_SECRET%
echo LASTFM_API_KEY=156d007301853d76f0d41665092f879a
echo CLAUDE_API_KEY=%CLAUDE_KEY%
echo SUPABASE_URL=%SUPABASE_URL%
echo SUPABASE_KEY=%SUPABASE_KEY%
) > discovery\.env

(
echo SUPABASE_URL=%SUPABASE_URL%
echo SUPABASE_KEY=%SUPABASE_KEY%
echo CLAUDE_API_KEY=%CLAUDE_KEY%
echo RESEND_API_KEY=
echo FROM_EMAIL=studio@renegaderecords.com
echo PORT=4000
) > backend\.env

(
echo VITE_API_URL=http://localhost:4000
) > dashboard\.env

echo  .env files written successfully.

:: INSTALL DEPENDENCIES
echo.
echo  =====================================================
echo  [4/5] Installing Dependencies
echo  =====================================================
echo.

echo  Installing Python packages...
cd discovery
pip install -r requirements.txt --quiet
cd ..
echo  Python packages done.

echo  Installing backend packages...
cd backend
call npm install --silent
cd ..
echo  Backend packages done.

echo  Installing dashboard packages...
cd dashboard
call npm install --silent
cd ..
echo  Dashboard packages done.

:: START EVERYTHING
echo.
echo  =====================================================
echo  [5/5] Starting Renegade Records Engine
echo  =====================================================
echo.
start "Renegade Backend"   cmd /k "cd /d %~dp0backend && node server.js"
timeout /t 2 /nobreak >nul
start "Renegade Dashboard" cmd /k "cd /d %~dp0dashboard && npm run dev"
timeout /t 4 /nobreak >nul
start http://localhost:3000

echo.
echo  =====================================================
echo   Setup complete!
echo   Dashboard : http://localhost:3000
echo   Backend   : http://localhost:4000
echo  =====================================================
echo.
echo  Run discovery engine now? (yes/no)
set /p RUN_NOW="  Your choice: "
if /i "%RUN_NOW%"=="yes" (
    cd discovery
    python discovery.py
    cd ..
)
echo.
echo  Done! Use run.bat for future runs.
pause
