@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PY=python"
if exist "python_path.txt" set /p PY=<python_path.txt
"%PY%" claim_epic.py %* >> run_output.txt 2>&1
