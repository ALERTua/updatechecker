
@echo off
pushd %~dp0

where uv >nul || (echo no uv. exiting & exit /b 1)

uv run updatechecker

set _ERRORLEVEL=%ERRORLEVEL%
echo Exiting %_ERRORLEVEL%
exit /b %_ERRORLEVEL%
