@echo off
REM ========================================
REM SAM 功能快速测试脚本
REM ========================================

echo ========================================
echo SAM 前后端连接测试
echo ========================================
echo.

REM 1. 检查后端是否运行
echo [1/4] 检查MedSAM后端服务...
curl -s http://localhost:8000/health > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ 后端运行正常 http://localhost:8000
    curl -s http://localhost:8000/health
    echo.
) else (
    echo ❌ 后端未运行！
    echo.
    echo 请在新窗口运行:
    echo   cd MedSAM-main
    echo   python medsam_service.py
    echo.
    pause
    exit /b 1
)

REM 2. 检查模型文件
echo [2/4] 检查MedSAM模型文件...
if exist "MedSAM-main\work_dir\MedSAM\medsam_vit_b.pth" (
    echo ✅ 模型文件存在
    for %%A in ("MedSAM-main\work_dir\MedSAM\medsam_vit_b.pth") do (
        echo    文件大小: %%~zA 字节
    )
) else (
    echo ❌ 模型文件缺失
    echo.
    echo 请下载模型文件 medsam_vit_b.pth 到:
    echo   MedSAM-main\work_dir\MedSAM\
    echo.
    echo 下载地址: https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN
    echo.
    pause
)

REM 3. 检查前端（如果运行）
echo [3/4] 检查OHIF前端...
curl -s http://localhost:3000 > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ✅ 前端运行正常 http://localhost:3000
) else (
    echo ⚠️  前端未运行
    echo.
    echo 请在新窗口运行:
    echo   cd miscada-project-master
    echo   yarn run dev
    echo.
)

REM 4. 检查按钮配置
echo [4/4] 检查SAM按钮配置...
findstr /C:"{ name: 'evaluate.cornerstone.segmentation'}" "miscada-project-master\modes\sam\src\toolbarButtons.ts" > nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo ❌ 按钮配置仍包含segmentation限制
    echo    请确认已修改 toolbarButtons.ts
) else (
    echo ✅ 按钮配置已修复（已移除segmentation限制）
)

echo.
echo ========================================
echo 测试完成！
echo ========================================
echo.
echo 📌 使用说明:
echo 1. 打开浏览器访问 http://localhost:3000
echo 2. 选择 "MedSAM Viewer" 模式
echo 3. 上传DICOM数据
echo 4. 右侧工具栏点击 "Store Original Slice"
echo 5. 使用 Rectangle 工具画框
echo 6. 点击 "Apply MedSAM Model" 进行分割
echo.
echo 📚 详细文档: 前后端连接诊断和修复指南.md
echo.
pause
