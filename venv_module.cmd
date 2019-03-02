
@echo off
rem chcp 65001>nul
set PYTHONIOENCODING=UTF-8
if defined verbose (
    set _verbose_venv=-i
)
pushd %~dp0
venv\Scripts\python %_verbose_venv% -m run %*
