@echo off
python "%~dp0preflight.py"
exit /b %ERRORLEVEL%