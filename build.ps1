# =====================================================================
# build.ps1 - build + package thermal-analyzer for ARMv7 (Nucleus)
#
# Windows PowerShell 5.1 compatible.
#
# Produces:   dist\thermal-analyzer-armv7.tar.gz (ready for GitHub release)
# Usage:
#   powershell .\build.ps1
#   powershell .\build.ps1 -Tag v0.2.0
#   powershell .\build.ps1 -Tag v0.2.0 -Release JuanM2209/thermal-tank-poc
# =====================================================================
param(
    [string]$Tag = "v0.6.0",
    [string]$ImageName = "thermal-analyzer",
    [string]$Release = ""
)

# NB: we intentionally do NOT set $ErrorActionPreference='Stop' because on
# Windows PowerShell 5.1, native executables that print to stderr (docker,
# gh, etc.) raise NativeCommandError and derail the script even on exit 0.
# Instead we check $LASTEXITCODE explicitly after each native call.
$ErrorActionPreference = "Continue"

function Fail($msg) { Write-Host $msg -ForegroundColor Red; exit 1 }
function Exec([string]$display, [scriptblock]$block) {
    Write-Host $display -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { Fail "FAILED: $display (exit $LASTEXITCODE)" }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "=== 1. Verify Docker Desktop ===" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop not reachable" }

Write-Host "=== 2. Ensure buildx builder with QEMU ARMv7 ===" -ForegroundColor Cyan
# Capture stdout only so stderr does not become a terminating error on PS 5.1.
$null = docker buildx inspect nucleusbuilder 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "   creating nucleusbuilder..." -ForegroundColor DarkGray
    docker buildx create --name nucleusbuilder --use | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "buildx create failed" }
} else {
    docker buildx use nucleusbuilder | Out-Null
}
docker buildx inspect --bootstrap | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "buildx bootstrap failed" }

Write-Host "=== 3. Build linux/arm/v7 ===" -ForegroundColor Cyan
$img = "${ImageName}:armv7"
docker buildx build --platform linux/arm/v7 --tag $img --load "$root\thermal"
if ($LASTEXITCODE -ne 0) { Fail "docker buildx build failed" }

Write-Host "=== 4. Export + gzip ===" -ForegroundColor Cyan
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$tar = Join-Path $dist "thermal-analyzer-armv7.tar"
$gz  = "$tar.gz"

if (Test-Path $tar) { Remove-Item $tar -Force }
if (Test-Path $gz)  { Remove-Item $gz  -Force }

docker save $img -o $tar
if ($LASTEXITCODE -ne 0) { Fail "docker save failed" }

# Gzip using .NET (no gzip.exe dependency)
$inStream  = [System.IO.File]::OpenRead($tar)
$outStream = [System.IO.File]::Create($gz)
$gzStream  = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
$inStream.CopyTo($gzStream)
$gzStream.Close(); $outStream.Close(); $inStream.Close()
Remove-Item $tar -Force

$size = (Get-Item $gz).Length
Write-Host ("   -> {0}  ({1:N1} MB)" -f $gz, ($size/1MB)) -ForegroundColor Green

$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    $null = gh --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "gh CLI not installed - skip with -Release '' or run manually" }
    gh release create $Tag --repo $Release --title "Thermal Analyzer $Tag" --notes "ARMv7 Docker image for Nucleus" "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { Fail "gh release failed" }
    Write-Host "Release created. Asset URL:"
    Write-Host "  https://github.com/$Release/releases/download/$Tag/thermal-analyzer-armv7.tar.gz" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step - upload the .tar.gz to a GitHub release:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo USER/REPO --title 'Thermal Analyzer $Tag' $gz dist\SHA256SUM"
}
