@echo off
chcp 65001 >nul
echo =====================================
echo GitHub 一键上传脚本
echo =====================================
echo.

set /p USERNAME="请输入你的GitHub用户名: "

echo.
echo 正在添加远程仓库...
git remote add origin https://github.com/%USERNAME%/Medical-AI-Diagnostic-Platform.git

echo.
echo 正在推送代码到GitHub...
echo 注意：密码请使用Personal Access Token（不是账户密码）
echo Token获取地址: https://github.com/settings/tokens
echo.

git push -u origin master

echo.
echo =====================================
echo 上传完成！
echo 访问你的仓库: https://github.com/%USERNAME%/Medical-AI-Diagnostic-Platform
echo =====================================
pause
