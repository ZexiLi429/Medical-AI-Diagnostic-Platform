@echo off
REM MISCADA项目快速启动脚本 (Windows)
REM 启动所有后端服务

echo ========================================
echo    MISCADA 项目启动脚本
echo ========================================
echo.

REM 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python
    pause
    exit /b 1
)

echo [1/4] 检查依赖...
python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [警告] 未安装FastAPI，正在安装依赖...
    cd MedSAM-main
    pip install -r requirements_services.txt
    cd ..
)

echo.
echo [2/4] 检查模型文件...
if not exist "MedSAM-main\work_dir\MedSAM\medsam_vit_b.pth" (
    echo [警告] 未找到MedSAM模型文件
    echo 请下载模型到: MedSAM-main\work_dir\MedSAM\medsam_vit_b.pth
    echo 下载地址: https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN
    echo.
    echo 是否继续启动其他服务? (y/n)
    set /p continue=
    if /i not "%continue%"=="y" exit /b 0
)

echo.
echo [3/4] 启动服务...
echo.

REM 启动MedSAM服务
echo 启动 MedSAM 分割服务 (端口 8000)...
cd MedSAM-main
start cmd /k "title MedSAM Service && python medsam_service.py"
cd ..
timeout /t 3 /nobreak >nul

REM 启动LLM服务
echo 启动 LLM 诊断服务 (端口 8001)...
cd MedSAM-main
start cmd /k "title LLM Diagnostic Service && python llm_diagnostic_service.py"
cd ..
timeout /t 3 /nobreak >nul

echo.
echo [4/4] 启动前端...
echo 启动 OHIF 前端 (端口 3000)...
cd miscada-project-master
start cmd /k "title OHIF Frontend && yarn run dev:orthanc"
cd ..

echo.
echo ========================================
echo    服务启动完成
echo ========================================
echo.
echo 访问地址:
echo   OHIF前端:     http://localhost:3000
echo   MedSAM服务:   http://localhost:8000
echo   LLM服务:      http://localhost:8001
echo   Orthanc:      http://localhost:8042
echo.
echo 提示:
echo   - 各服务在独立的命令窗口中运行
echo   - 关闭窗口即可停止对应服务
echo   - 等待约30秒让所有服务完全启动
echo.
echo 按任意键退出此窗口...
pause >nul
