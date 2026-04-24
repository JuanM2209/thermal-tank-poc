# =====================================================================
# build-nano.ps1 -- build the NANO ARMv7 image (v0.13.0-nano)
#
# Uses thermal/Dockerfile.nano: alpine 3.19 base + custom source-built
# opencv (core+imgproc+imgcodecs+videoio only) + alpine-native numpy.
#
# Target: ~90-100 MB uncompressed  /  ~35-45 MB compressed.
# For Nucleus devices where /data has less than 200 MB truly free after
# existing containers (Node-RED, remote-support) are in place.
#
# Output: dist\thermal-analyzer-armv7.tar.gz
#
# Usage:
#   powershell .\build-nano.ps1
#   powershell .\build-nano.ps1 -Tag v0.13.0-nano -Release JuanM2209/thermal-tank-poc
# =====================================================================
param(
    [string]$Tag = "v0.13.0-nano",
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

Write-Host "=== 3. Build NANO linux/arm/v7 (alpine + custom opencv) ===" -ForegroundColor Cyan
Write-Host "    Expect 40-60 min under QEMU emulation (opencv source compile)." -ForegroundColor DarkGray
$img = "${ImageName}:armv7-nano"
docker buildx build `
    --platform linux/arm/v7 `
    --file "$root\thermal\Dockerfile.nano" `
    --tag $img `
    --load `
    "$root\thermal"
if ($LASTEXITCODE -ne 0) { Fail "docker buildx build failed" }

# Retag as plain :armv7 so the install script picks it up unchanged
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

$rawSize = (Get-Item $tar).Length
Write-Host ("   -> uncompressed: {0:N1} MB" -f ($rawSize/1MB)) -ForegroundColor DarkGray

$inStream  = [System.IO.File]::OpenRead($tar)
$outStream = [System.IO.File]::Create($gz)
$gzStream  = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
$inStream.CopyTo($gzStream)
$gzStream.Close(); $outStream.Close(); $inStream.Close()
Remove-Item $tar -Force

$size = (Get-Item $gz).Length
Write-Host ("   -> {0}  ({1:N1} MB compressed)" -f $gz, ($size/1MB)) -ForegroundColor Green

# Sanity gate: if the image came out bigger than the slim (v0.11) it means
# something in the pipeline silently regressed -- stop before publishing.
$maxMB = 80
if (($size / 1MB) -gt $maxMB) {
    Fail "Compressed image is $([math]::Round($size/1MB,1)) MB - exceeds $maxMB MB nano budget. Review Dockerfile.nano before releasing."
}

$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    $null = gh --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "gh CLI not installed" }
    $notes = Join-Path $root "dist\release-notes-v0.13.0-nano.md"
    $notesArg = if (Test-Path $notes) { @("--notes-file", $notes) } else { @("--notes", "Nano ARMv7 image for severely storage-constrained Nucleus. Same features as v0.11.0-slim.") }
    gh release create $Tag --repo $Release --title "Thermal Analyzer $Tag (nano)" @notesArg "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { Fail "gh release failed" }
    Write-Host "Release URL: https://github.com/$Release/releases/tag/$Tag" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step - create the release manually:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo JuanM2209/thermal-tank-poc --title 'Thermal Analyzer $Tag (nano)' --notes-file dist\release-notes-v0.13.0-nano.md $gz dist\SHA256SUM"
}
