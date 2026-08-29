param(
  [string]$Tool = "claude-code",
  [string]$Files = "",
  [string]$Purpose = "",
  [string]$ReleaseCondition = "At session-close.",
  [string]$Outcome = "",
  [string]$OwnershipFile = ".agents/ACTIVE_EDIT_OWNERSHIP.md",
  [switch]$CheckOnly,
  [switch]$ReleaseOwnership
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$controlPlaneDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $controlPlaneDir "..")).Path
$resolver = Join-Path $controlPlaneDir "resolve-control-plane.ps1"
$controlPlaneRepo = & $resolver -RepoRoot $repoRoot -AdapterDir ".control-plane"
$target = Join-Path $controlPlaneRepo "state/claim_ownership.ps1"

if (-not (Test-Path -LiteralPath $target)) {
  throw "Missing control-plane ownership script: $target"
}

& $target `
  -Tool $Tool `
  -Files $Files `
  -Purpose $Purpose `
  -ReleaseCondition $ReleaseCondition `
  -Outcome $Outcome `
  -OwnershipFile $OwnershipFile `
  -RepoRoot $repoRoot `
  -CheckOnly:$CheckOnly `
  -ReleaseOwnership:$ReleaseOwnership
exit $LASTEXITCODE
