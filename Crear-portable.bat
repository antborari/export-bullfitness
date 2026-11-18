@echo off
setlocal
cd /d "%~dp0"

py -m pip install pyinstaller
if errorlevel 1 (
  echo No se pudo instalar PyInstaller.
  pause
  exit /b 1
)

py -m PyInstaller --noconfirm --clean --onefile --windowed --name Exportador-ASV exportador_asv.py
if errorlevel 1 (
  echo No se pudo crear el ejecutable.
  pause
  exit /b 1
)

echo.
echo Aplicacion portable creada en: dist\Exportador-ASV.exe
pause
