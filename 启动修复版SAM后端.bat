@echo off
chcp 65001 >nul
echo ===================================
echo MedSAM 后端修复和测试
echo ===================================
echo.

cd /d "%~dp0MedSAM-main"

echo [1/4] 停止旧的服务...
taskkill /F /IM python.exe /FI "WINDOWTITLE eq MedSAM*" 2>nul
timeout /t 2 /nobreak >nul

echo [2/4] 备份原文件...
if exist medsam_service.py (
    copy /Y medsam_service.py medsam_service_backup.py >nul
    echo ✓ 已备份 medsam_service.py → medsam_service_backup.py
)

echo [3/4] 使用修复版本...
if exist medsam_service_fixed.py (
    copy /Y medsam_service_fixed.py medsam_service.py >nul
    echo ✓ 已使用修复版本
) else (
    echo ✗ 找不到 medsam_service_fixed.py
    pause
    exit /b 1
)

echo [4/4] 启动修复后的服务...
echo.
echo ===================================
echo 服务正在启动...
echo 访问: http://localhost:8000
echo 健康检查: http://localhost:8000/health
echo 按 Ctrl+C 可停止服务
echo ===================================
echo.

python medsam_service.py

pause
