# =====================================================================
# build-apk.ps1 -- build the APK ARMv7 image (v0.13.2-apk)
#
# Uses thermal/Dockerfile.apk: alpine 3.19 base + prebuilt py3-opencv
# from the alpine community repo (no source compile, no QEMU-heavy steps).
#
# Build time: ~2 minutes total (vs 40-60 min for Dockerfile.nano).
# Target:     ~70-90 MB uncompressed  /  ~30-35 MB compressed.
#
# Output: dist\thermal-analyzer-armv7.tar.gz
#   (SAME filename as build-nano.ps1 so install-on-nucleus.sh picks it up
#    unchanged -- installer just loads the tarball and retags as :armv7.)
#
# Usage:
#   powershell .\build-apk.ps1
#   powershell .\build-apk.ps1 -Tag v0.13.2-apk -Release JuanM2209/thermal-tank-poc
# =====================================================================
param(
    [string]$Tag = "v0.13.2-apk",
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

Write-Host "=== 3. Build APK linux/arm/v7 (alpine + prebuilt py3-opencv) ===" -ForegroundColor Cyan
Write-Host "    Expect ~2 min total (apk install only, no source compile)." -ForegroundColor DarkGray
$img = "${ImageName}:armv7-apk"
docker buildx build `
    --platform linux/arm/v7 `
    --file "$root\thermal\Dockerfile.apk" `
    --tag $img `
    --load `
    "$root\thermal"
if ($LASTEXITCODE -ne 0) { Fail "docker buildx build failed" }

# Retag as plain :armv7 so install-on-nucleus.sh picks it up unchanged.
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

# Sanity gate: apk path targets ~30-35 MB compressed. If it comes out fatter
# than 60 MB something regressed (e.g. apk pulled an unexpected heavyweight
# dep, or cleanup step silently failed). Stop before publishing.
$maxMB = 60
if (($size / 1MB) -gt $maxMB) {
    Fail "Compressed image is $([math]::Round($size/1MB,1)) MB - exceeds $maxMB MB apk budget. Review Dockerfile.apk before releasing."
}

$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    $null = gh --version 2>&1
    if ($LASTEXITCODE -ne 0) { Fail "gh CLI not installed" }
    $notes = Join-Path $root "dist\release-notes-v0.13.2-apk.md"
    $notesArg = if (Test-Path $notes) { @("--notes-file", $notes) } else { @("--notes", "APK ARMv7 image (Plan C): alpine py3-opencv prebuilt, no source compile. Same features as v0.13.0-nano, ~30x faster to build.") }
    gh release create $Tag --repo $Release --title "Thermal Analyzer $Tag (apk)" @notesArg "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { Fail "gh release failed" }
    Write-Host "Release URL: https://github.com/$Release/releases/tag/$Tag" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step - create the release manually:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo JuanM2209/thermal-tank-poc --title 'Thermal Analyzer $Tag (apk)' --notes-file dist\release-notes-v0.13.2-apk.md $gz dist\SHA256SUM"
}
