@echo off
setlocal
cd /d "%~dp0"

set "BUNDLED_PY=C:\Users\Aakash\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

if exist "%BUNDLED_PY%" (
  echo Starting server with bundled Python...
  "%BUNDLED_PY%" "%~dp0sqlite_center_backend.py"
  goto :eof
)

where python >nul 2>nul
if %errorlevel%==0 (
  echo Starting server with system Python...
  python "%~dp0sqlite_center_backend.py"
  goto :eof
)

echo Python nahi mila.
echo Install Python ya bundled runtime available rakhein, phir dubara chalayein.
pause
