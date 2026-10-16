# Creates a portable ZIP archive from the built dist folder
# Run after build_exe.ps1

param(
    [string]$Version = "1.0.0"
)

$ErrorActionPreference = "Stop"

$DistFolder = "dist\FFmpegConverter"
$ZipPath = "dist\FFmpegConverter-Portable-v$Version.zip"

if (-not (Test-Path $DistFolder)) {
    throw "Build folder not found: $DistFolder. Run build_exe.ps1 first."
}

Write-Host "Creating portable ZIP archive..."

# Remove old ZIP if it exists
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

# Create ZIP
Compress-Archive -Path "$DistFolder\*" -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host "Created: $ZipPath"
Write-Host "Size: $([math]::Round((Get-Item $ZipPath).Length / 1MB, 2)) MB"
