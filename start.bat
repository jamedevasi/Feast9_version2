@echo off
cd /d "%~dp0"
call venv\Scripts\activate
set DATA_DIR=%~dp0data
set SECRET_KEY=local-dev-key
python run.py
