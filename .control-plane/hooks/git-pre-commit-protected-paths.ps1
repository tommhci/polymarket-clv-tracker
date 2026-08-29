param(
  [string]$ProtectedPathsFile = ".control-plane/protected-paths.json"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$controlPlaneDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $controlPlaneDir "..")).Path
$resolver = Join-Path $controlPlaneDir "resolve-control-plane.ps1"
$controlPlaneRepo = & $resolver -RepoRoot $repoRoot -AdapterDir ".control-plane"
$target = Join-Path $controlPlaneRepo "hooks/git/pre_commit_protected_paths.ps1"

if (-not (Test-Path -LiteralPath $target)) {
  throw "Missing control-plane git pre-commit script: $target"
}

& $target -RepoRoot $repoRoot -ProtectedPathsFile $ProtectedPathsFile
exit $LASTEXITCODE
