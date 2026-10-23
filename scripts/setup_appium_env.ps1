# -*- coding: utf-8 -*-
# Appium + ADB + Java + Python 环境配置一键脚本（Windows / PowerShell）
# 幂等：已装则跳过，只补缺；每个组失败不影响后续组。
# 用法：powershell -ExecutionPolicy Bypass -File scripts/setup_appium_env.ps1

$ErrorActionPreference = "Continue"
$root = Split-Path $PSScriptRoot -Parent
$APPIUM_HOME = Join-Path $root "tools\appium\.appium"          # 驱动装在项目内
$APPIUM_MAIN  = Join-Path $root "tools\appium\node_modules\appium\build\lib\main.js"

function Step($name) { Write-Host ""; Write-Host "==== $name ====" -ForegroundColor Cyan }

function Ensure-PythonClient {
    Step "【1/4】Python Appium 客户端 (Appium-Python-Client)"
    python -c "import appium; print('已安装 Appium-Python-Client', appium.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host ">> 已存在，跳过" -ForegroundColor Green; return }
    Write-Host ">> 安装 Appium-Python-Client ..."
    python -m pip install --upgrade pip
    python -m pip install "Appium-Python-Client>=3.0"
    python -c "import appium; print('>> 完成 Appium-Python-Client', appium.__version__)" 2>$null
}

function Ensure-NodeAndServer {
    Step "【2/4】Node + Appium Server (项目内, APPIUM_HOME=$APPIUM_HOME)"
    node -v 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "!! 未安装 Node.js。请到 https://nodejs.org 下载 LTS 安装（会自动配 PATH），再重跑本脚本。" -ForegroundColor Yellow
        return
    }
    if (-not (Test-Path $APPIUM_MAIN)) {
        Write-Host ">> 未找到项目内 Appium server，正在安装 ..."
        Push-Location (Join-Path $root "tools\appium")
        npm install
        Pop-Location
    } else {
        Write-Host ">> 项目内 Appium server 已存在" -ForegroundColor Green
    }
}

function Ensure-UiAutomator2 {
    Step "【3/4】UiAutomator2 驱动"
    if (Test-Path (Join-Path $APPIUM_HOME "node_modules\appium-uiautomator2-driver")) {
        Write-Host ">> uiautomator2 驱动已存在，跳过" -ForegroundColor Green; return
    }
    $env:APPIUM_HOME = $APPIUM_HOME
    & node $APPIUM_MAIN driver install uiautomator2
    if ($LASTEXITCODE -ne 0) {
        Write-Host ">> 驱动安装失败（可能网络问题），参考 docs/appium_env_setup.md 手动安装" -ForegroundColor Yellow
    }
}

function Ensure-Adb {
    Step "【4/4】ADB (Android SDK platform-tools)"
    # ANDROID_HOME 通常已设：D:\SDK\platform-tools\adb.exe
    $adbHome = $env:ANDROID_HOME
    $adbCandidates = @()
    if ($adbHome) { $adbCandidates += (Join-Path $adbHome "platform-tools\adb.exe") }
    $onPath = Get-Command adb -ErrorAction SilentlyContinue
    if ($onPath) { Write-Host ">> 已装 adb: $($onPath.Source)" -ForegroundColor Green }
    elseif ($adbCandidates | Where-Object { Test-Path $_ }) {
        Write-Host ">> 找到 adb: $($adbCandidates | Where-Object {Test-Path $_} | Select-Object -First 1)" -ForegroundColor Green
        Write-Host ">> 建议把 android SDK 的 platform-tools\ 加入 PATH，或直接设设备串口使用。"
    } else {
        Write-Host "!! 未找到 adb。请安装 Android SDK platform-tools 或通过 Android Studio SDK Manager 安装 platform-tools + platform + build-tools。" -ForegroundColor Yellow
    }
    if (Test-Path (Join-Path $root "tools\android")) {
        Write-Host ">> 设备列表（可选曾影像确认）："
        adb devices 2>$null
    }
}

function Verify-All {
    Step "校验"
    Write-Host "Python:     $((python --version 2>&1))"
    Write-Host "Node:       $((node -v 2>&1))"
    Write-Host "Java:       $((java -version 2>&1 | Select-Object -First 1))"
    Write-Host "ADB:        $((adb version 2>&1 | Select-Object -First 1))"
    $imports = python -c "import appium, appium.webdriver, appium.options.android, appium.webdriver.common.appiumby; print('Appium-Python-Client import OK')" 2>&1
    Write-Host "Appium-py:  $imports"
    if (Test-Path $APPIUM_MAIN) {
        $env:APPIUM_HOME = $APPIUM_HOME
        Write-Host "Appium服务: node $APPIUM_MAIN --version"
        node $APPIUM_MAIN --version 2>&1 | Select-Object -Last 1
        node $APPIUM_MAIN driver list --installed 2>&1 | Select-String "uiautomator2"
    }
}

Ensure-PythonClient
Ensure-NodeAndServer
Ensure-UiAutomator2
Ensure-Adb
Verify-All
Write-Host ""
Write-Host "环境配置完成。真机/模拟器已连接后，可执行:" -ForegroundColor Cyan
Write-Host "  python execution/runner.py D:/higo-api send_red_packet <deviceserial>" -ForegroundColor Gray