# 启用仓库自带的 Git 钩子（提交前拦截 + 推送前全量扫描）。
# 用法：powershell -ExecutionPolicy Bypass -File scripts/install_hooks.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path '.githooks/pre-commit')) {
    throw "未找到 .githooks/pre-commit，请在仓库根目录执行"
}

git config core.hooksPath .githooks

# 保证钩子在类 Unix 环境可执行（Git for Windows 不依赖该位，但其他平台需要）
git update-index --add --chmod=+x .githooks/pre-commit  .githooks/pre-push 2>$null | Out-Null

Write-Host "已启用 .githooks（core.hooksPath=.githooks）"
Write-Host "  pre-commit : 只扫暂存区，发现疑似密钥阻断提交"
Write-Host "  pre-push   : 全量扫描（工作区 + 历史 + .env 反查）"
Write-Host "手动自检   : .venv\Scripts\python.exe scripts\secret_scan.py"
