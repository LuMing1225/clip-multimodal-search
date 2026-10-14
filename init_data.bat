@echo off
chcp 65001 >nul
title CLIP电商多模态检索系统 - 数据初始化

echo ============================================
echo   CLIP电商多模态检索系统 - 数据初始化
echo ============================================
echo.

set PYTHON=C:\Users\luming\anaconda3\envs\nlp\python.exe
set PROJECT_DIR=E:\shixunXM\工单4\05-CLIP电商多模态检索系统
set PYTHONPATH=%PROJECT_DIR%

cd /d "%PROJECT_DIR%"

echo [1/2] 生成合成电商商品数据集 (300件)...
"%PYTHON%" scripts\generate_dataset.py
if errorlevel 1 (
    echo 数据集生成失败！
    pause
    exit /b 1
)

echo.
echo [2/2] 初始化数据库并入库 (CLIP编码+Milvus+图谱)...
"%PYTHON%" scripts\init_data.py
if errorlevel 1 (
    echo 数据入库失败！
    pause
    exit /b 1
)

echo.
echo ============================================
echo   数据初始化完成！
echo   商品数量: 300
echo   运行 start.bat 启动系统
echo ============================================
pause
