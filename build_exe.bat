@echo off
REM Builds MacroRecorder.exe from MacroRecorder.py (run this on Windows).
REM Needs Python installed from python.org (tick "Add Python to PATH").

cd /d "%~dp0"
echo Installing required packages...
python -m pip install --upgrade pynput pyinstaller
if errorlevel 1 goto fail

echo Building exe...
python -m PyInstaller --onefile --windowed --name MacroRecorder MacroRecorder.py
if errorlevel 1 goto fail

echo.
echo Done! Your exe is here:  %~dp0dist\MacroRecorder.exe
pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
