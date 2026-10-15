@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name ZeroAI --add-data "zeroai\workflows;zeroai\workflows" app.py
if errorlevel 1 exit /b 1
powershell -NoProfile -Command "Compress-Archive -Path 'dist\ZeroAI\*' -DestinationPath 'dist\ZeroAI-Windows-x64.zip' -Force"
echo.
echo Built: dist\ZeroAI-Windows-x64.zip
endlocal
