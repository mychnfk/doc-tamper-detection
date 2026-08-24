# deploy.ps1 — DocGuard 一键部署（Windows 10/11 + NVIDIA GPU）
# 四阶段：环境检测 → 安装依赖 → 运行测试 → 部署服务+状态报告
# 幂等设计：可重复运行，已完成的步骤自动跳过；失败后修复问题再双击一次即可续跑。
# 入口：仓库根目录的 deploy.bat（双击即可，本文件不直接运行）
# 兼容 PowerShell 5.1（Windows 自带版本），不使用 &&/三元等 7.x 语法。

$ErrorActionPreference = 'Stop'
try { chcp 65001 | Out-Null; [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$VenvPy = Join-Path $Root '.venv\Scripts\python.exe'
$Nssm = Join-Path $PSScriptRoot 'nssm.exe'
$ReportFile = Join-Path $Root 'deploy-report.txt'
$Results = New-Object System.Collections.ArrayList
$StartTime = Get-Date
$Script:GpuInfo = ''

# ── 自提权：winget 装 Python / 注册服务 / 开防火墙均需管理员 ─────────────
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '需要管理员权限，正在弹出 UAC 确认窗口…'
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    exit
}

function Add-Result([string]$Stage, [string]$Name, [string]$Status, [string]$Detail = '') {
    [void]$Results.Add([pscustomobject]@{ Stage = $Stage; Name = $Name; Status = $Status; Detail = $Detail })
    $color = 'Gray'
    if ($Status -eq 'OK') { $color = 'Green' }
    elseif ($Status -eq 'WARN') { $color = 'Yellow' }
    elseif ($Status -eq 'FAIL') { $color = 'Red' }
    Write-Host ('[{0,-4}] {1} | {2}  {3}' -f $Status, $Stage, $Name, $Detail) -ForegroundColor $color
}

function Stop-Deploy([string]$Stage, [string]$Name, [string]$Detail) {
    Add-Result $Stage $Name 'FAIL' $Detail
    throw "$Stage/${Name}: $Detail"
}

function Test-Tcp([string]$TargetHost, [int]$Port) {
    try {
        $client = New-Object Net.Sockets.TcpClient
        $task = $client.ConnectAsync($TargetHost, $Port)
        $ok = $task.Wait(5000) -and $client.Connected
        $client.Close()
        return $ok
    } catch { return $false }
}

function Get-SystemPython {
    # 返回 @{Exe=..; Pre=..}；优先 py 启动器精确选 3.12
    try {
        $v = & py -3.12 --version 2>&1
        if ("$v" -match 'Python 3\.12') { return @{ Exe = 'py'; Pre = @('-3.12') } }
    } catch {}
    try {
        $v = & python --version 2>&1
        if ("$v" -match 'Python 3\.12') { return @{ Exe = 'python'; Pre = @() } }
    } catch {}
    return $null
}

$DeployOk = $false
try {

# ═══ 阶段 1/4：环境检测 ══════════════════════════════════════════════════
Write-Host "`n═══ 阶段 1/4：环境检测 ═══" -ForegroundColor Cyan
$S = '1-环境检测'

$os = Get-CimInstance Win32_OperatingSystem
Add-Result $S 'Windows 版本' 'OK' ('{0} (build {1})' -f $os.Caption.Trim(), $os.BuildNumber)

# GPU：硬前置。没有 NVIDIA 驱动一切免谈
$smi = $null
try { $smi = & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null } catch {}
if (-not $smi) {
    Stop-Deploy $S 'NVIDIA 驱动' ('未检测到 nvidia-smi。请先到 nvidia.cn 下载安装显卡驱动' +
        '（GeForce Game Ready 或 Studio 均可），装完重启后再双击 deploy.bat')
}
$Script:GpuInfo = "$smi".Trim()
Add-Result $S 'NVIDIA GPU' 'OK' $Script:GpuInfo
if ($Script:GpuInfo -notmatch '4060') {
    Add-Result $S 'GPU 型号' 'WARN' '不是预期的 RTX 4060，性能结论需重新评估（不阻塞）'
}

# 磁盘：torch 2.5GB + venv + 模型，留足余量
$drive = (Get-Item $Root).PSDrive
$freeGB = [math]::Round($drive.Free / 1GB, 1)
if ($freeGB -lt 10) { Stop-Deploy $S '磁盘空间' "剩余 ${freeGB}GB < 10GB，请清理后重跑" }
Add-Result $S '磁盘空间' 'OK' "剩余 ${freeGB}GB"

# 随包资产清单：缺=包不完整，重新解压
foreach ($asset in @(
    'TruFor\TruFor_train_test\pretrained_models\trufor.pth.tar',
    'web\dist\index.html',
    'deploy\baseline\normal_55_237.jpg',
    'deploy\baseline\tiled_check.jpg',
    'requirements.txt')) {
    if (-not (Test-Path (Join-Path $Root $asset))) {
        Stop-Deploy $S '随包资产' "缺少 $asset —— zip 未解压完整，请重新解压后重跑"
    }
}
Add-Result $S '随包资产' 'OK' '模型权重/前端产物/基线图齐全'

# 网络：装依赖需要出网；VLM 是警告级（不通则自动降级为仅像素取证）
if (-not (Test-Tcp 'pypi.tuna.tsinghua.edu.cn' 443)) {
    Add-Result $S 'pip 源连通' 'WARN' '清华源不可达，若依赖已装好可忽略，否则阶段 2 会失败'
} else { Add-Result $S 'pip 源连通' 'OK' 'pypi.tuna.tsinghua.edu.cn' }
if (-not (Test-Tcp 'download.pytorch.org' 443)) {
    Add-Result $S 'PyTorch 源连通' 'WARN' '官方源不可达，将尝试阿里云镜像'
} else { Add-Result $S 'PyTorch 源连通' 'OK' 'download.pytorch.org' }
$vlmHost = 'llm-grvsxc3jcll56h4b.cn-beijing.maas.aliyuncs.com'
if (Test-Tcp $vlmHost 443) {
    Add-Result $S 'VLM 端点连通' 'OK' $vlmHost
} else {
    Add-Result $S 'VLM 端点连通' 'WARN' ('DashScope 不可达（公司内网限制？）。' +
        '系统将自动降级为仅像素取证；接入公司内部模型服务为后续待办')
}

# 端口 8000：被本服务占用是正常（重跑），被别人占用要提示
$portUser = $null
try { $portUser = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 } catch {}
if ($portUser) {
    $procName = (Get-Process -Id $portUser.OwningProcess -ErrorAction SilentlyContinue).ProcessName
    if ($procName -eq 'python') { Add-Result $S '端口 8000' 'OK' '已被 DocGuard 服务占用（重跑场景，稍后重启服务）' }
    else { Add-Result $S '端口 8000' 'WARN' "被进程 [$procName] 占用，注册服务后可能启动失败" }
} else { Add-Result $S '端口 8000' 'OK' '空闲' }

# Python 3.12：没有则 winget 自动装
$sysPy = Get-SystemPython
if (-not $sysPy) {
    Write-Host '未找到 Python 3.12，尝试 winget 自动安装（约 30MB）…'
    $wingetOk = $false
    try { & winget --version | Out-Null; $wingetOk = $true } catch {}
    if (-not $wingetOk) {
        Stop-Deploy $S 'Python 3.12' ('本机无 Python 3.12 且无 winget。请到 python.org 下载 3.12 安装包，' +
            '安装时勾选 "Add python.exe to PATH"，装完重跑 deploy.bat')
    }
    & winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    # 刷新本进程 PATH（安装器写的是注册表，当前会话感知不到）
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
    $sysPy = Get-SystemPython
    if (-not $sysPy) { Stop-Deploy $S 'Python 3.12' 'winget 安装后仍找不到，请手动安装 python.org 3.12 后重跑' }
}
Add-Result $S 'Python 3.12' 'OK' ("{0} {1}" -f $sysPy.Exe, ($sysPy.Pre -join ' '))

# .env：首次运行提示输入 key（密钥不随包裸奔）；留空=仅像素取证模式
$envFile = Join-Path $Root '.env'
if (-not (Test-Path $envFile)) {
    Write-Host ''
    Write-Host '首次部署：请输入 DASHSCOPE_API_KEY（大模型复核用）。' -ForegroundColor Cyan
    Write-Host '公司内网若无法访问 DashScope 可直接回车留空，系统将以仅像素取证模式运行。'
    $key = Read-Host 'DASHSCOPE_API_KEY'
    Set-Content -Path $envFile -Value "DASHSCOPE_API_KEY=$key" -Encoding ascii
    if ($key) { Add-Result $S '.env 配置' 'OK' 'API key 已写入' }
    else { Add-Result $S '.env 配置' 'WARN' '未配置 key，仅像素取证模式' }
} else { Add-Result $S '.env 配置' 'OK' '已存在，不覆盖' }

# ═══ 阶段 2/4：安装依赖 ══════════════════════════════════════════════════
Write-Host "`n═══ 阶段 2/4：安装依赖 ═══" -ForegroundColor Cyan
$S = '2-安装依赖'
$Mirror = 'https://pypi.tuna.tsinghua.edu.cn/simple'

# 幂等探针：核心依赖全部可导入且 CUDA 可用 → 整段跳过
$ready = $false
if (Test-Path $VenvPy) {
    & $VenvPy -c "import torch, fastapi, dashscope, timm, pillow_heif; import sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $ready = $true }
}
if ($ready) {
    Add-Result $S '依赖安装' 'OK' '已就绪（幂等探针通过），跳过安装'
} else {
    if (-not (Test-Path $VenvPy)) {
        Write-Host '创建虚拟环境 .venv …'
        & $sysPy.Exe @($sysPy.Pre) -m venv (Join-Path $Root '.venv')
        if ($LASTEXITCODE -ne 0) { Stop-Deploy $S '创建 venv' '失败，检查 Python 安装' }
    }
    & $VenvPy -m pip install --upgrade pip -i $Mirror --quiet
    Add-Result $S 'pip 升级' 'OK' ''

    # torch 必须先装 CUDA 版：requirements.txt 钉的 torch==2.12.1 在 PyPI 上是 CPU 轮子。
    # 先装 +cu 版后，pip 会认为 ==2.12.1 已满足（PEP 440 忽略本地版本段），不会覆盖。
    Write-Host '安装 CUDA 版 PyTorch（约 2.5GB，视网速 5-20 分钟）…'
    $torchOk = $false
    $torchSrc = @(
        @{ Kind = 'index'; Url = 'https://download.pytorch.org/whl/cu128' },
        @{ Kind = 'index'; Url = 'https://download.pytorch.org/whl/cu126' },
        @{ Kind = 'links'; Url = 'https://mirrors.aliyun.com/pytorch-wheels/cu128/' }
    )
    foreach ($src in $torchSrc) {
        Write-Host ("  尝试源: {0}" -f $src.Url)
        if ($src.Kind -eq 'index') {
            & $VenvPy -m pip install "torch==2.12.1" "torchvision==0.27.1" --index-url $src.Url
        } else {
            & $VenvPy -m pip install "torch==2.12.1" "torchvision==0.27.1" -f $src.Url
        }
        if ($LASTEXITCODE -eq 0) { $torchOk = $true; break }
    }
    if (-not $torchOk) { Stop-Deploy $S 'CUDA torch' '三个源均失败。确认能访问 download.pytorch.org 或联系我们改用离线 wheel 包' }
    Add-Result $S 'CUDA torch' 'OK' '2.12.1 + torchvision 0.27.1'

    & $VenvPy -m pip install -r (Join-Path $Root 'requirements.txt') -i $Mirror
    if ($LASTEXITCODE -ne 0) { Stop-Deploy $S 'requirements' 'pip 安装失败，见上方报错' }
    Add-Result $S 'requirements' 'OK' ''
}

# CUDA 终验：这里失败=装成 CPU 版，后面全白搭，必须硬停
$gpuName = & $VenvPy -c "import torch; print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-CUDA')"
if ($LASTEXITCODE -ne 0 -or "$gpuName" -match 'NO-CUDA') {
    Stop-Deploy $S 'CUDA 验证' 'torch.cuda.is_available()=False（装成 CPU 版？驱动过旧？），部署中止'
}
$torchVer = & $VenvPy -c "import torch; print(torch.__version__)"
Add-Result $S 'CUDA 验证' 'OK' "torch $torchVer / $gpuName"

# ═══ 阶段 3/4：运行测试 ══════════════════════════════════════════════════
Write-Host "`n═══ 阶段 3/4：运行测试 ═══" -ForegroundColor Cyan
$S = '3-运行测试'

# 单元/集成测试：VLM 已 mock，不出网不耗 GPU，秒级
$pytestOut = & $VenvPy -m pytest (Join-Path $Root 'tests') -q 2>&1
$pytestTail = ($pytestOut | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0) {
    Write-Host ($pytestOut -join "`n")
    Stop-Deploy $S 'pytest' "测试未通过（$pytestTail），环境有问题，不部署"
}
Add-Result $S 'pytest' 'OK' "$pytestTail"

# 基线回归：CUDA 分数须与 Mac 基线在容差内（首次加载模型+大图切片，约 1-3 分钟）
Write-Host '基线回归中（含 3456x4608 大图切片推理，请稍候）…'
$blOut = & $VenvPy (Join-Path $Root 'deploy\check_baseline.py') 2>&1
Write-Host ($blOut -join "`n")
$blDetail = (($blOut | Where-Object { $_ -match '^(OK|WARN|FAIL)' }) -join ' ; ')
if ($LASTEXITCODE -eq 2) { Stop-Deploy $S '基线回归' "跑不起来：$blDetail" }
elseif ($LASTEXITCODE -eq 1) { Add-Result $S '基线回归' 'WARN' "超容差，请把报告发回项目组确认：$blDetail" }
else { Add-Result $S '基线回归' 'OK' $blDetail }

# VLM 冒烟：不通不阻塞（自动降级为仅像素取证）
$vlmOut = & $VenvPy (Join-Path $Root 'deploy\check_vlm.py') 2>&1
if ($LASTEXITCODE -eq 0) { Add-Result $S 'VLM 冒烟' 'OK' (($vlmOut | Select-Object -Last 1)) }
else { Add-Result $S 'VLM 冒烟' 'WARN' ('不通，Agent/快速复核将自动降级为仅像素取证。' + ($vlmOut | Select-Object -Last 1)) }

# ═══ 阶段 4/4：部署服务 + 状态报告 ═══════════════════════════════════════
Write-Host "`n═══ 阶段 4/4：部署服务 ═══" -ForegroundColor Cyan
$S = '4-部署服务'

# 防火墙：允许局域网同事访问
$fwRule = & netsh advfirewall firewall show rule name="DocGuard-8000" 2>&1
if ("$fwRule" -match 'DocGuard-8000') {
    Add-Result $S '防火墙' 'OK' '规则已存在'
} else {
    & netsh advfirewall firewall add rule name="DocGuard-8000" dir=in action=allow protocol=TCP localport=8000 | Out-Null
    Add-Result $S '防火墙' 'OK' '已放行 TCP 8000（局域网可访问）'
}

# NSSM 注册 Windows 服务：开机自启 + 崩溃自动拉起
New-Item -ItemType Directory -Force -Path (Join-Path $Root 'logs') | Out-Null
$svc = Get-Service -Name 'DocGuard' -ErrorAction SilentlyContinue
if ($svc) {
    & $Nssm stop DocGuard 2>&1 | Out-Null
    Add-Result $S '服务注册' 'OK' '服务已存在，更新配置后重启'
} else {
    & $Nssm install DocGuard $VenvPy '-u' '-m' 'uvicorn' 'api:app' '--host' '0.0.0.0' '--port' '8000'
    if ($LASTEXITCODE -ne 0) { Stop-Deploy $S '服务注册' 'nssm install 失败' }
    Add-Result $S '服务注册' 'OK' '已注册为 Windows 服务 DocGuard'
}
& $Nssm set DocGuard AppDirectory $Root | Out-Null
& $Nssm set DocGuard AppEnvironmentExtra 'PYTHONUTF8=1' | Out-Null
& $Nssm set DocGuard AppStdout (Join-Path $Root 'logs\docguard.log') | Out-Null
& $Nssm set DocGuard AppStderr (Join-Path $Root 'logs\docguard.err.log') | Out-Null
& $Nssm set DocGuard AppRotateFiles 1 | Out-Null
& $Nssm set DocGuard AppRotateBytes 10485760 | Out-Null
& $Nssm set DocGuard Start SERVICE_AUTO_START | Out-Null
& $Nssm set DocGuard AppExit Default Restart | Out-Null
& $Nssm set DocGuard AppRestartDelay 5000 | Out-Null
& $Nssm start DocGuard 2>&1 | Out-Null

# 健康检查：等模型预热（首次含 CUDA 内核编译，给足 180 秒）
Write-Host '等待服务启动与模型预热…'
$healthy = $false
foreach ($i in 1..90) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $healthy = $true; break }
    } catch {}
}
if (-not $healthy) {
    Stop-Deploy $S '健康检查' '180 秒内未就绪，查看 logs\docguard.err.log 并把 deploy-report.txt 发回项目组'
}
Add-Result $S '健康检查' 'OK' ('http://127.0.0.1:8000/ 就绪（等待 {0} 秒）' -f ($i * 2))

