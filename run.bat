@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
"%PY%" claim_epic.py %* >> run_output.txt 2>&1
