param(
  [string]$ProtectedPathsFile = ".control-plane/protected-paths.json"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$controlPlaneDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $controlPlaneDir "..")).Path
$resolver = Join-Path $controlPlaneDir "resolve-control-plane.ps1"
$controlPlaneRepo = & $resolver -RepoRoot $repoRoot -AdapterDir ".control-plane"
$target = Join-Path $controlPlaneRepo "hooks/claude-code/check_write_target.ps1"

# Anchor a relative ProtectedPathsFile to repoRoot so the guard works regardless
# of the caller's CWD (production hooks run from repo root; health checks may not).
if (-not [System.IO.Path]::IsPathRooted($ProtectedPathsFile)) {
  $ProtectedPathsFile = Join-Path $repoRoot $ProtectedPathsFile
}

if (-not (Test-Path -LiteralPath $target)) {
  throw "Missing control-plane write guard script: $target"
}

& $target -ProtectedPathsFile $ProtectedPathsFile
exit $LASTEXITCODE
