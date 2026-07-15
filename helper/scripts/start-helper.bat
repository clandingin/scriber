@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create venv. Ensure Python 3.11+ is on PATH.
    exit /b 1
  )
  call ".venv\Scripts\pip.exe" install -U pip
  call ".venv\Scripts\pip.exe" install -e .
)

echo Starting Tab Transcriber helper on 127.0.0.1:17341 ...
echo Token will be written to helper\.token
echo First run downloads model weights (local cache only).
if "%~1"=="" (
  call ".venv\Scripts\python.exe" -m tab_transcriber_helper.server --model base.en
) else (
  call ".venv\Scripts\python.exe" -m tab_transcriber_helper.server %*
)
