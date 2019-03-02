
@echo off
rem chcp 65001>nul
set PYTHONIOENCODING=UTF-8
pushd %~dp0
venv\Scripts\python %*
