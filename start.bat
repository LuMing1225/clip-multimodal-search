@echo off
chcp 65001 >nul
title CLIP电商多模态检索系统 - 一键启动

echo ============================================
echo   CLIP电商多模态检索系统 - 启动脚本
echo   后端端口: 8565  前端端口: 8525
echo ============================================
echo.

set PYTHON=C:\Users\luming\anaconda3\envs\nlp\python.exe
set PROJECT_DIR=E:\shixunXM\工单4\05-CLIP电商多模态检索系统
set PYTHONPATH=%PROJECT_DIR%
set HF_HUB_OFFLINE=1

cd /d "%PROJECT_DIR%"

echo [1/2] 启动后端服务 (端口 8565)...
start "CLIP后端服务" cmd /k ""%PYTHON%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8565"

timeout /t 3 /nobreak >nul

echo [2/2] 启动前端服务 (端口 8525)...
start "CLIP前端服务" cmd /k ""%PYTHON%" "%PROJECT_DIR%\frontend\serve.py""

timeout /t 5 /nobreak >nul

echo.
echo ============================================
echo   启动完成！
echo   前端: http://localhost:8525
echo   后端: http://localhost:8565
echo   状态: http://localhost:8565/api/stats
echo ============================================
echo.
echo 按任意键打开浏览器...
pause >nul
start http://localhost:8525
