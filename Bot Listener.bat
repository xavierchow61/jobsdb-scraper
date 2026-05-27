@echo off
cd /d "%~dp0"
title HK Job Scraper - Telegram Bot
echo Starting Telegram bot listener...
echo.
echo Send /help to your bot in Telegram.
echo Press Ctrl+C in this window to stop.
echo.
python bot.py
echo.
echo Bot stopped. Press any key to close window.
pause >nul
