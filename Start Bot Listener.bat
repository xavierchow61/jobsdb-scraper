@echo off
cd /d "%~dp0"
title JobsDB Bot Listener
echo Starting Telegram bot listener...
echo (Close this window to stop the bot.)
echo.
python bot_listener.py
echo.
echo Bot has stopped.
pause
