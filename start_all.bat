@echo off
REM MISCADA项目快速启动脚本 (Windows)
REM 启动所有后端服务

echo ========================================
echo    MISCADA 项目启动脚本
echo ========================================
echo.

REM 使用 Anaconda Python（已确认路径）
set PYTHON=C:\ProgramData\anaconda3\python.exe
set KMP_DUPLICATE_LIB_OK=TRUE

echo [1/4] 检查依赖...
%PYTHON% -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo [警告] 未安装FastAPI，正在安装依赖...
    cd MedSAM-main
    %PYTHON% -m pip install -r requirements_services.txt
    cd ..
)

echo.
echo [2/4] 检查模型文件...
if not exist "MedSAM-main\work_dir\MedSAM\medsam_vit_b.pth" (
    echo [警告] 未找到MedSAM模型文件 (端口8000服务将无法分割，其他服务正常)
    echo 下载地址: https://drive.google.com/drive/folders/1ETWmi4AiniJeWOt6HAsYgTjYv_fkgzoN
    echo.
)

echo.
echo [3/4] 启动服务...
echo.

REM 启动MedSAM服务
echo 启动 MedSAM 分割服务 (端口 8000)...
cd MedSAM-main
start cmd /k "title MedSAM Service && set KMP_DUPLICATE_LIB_OK=TRUE && C:\ProgramData\anaconda3\python.exe medsam_service.py"
cd ..
timeout /t 3 /nobreak >nul

REM 启动LLM服务
echo 启动 LLM 诊断服务 (端口 8001)...
cd MedSAM-main
start cmd /k "title LLM Diagnostic Service && set KMP_DUPLICATE_LIB_OK=TRUE && C:\ProgramData\anaconda3\python.exe llm_diagnostic_service.py"
cd ..
timeout /t 3 /nobreak >nul

REM 启动LiteMedSAM服务
echo 启动 LiteMedSAM 快速分割服务 (端口 8002)...
cd MedSAM-LiteMedSAM
start cmd /k "title LiteMedSAM Service && set KMP_DUPLICATE_LIB_OK=TRUE && C:\ProgramData\anaconda3\python.exe litemedsam_service.py"
cd ..
timeout /t 3 /nobreak >nul

REM 启动MedSAM2 3D服务
echo 启动 MedSAM2 3D追踪服务 (端口 8003)...
cd MedSAM2
start cmd /k "title MedSAM2 3D Service && set KMP_DUPLICATE_LIB_OK=TRUE && C:\ProgramData\anaconda3\python.exe medsam2_service.py"
cd ..
timeout /t 3 /nobreak >nul

echo.
echo [4/4] 启动前端...
echo 检查前端依赖...
cd miscada-project-master
if not exist "node_modules\" (
    echo 首次运行，正在安装前端依赖（需要3-5分钟）...
    yarn.cmd install
)
echo 启动 OHIF 前端 (端口 3000)...
start cmd /k "title OHIF Frontend && yarn.cmd run dev:orthanc"
cd ..

echo.
echo ========================================
echo    服务启动完成
echo ========================================
echo.
echo 访问地址:
echo   OHIF前端:        http://localhost:3000
echo   MedSAM服务:      http://localhost:8000
echo   LLM服务:         http://localhost:8001
echo   LiteMedSAM服务:  http://localhost:8002
echo   MedSAM2 3D服务:  http://localhost:8003
echo   Orthanc:         http://localhost:8042
echo.
echo 提示:
echo   - 各服务在独立的命令窗口中运行
echo   - 关闭窗口即可停止对应服务
echo   - 等待约30秒让所有服务完全启动
echo.
echo 按任意键退出此窗口...
pause >nul
