@echo off
chcp 65001 >nul
title PDF Studio
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 run.py
    goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
    python run.py
    goto end
)

echo.
echo  [!] Python غير مثبت على الجهاز.
echo      حمّله من https://www.python.org/downloads/
echo      ومهم جدا: فعّل خيار "Add Python to PATH" اثناء التثبيت.
echo.
pause

:end
echo.
echo تم ايقاف الاداة.
pause
