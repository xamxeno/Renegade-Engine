@echo off
title Renegade Records — Control Panel
color 0A

:MENU
cls
echo.
echo  =====================================================
echo   RENEGADE RECORDS — Control Panel
echo  =====================================================
echo.
echo   DISCOVERY
echo   [1] Run Discovery Engine     (Spotify + Last.fm + Deezer)
echo   [2] Run Enrichment Engine    (find Instagram + email)
echo   [3] Run Full Pipeline        (discovery then enrich)
echo.
echo   DASHBOARD
echo   [4] Start Dashboard + Backend
echo   [5] Start Backend only
echo   [6] Start Dashboard only
echo   [R] Restart Dashboard + Backend
echo.
echo   DATABASE
echo   [7] Sync leads to Supabase
echo.
echo   SETUP ^& TOOLS
echo   [8] Add / Update Spotify API Keys
echo   [9] Add / Update All API Keys
echo   [S] Check System Status
echo   [T] Test resolve one artist
echo   [0] Exit
echo.
echo  =====================================================
set /p CHOICE="   Enter choice: "

if "%CHOICE%"=="1" goto DISCOVERY
if "%CHOICE%"=="2" goto ENRICH
if "%CHOICE%"=="3" goto PIPELINE
if "%CHOICE%"=="4" goto DASH_AND_BACK
if "%CHOICE%"=="5" goto BACKEND
if "%CHOICE%"=="6" goto DASHBOARD
if "%CHOICE%"=="7" goto SYNC
if "%CHOICE%"=="8" goto SPOTIFY_KEYS
if "%CHOICE%"=="9" goto ALL_KEYS
if /i "%CHOICE%"=="R" goto RESTART
if /i "%CHOICE%"=="S" goto STATUS
if /i "%CHOICE%"=="T" goto TEST_RESOLVE
if "%CHOICE%"=="0" exit
echo   Invalid choice.
timeout /t 1 /nobreak >nul
goto MENU

:: ─────────────────────────────────────────────────────
:DISCOVERY
cls
echo.
echo  =====================================================
echo   Discovery Engine
echo   Spotify (priority) → Last.fm → Deezer
echo   Regions: USA · Canada · UK · Australia · UAE
echo  =====================================================
echo.
echo  The engine will find artists first, show you a
echo  preview, then ASK before spending Claude credits.
echo.
cd discovery
python discovery.py
cd ..
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:ENRICH
cls
echo.
echo  =====================================================
echo   Enrichment Engine
echo   Finds Instagram + Email for each lead
echo   Validates artist vs producer
echo   Asks before Claude scoring
echo  =====================================================
echo.
cd discovery
python enrich.py
cd ..
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:PIPELINE
cls
echo.
echo  =====================================================
echo   Discovery Engine
echo   (Instagram scanned inline — no separate enrich step)
echo  =====================================================
echo.
cd discovery
python discovery.py
cd ..
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:DASH_AND_BACK
cls
echo.
echo  Starting Backend + Dashboard...
echo.
start "Renegade Backend"   cmd /k "cd /d %~dp0backend && node server.js"
timeout /t 2 /nobreak >nul
start "Renegade Dashboard" cmd /k "cd /d %~dp0dashboard && npm run dev"
timeout /t 4 /nobreak >nul
start http://localhost:3000
echo.
echo  Dashboard : http://localhost:3000
echo  Backend   : http://localhost:4000
echo.
echo  Both running in separate windows.
echo  Close those windows to stop the services.
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:RESTART
cls
echo.
echo  Stopping existing Backend + Dashboard...
echo.
taskkill /fi "WINDOWTITLE eq Renegade Backend*"  /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq Renegade Dashboard*" /f >nul 2>&1
timeout /t 2 /nobreak >nul
echo  Restarting...
echo.
start "Renegade Backend"   cmd /k "cd /d %~dp0backend && node server.js"
timeout /t 2 /nobreak >nul
start "Renegade Dashboard" cmd /k "cd /d %~dp0dashboard && npm run dev"
timeout /t 4 /nobreak >nul
start http://localhost:3000
echo.
echo  Restarted. Dashboard: http://localhost:3000
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:BACKEND
cls
echo  Starting Backend on http://localhost:4000 ...
cd backend
node server.js
cd ..
goto MENU

