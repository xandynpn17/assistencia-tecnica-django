@echo off
setlocal
powershell -ExecutionPolicy Bypass -File "%~dp0run_lan.ps1" %*