# 冒烟检测：真实过一遍检测链路（仅像素取证，不耗 VLM 费用）
$curl = Join-Path $env:SystemRoot 'System32\curl.exe'
$smokeT0 = Get-Date
$resp = & $curl -s -N --max-time 180 -F 'file=@deploy/baseline/normal_55_237.jpg' -F 'mode=cv' 'http://127.0.0.1:8000/api/detect'
$smokeSec = [math]::Round(((Get-Date) - $smokeT0).TotalSeconds, 1)
if ("$resp" -match '"score":\s*([0-9.]+)') {
    Add-Result $S '冒烟检测' 'OK' ('score={0} 耗时 {1}s（Mac 基线 0.1138 / 3.2s）' -f $Matches[1], $smokeSec)
} else {
    Add-Result $S '冒烟检测' 'FAIL' '未拿到检测结果，查看 logs\docguard.err.log'
}

$DeployOk = $true

} catch {
    Write-Host "`n部署中断：$_" -ForegroundColor Red
} finally {
    # ── 状态报告：无论成败都落盘，发回项目组即可远程判断 ──────────────
    $lanIp = ''
    try {
        $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
            Select-Object -First 1).IPAddress
    } catch {}
    $elapsed = [math]::Round(((Get-Date) - $StartTime).TotalMinutes, 1)
    $lines = @()
    $lines += '════════ DocGuard 部署状态报告 ════════'
    $lines += ('时间: {0}    机器: {1}    总耗时: {2} 分钟' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $env:COMPUTERNAME, $elapsed)
    $lines += ('GPU: {0}' -f $Script:GpuInfo)
    $lines += ('结果: {0}' -f $(if ($DeployOk) { '部署成功' } else { '部署失败（见下表 FAIL 行）' }))
    $lines += ''
    foreach ($r in $Results) { $lines += ('[{0,-4}] {1} | {2}  {3}' -f $r.Status, $r.Stage, $r.Name, $r.Detail) }
    $lines += ''
    if ($DeployOk) {
        $lines += ('访问地址: http://localhost:8000    局域网: http://{0}:8000' -f $lanIp)
        $lines += '服务名: DocGuard（开机自启，崩溃自动拉起；重启命令: deploy\nssm.exe restart DocGuard）'
        $lines += '日志: logs\docguard.log / logs\docguard.err.log'
    }
    $lines += '请把本文件（deploy-report.txt）通过丰声发回项目组。'
    $lines | Out-File -FilePath $ReportFile -Encoding utf8
    Write-Host ''
    Write-Host ('报告已写入: {0}' -f $ReportFile) -ForegroundColor Cyan
    if ($DeployOk) {
        Write-Host ('部署成功！浏览器打开 http://localhost:8000 即可使用；局域网访问 http://{0}:8000' -f $lanIp) -ForegroundColor Green
    } else {
        Write-Host '部署未完成。请把 deploy-report.txt 发回项目组，修复后重新双击 deploy.bat 可断点续跑。' -ForegroundColor Yellow
    }
    Read-Host '按回车键退出'
}
