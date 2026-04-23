# =====================================================================
# build-slim.ps1 - build the slim ARMv7 image (v0.11.0-slim)
#
# Uses thermal/Dockerfile.slim for a smaller footprint on storage-constrained
# Nucleus devices. Output: dist\thermal-analyzer-armv7-slim.tar.gz (~100 MB)
#
# Usage:
#   powershell .\build-slim.ps1
#   powershell .\build-slim.ps1 -Tag v0.11.0-slim -Release JuanM2209/thermal-tank-poc
# =====================================================================
param(
    [string]$Tag = "v0.11.0-slim",
    [string]$ImageName = "thermal-analyzer",
    [string]$Release = ""
)

$ErrorActionPreference = "Continue"

function Fail($msg) { Write-Host $msg -ForegroundColor Red; exit 1 }

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "=== 1. Verify Docker Desktop ===" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop not reachable" }

Write-Host "=== 2. Ensure buildx builder ===" -ForegroundColor Cyan
$null = docker buildx inspect nucleusbuilder 2>&1
if ($LASTEXITCODE -ne 0) {
    docker buildx create --name nucleusbuilder --use | Out-Null
    if ($LASTEXITCODE -ne 0) { Fail "buildx create failed" }
} else {
    docker buildx use nucleusbuilder | Out-Null
}
docker buildx inspect --bootstrap | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "buildx bootstrap failed" }

Write-Host "=== 3. Build SLIM linux/arm/v7 ===" -ForegroundColor Cyan
$img = "${ImageName}:armv7-slim"
docker buildx build `
    --platform linux/arm/v7 `
    --file "$root\thermal\Dockerfile.slim" `
    --tag $img `
    --load `
    "$root\thermal"
if ($LASTEXITCODE -ne 0) { Fail "docker buildx build failed" }

# Also tag as plain :armv7 so the install script picks it up unchanged
docker tag $img "${ImageName}:armv7"

Write-Host "=== 4. Export + gzip ===" -ForegroundColor Cyan
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$tar = Join-Path $dist "thermal-analyzer-armv7.tar"
$gz  = "$tar.gz"

if (Test-Path $tar) { Remove-Item $tar -Force }
if (Test-Path $gz)  { Remove-Item $gz  -Force }

docker save "${ImageName}:armv7" -o $tar
if ($LASTEXITCODE -ne 0) { Fail "docker save failed" }

$inStream  = [System.IO.File]::OpenRead($tar)
$outStream = [System.IO.File]::Create($gz)
$gzStream  = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
$inStream.CopyTo($gzStream)
$gzStream.Close(); $outStream.Close(); $inStream.Close()
Remove-Item $tar -Force

$size = (Get-Item $gz).Length
Write-Host ("   -> {0}  ({1:N1} MB compressed)" -f $gz, ($size/1MB)) -ForegroundColor Green

$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    $null = gh --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "gh CLI not installed" }
    gh release create $Tag --repo $Release --title "Thermal Analyzer $Tag (slim)" `
        --notes "Slim ARMv7 image for storage-constrained Nucleus (~100 MB compressed, ~250 MB decompressed). Same features as v0.10.0." `
        "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { Fail "gh release failed" }
    Write-Host "Release URL: https://github.com/$Release/releases/tag/$Tag" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step - create the release manually:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo JuanM2209/thermal-tank-poc --title 'Thermal Analyzer $Tag (slim)' $gz dist\SHA256SUM"
}
