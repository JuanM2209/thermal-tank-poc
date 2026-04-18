# =====================================================================
# build.ps1 — build + package thermal-analyzer for ARMv7 (Nucleus)
#
# Run this on your Windows machine with Docker Desktop.
# Produces:   dist\thermal-analyzer-armv7.tar.gz   (~200 MB, ready to upload
#                                                    to a GitHub release)
# Usage:
#   pwsh .\build.ps1
#   pwsh .\build.ps1 -Tag v0.2.0           # change version
#   pwsh .\build.ps1 -Release user/repo    # also create GH release via `gh`
# =====================================================================
param(
    [string]$Tag = "v0.1.0",
    [string]$ImageName = "thermal-analyzer",
    [string]$Release = ""          # e.g. "juanmejia109/thermal-tank-poc"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "=== 1. Verify Docker Desktop ===" -ForegroundColor Cyan
docker version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Docker Desktop not reachable" }

Write-Host "=== 2. Ensure buildx builder with QEMU ARMv7 ===" -ForegroundColor Cyan
docker buildx inspect nucleusbuilder 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker buildx create --name nucleusbuilder --use | Out-Null
} else {
    docker buildx use nucleusbuilder | Out-Null
}
docker buildx inspect --bootstrap | Out-Null

Write-Host "=== 3. Build linux/arm/v7 ===" -ForegroundColor Cyan
$img = "${ImageName}:armv7"
docker buildx build `
    --platform linux/arm/v7 `
    --tag $img `
    --load `
    "$root\thermal"
if ($LASTEXITCODE -ne 0) { throw "Build failed" }

Write-Host "=== 4. Export + gzip ===" -ForegroundColor Cyan
$dist = Join-Path $root "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$tar = Join-Path $dist "thermal-analyzer-armv7.tar"
$gz  = "$tar.gz"

docker save $img -o $tar
if ($LASTEXITCODE -ne 0) { throw "Save failed" }

# Gzip using .NET (no gzip.exe dependency)
$inStream  = [System.IO.File]::OpenRead($tar)
$outStream = [System.IO.File]::Create($gz)
$gzStream  = New-Object System.IO.Compression.GZipStream($outStream, [System.IO.Compression.CompressionLevel]::Optimal)
$inStream.CopyTo($gzStream)
$gzStream.Close(); $outStream.Close(); $inStream.Close()
Remove-Item $tar

$size = (Get-Item $gz).Length
Write-Host ("   -> {0}  ({1:N1} MB)" -f $gz, ($size/1MB)) -ForegroundColor Green

# Checksum for the install command
$sha = (Get-FileHash $gz -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$dist\SHA256SUM" -Value "$sha  thermal-analyzer-armv7.tar.gz"
Write-Host "   SHA256: $sha" -ForegroundColor Green

if ($Release) {
    Write-Host "=== 5. Create GitHub release ===" -ForegroundColor Cyan
    gh --version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "gh CLI not installed — skip with -Release '' or run manually" }
    gh release create $Tag `
        --repo $Release `
        --title "Thermal Analyzer $Tag" `
        --notes "ARMv7 Docker image for Nucleus" `
        "$gz" "$dist\SHA256SUM"
    if ($LASTEXITCODE -ne 0) { throw "gh release failed" }
    Write-Host "Release created. Asset URL:"
    Write-Host "  https://github.com/$Release/releases/download/$Tag/thermal-analyzer-armv7.tar.gz" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "Next step — upload the .tar.gz to a GitHub release:" -ForegroundColor Yellow
    Write-Host "  gh release create $Tag --repo USER/REPO --title 'Thermal Analyzer $Tag' $gz dist\SHA256SUM"
    Write-Host "Or via the web UI: https://github.com/USER/REPO/releases/new"
}