:: ─────────────────────────────────────────────────────
:DASHBOARD
cls
echo  Starting Dashboard on http://localhost:3000 ...
start "Renegade Backend" cmd /k "cd /d %~dp0backend && node server.js"
timeout /t 2 /nobreak >nul
start http://localhost:3000
cd dashboard
npm run dev
cd ..
goto MENU

:: ─────────────────────────────────────────────────────
:SYNC
cls
echo.
echo  Syncing leads to Supabase...
echo.
cd discovery
python sync_supabase.py
cd ..
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:SPOTIFY_KEYS
cls
echo.
echo  =====================================================
echo   Spotify API Keys Setup
echo  =====================================================
echo.
echo  How to get your Spotify keys:
echo   1. Go to https://developer.spotify.com/dashboard
echo   2. Log in and click "Create App"
echo   3. Name: Renegade Engine
echo   4. Add redirect URI: https://example.com/callback
echo   5. Save, then go to Settings
echo   6. Copy Client ID and Client Secret
echo.
echo  Leave blank and press ENTER to keep existing value.
echo.
set /p NEW_ID="  Spotify Client ID: "
set /p NEW_SECRET="  Spotify Client Secret: "

:: Read existing values
for /f "tokens=1* delims==" %%a in ('findstr "SPOTIFY_CLIENT_ID" discovery\.env 2^>nul') do set OLD_ID=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SPOTIFY_CLIENT_SECRET" discovery\.env 2^>nul') do set OLD_SECRET=%%b
for /f "tokens=1* delims==" %%a in ('findstr "CLAUDE_API_KEY" discovery\.env 2^>nul') do set OLD_CLAUDE=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SUPABASE_URL" discovery\.env 2^>nul') do set OLD_SURL=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SUPABASE_KEY" discovery\.env 2^>nul') do set OLD_SKEY=%%b

if not "%NEW_ID%"==""     set OLD_ID=%NEW_ID%
if not "%NEW_SECRET%"=""  set OLD_SECRET=%NEW_SECRET%

(
echo SPOTIFY_CLIENT_ID=%OLD_ID%
echo SPOTIFY_CLIENT_SECRET=%OLD_SECRET%
echo LASTFM_API_KEY=156d007301853d76f0d41665092f879a
echo CLAUDE_API_KEY=%OLD_CLAUDE%
echo SUPABASE_URL=%OLD_SURL%
echo SUPABASE_KEY=%OLD_SKEY%
) > discovery\.env

echo.
echo  Spotify keys saved to discovery/.env
echo.
echo  Verifying Spotify connection...
cd discovery
python -c "
import os, requests
from base64 import b64encode
from dotenv import load_dotenv
load_dotenv()
cid = os.getenv('SPOTIFY_CLIENT_ID','')
sec = os.getenv('SPOTIFY_CLIENT_SECRET','')
if not cid or not sec:
    print('  [ERROR] Keys are empty — please re-enter')
else:
    try:
        creds = b64encode(f'{cid}:{sec}'.encode()).decode()
        r = requests.post('https://accounts.spotify.com/api/token',
            headers={'Authorization': f'Basic {creds}'},
            data={'grant_type': 'client_credentials'}, timeout=10)
        if r.json().get('access_token'):
            print('  [OK] Spotify connected successfully!')
        else:
            print(f'  [ERROR] {r.json()}')
    except Exception as e:
        print(f'  [ERROR] {e}')
"
cd ..
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:ALL_KEYS
cls
echo.
echo  =====================================================
echo   Update All API Keys
echo  =====================================================
echo.
echo  Leave blank and press ENTER to keep existing value.
echo.

:: Read all existing
for /f "tokens=1* delims==" %%a in ('findstr "SPOTIFY_CLIENT_ID" discovery\.env 2^>nul') do set OLD_SID=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SPOTIFY_CLIENT_SECRET" discovery\.env 2^>nul') do set OLD_SSEC=%%b
for /f "tokens=1* delims==" %%a in ('findstr "CLAUDE_API_KEY" discovery\.env 2^>nul') do set OLD_CLAUDE=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SUPABASE_URL" discovery\.env 2^>nul') do set OLD_SURL=%%b
for /f "tokens=1* delims==" %%a in ('findstr "SUPABASE_KEY" discovery\.env 2^>nul') do set OLD_SKEY=%%b

