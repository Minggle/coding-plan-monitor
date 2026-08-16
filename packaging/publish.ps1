# 一键发布：推送代码并创建 GitHub Release（需先完成 gh auth login）
# 用法：powershell -ExecutionPolicy Bypass -File packaging\publish.ps1 -Tag v0.2.0
param(
    [Parameter(Mandatory = $true)]
    [string]$Tag,
    [string]$Setup = '',
    [string]$Notes = ''
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Resolve-Path "$PSScriptRoot\.."
$Version  = $Tag.TrimStart('v')
if (-not $Setup) { $Setup = Join-Path $RepoRoot "installer\CodingPlanMonitor-Setup-$Version.exe" }
if (-not $Notes) { $Notes = Join-Path $RepoRoot "packaging\release-notes-$Tag.md" }

gh auth status
git -C $RepoRoot push -u origin main
git -C $RepoRoot push origin $Tag

if ((Test-Path $Setup) -and (Test-Path $Notes)) {
    gh release create $Tag $Setup --title $Tag --notes-file $Notes
} elseif (Test-Path $Setup) {
    gh release create $Tag $Setup --title $Tag --generate-notes
} else {
    gh release create $Tag --title $Tag --generate-notes
}
Write-Output "发布完成：$Tag"