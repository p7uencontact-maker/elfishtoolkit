@echo off
setlocal
cd /d "%~dp0"

REM Windows ships a fake "python.exe"/"python3.exe" stub (an App Execution Alias) that prints the
REM Microsoft Store message you saw when no real Python is on PATH. The "py" launcher that the
REM official python.org installer creates isn't affected by that, so prefer it.
where py >nul 2>&1
if %errorlevel%==0 (
    set PYCMD=py
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set PYCMD=python
    ) else (
        goto nopython
    )
)

echo Using Python via: %PYCMD%
%PYCMD% -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo.
    echo pip install failed -- see the error above.
    pause
    exit /b 1
)

%PYCMD% el_fish_suite_gui.py
if %errorlevel% neq 0 (
    echo.
    echo The suite exited with an error -- see above.
    pause
)
exit /b 0

:nopython
echo.
echo Python doesn't seem to be installed, or isn't set up on PATH yet.
echo.
echo 1. Install it from https://www.python.org/downloads/
echo    On the FIRST installer screen, tick "Add python.exe to PATH" before
echo    clicking Install -- easy to miss, it's unchecked by default.
echo 2. Already installed Python and still seeing the Microsoft Store message?
echo    Open Settings -^> Apps -^> Advanced app settings -^> App execution aliases,
echo    and turn OFF "App Installer python.exe" and "...python3.exe". Those are
echo    Windows' placeholder stubs and they shadow a real install.
echo 3. Close this window and double-click run_gui.bat again -- a fresh window
echo    picks up the updated PATH; one already open won't.
echo.
pause
exit /b 1
