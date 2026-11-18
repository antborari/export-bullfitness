@echo off
cd /d "%~dp0"
py exportador_asv.py
if errorlevel 1 pause
