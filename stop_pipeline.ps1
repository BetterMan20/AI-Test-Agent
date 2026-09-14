# 手动停止整条 AI 测试管线。
# 用法（在 IDE 终端里执行）：
#   .\stop_pipeline.ps1            # 停止所有在本项目内运行的 main.py
#   .\stop_pipeline.ps1 -DryRun    # 只列出会杀掉的进程，不真正结束

param(
    [switch]$DryRun
)

$root = "D:\Project\AI-Test-Agent"

$targets = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like "*$root*" -and
        $_.CommandLine -like "*main.py*"
    }

if (-not $targets) {
    Write-Host "没有检测到正在运行的管线 (main.py)。" -ForegroundColor Yellow
    exit 0
}

Write-Host ("找到 " + @($targets).Count + " 个管线进程：")
foreach ($t in $targets) {
    $cmd = ($t.CommandLine -replace '\s+', ' ')
    Write-Host ("  PID {0}: {1}" -f $t.ProcessId, $cmd) -ForegroundColor Cyan
}

if ($DryRun) {
    Write-Host "(DryRun) 未结束任何进程。" -ForegroundColor Cyan
    exit 0
}

foreach ($t in $targets) {
    Stop-Process -Id $t.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host ("已发送结束信号 PID {0}" -f $t.ProcessId) -ForegroundColor Green
}

Write-Host "管线已停止。" -ForegroundColor Green
