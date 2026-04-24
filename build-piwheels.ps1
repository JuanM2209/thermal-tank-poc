# =====================================================================
# build-piwheels.ps1 -- build the PIWHEELS ARMv7 image (v0.13.1-piwheels)
#
# Uses thermal/Dockerfile.piwheels: python:3.11-slim-bookworm base +
# prebuilt opencv-python-headless / numpy wheels from piwheels.org.
#
# Target: ~220-260 MB uncompressed / ~80-100 MB compressed.
# Build time: ~2 min (no QEMU source compilation).
#
# This is the Plan B sibling of build-nano.ps1. The nano build is
# ~3x smaller on disk but takes 40-60 min to cross-compile opencv under
# QEMU ARMv7. Use this script when iterating on non-cv2 changes where
# build-speed matters more than image size.
#
# Output: dist\thermal-analyzer-armv7.tar.gz
#         (SAME filename as nano -- install-on-nucleus.sh unchanged)
#
# Usage:
#   powershell .\build-piwheels.ps1
#   powershell .\build-piwheels.ps1 -Tag v0.13.1-piwheels -Release JuanM2209/thermal-tank-poc
# =====================================================================
param(
    [string]$Tag = "v0.13.1-piwheels",
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

Write-Host "=== 3. Build PIWHEELS linux/arm/v7 (Debian + prebuilt wheels) ===" -ForegroundColor Cyan
Write-Host "    Expect ~2 min -- no source compilation, wheels only." -ForegroundColor DarkGray
$img = "${ImageName}:armv7-piwheels"
docker buildx build `
    --platform linux/arm/v7 `
    --file "$root\thermal\Dockerfile.piwheels" `
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

# Sanity gate: more lenient than nano's 80 MB cap because piwheels ships
# unstripped wheels with a larger cv2.so. 120 MB still fits the Nucleus
# 150 MB installer gate with room to spare.
$maxMB = 120
if (($size / 1MB) -gt $maxMB) {
    Fail "Compressed image is $([math]::Round($size/1MB,1)) MB - exceeds $maxMB MB piwheels budget. Review Dockerfile.piwheels before releasing."
}

$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    $null = gh --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "gh CLI not installed" }
    $notes = Join-Path $root "dist\release-notes-v0.13.1-piwheels.md"
    $notesArg = if (Test-Path $notes) { @("--notes-file", $notes) } else { @("--notes", "Piwheels ARMv7 image (Plan B): prebuilt opencv wheels, ~2 min build, ~80-100 MB compressed. Same features as v0.13.0-nano.") }
    gh release create $Tag --repo $Release --title "Thermal Analyzer $Tag (piwheels)" @notesArg "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { Fail "gh release failed" }
    Write-Host "Release URL: https://github.com/$Release/releases/tag/$Tag" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step - create the release manually:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo JuanM2209/thermal-tank-poc --title 'Thermal Analyzer $Tag (piwheels)' --notes-file dist\release-notes-v0.13.1-piwheels.md $gz dist\SHA256SUM"
}