set /p NEW_SID="  Spotify Client ID: "
set /p NEW_SSEC="  Spotify Client Secret: "
set /p NEW_CLAUDE="  Claude API Key (sk-ant-...): "
set /p NEW_SURL="  Supabase URL: "
set /p NEW_SKEY="  Supabase anon key: "

if not "%NEW_SID%"==""    set OLD_SID=%NEW_SID%
if not "%NEW_SSEC%"==""   set OLD_SSEC=%NEW_SSEC%
if not "%NEW_CLAUDE%"=""  set OLD_CLAUDE=%NEW_CLAUDE%
if not "%NEW_SURL%"==""   set OLD_SURL=%NEW_SURL%
if not "%NEW_SKEY%"==""   set OLD_SKEY=%NEW_SKEY%

(
echo SPOTIFY_CLIENT_ID=%OLD_SID%
echo SPOTIFY_CLIENT_SECRET=%OLD_SSEC%
echo LASTFM_API_KEY=156d007301853d76f0d41665092f879a
echo CLAUDE_API_KEY=%OLD_CLAUDE%
echo SUPABASE_URL=%OLD_SURL%
echo SUPABASE_KEY=%OLD_SKEY%
) > discovery\.env

(
echo SUPABASE_URL=%OLD_SURL%
echo SUPABASE_KEY=%OLD_SKEY%
echo CLAUDE_API_KEY=%OLD_CLAUDE%
echo RESEND_API_KEY=
echo FROM_EMAIL=studio@renegaderecords.com
echo PORT=4000
) > backend\.env

(
echo VITE_API_URL=http://localhost:4000
) > dashboard\.env

echo.
echo  All keys saved successfully.
echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:STATUS
cls
echo.
echo  =====================================================
echo   System Status
echo  =====================================================
echo.

python --version >nul 2>&1
if %errorlevel%==0 (for /f "tokens=*" %%i in ('python --version') do echo  [OK] %%i) else (echo  [MISSING] Python — install from python.org)

node --version >nul 2>&1
if %errorlevel%==0 (for /f "tokens=*" %%i in ('node --version') do echo  [OK] Node.js %%i) else (echo  [MISSING] Node.js — install from nodejs.org)

echo.
echo  Checking .env files...
if exist discovery\.env (echo  [OK] discovery/.env found) else (echo  [MISSING] discovery/.env — run setup.bat)
if exist backend\.env   (echo  [OK] backend/.env found)   else (echo  [MISSING] backend/.env — run setup.bat)

echo.
echo  Checking API keys...
cd discovery
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
sid = os.getenv('SPOTIFY_CLIENT_ID','')
cid = os.getenv('CLAUDE_API_KEY','')
surl = os.getenv('SUPABASE_URL','')
print('  [OK] Spotify keys set' if sid else '  [MISSING] Spotify — use option 8')
print('  [OK] Claude API key set' if cid.startswith('sk-') else '  [MISSING] Claude key — use option 9')
print('  [OK] Supabase configured' if surl else '  [OPTIONAL] Supabase not set (saves to JSON)')
"
cd ..

echo.
echo  Checking latest leads file...
if exist discovery\leads_*.json (
    for /f "tokens=*" %%i in ('dir /b /od discovery\leads_*.json 2^>nul') do set LATEST=%%i
    echo  [OK] Latest leads: %LATEST%
) else (
    echo  [NONE] No leads yet — run Discovery Engine first
)

echo.
pause >nul
goto MENU

:: ─────────────────────────────────────────────────────
:TEST_RESOLVE
cls
echo.
echo  =====================================================
echo   Test Single Artist Resolution
echo  =====================================================
echo.
echo  Enter any artist name to test the full 5-step
echo  contact resolution pipeline on just that one artist.
echo.
echo  Good test names: "Kiana Lede", "Masego", "Giveon"
echo.
cd discovery
python resolve.py
cd ..
echo.
pause >nul
goto MENU
