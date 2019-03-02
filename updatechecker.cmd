
@echo off
set PYTHONIOENCODING=UTF-8
pushd %~dp0
venv.cmd %~dp0__main__.py %*
