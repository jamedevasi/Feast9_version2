@echo off
cd /d "%~dp0"
call venv\Scripts\activate
set DATA_DIR=%~dp0data
rem No SECRET_KEY here: Feast9 generates a random one on first start and keeps it in
rem data\secret_key. Setting a fixed value in a file that's in Git would let anyone who
rem has read this repo forge a login.
python run.py
