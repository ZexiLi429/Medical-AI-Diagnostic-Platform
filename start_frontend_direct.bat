@echo off
REM 直接启动前端（绕过 lerna）
echo Starting OHIF Frontend directly...
cd miscada-project-master\platform\app
start cmd /k "title OHIF Frontend && yarn.cmd run dev:orthanc"
echo Frontend starting on http://localhost:3000
pause
