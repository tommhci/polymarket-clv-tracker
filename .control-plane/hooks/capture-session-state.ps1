param(
  [string]$SessionId = "",
  [ValidateSet("product", "governance", "personal", "analytical", "unknown")]
  [string]$Domain = "unknown",
  [string]$ActiveNode = "",
  [ValidateSet("verified_now", "historical", "unknown", "waived_by_user")]
  [string]$ActiveNodeStatus = "unknown",
  [ValidateSet("verified_now", "historical", "not_run", "failed", "unknown", "waived_by_user")]
  [string]$TestsStatus = "not_run",
  [string]$TestsCommand = "",
  [string]$TestsResult = "",
  [string]$Summary = "",
  [string]$OutputPath = ".agents/session_log.jsonl"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$controlPlaneDir = Split-Path -Parent $scriptDir
$repoRoot = (Resolve-Path (Join-Path $controlPlaneDir "..")).Path
$resolver = Join-Path $controlPlaneDir "resolve-control-plane.ps1"
$controlPlaneRepo = & $resolver -RepoRoot $repoRoot -AdapterDir ".control-plane"
$target = Join-Path $controlPlaneRepo "state/capture_session_state.ps1"

if (-not (Test-Path -LiteralPath $target)) {
  throw "Missing control-plane capture script: $target"
}

& $target `
  -SessionId $SessionId `
  -Domain $Domain `
  -ActiveNode $ActiveNode `
  -ActiveNodeStatus $ActiveNodeStatus `
  -TestsStatus $TestsStatus `
  -TestsCommand $TestsCommand `
  -TestsResult $TestsResult `
  -Summary $Summary `
  -OutputPath $OutputPath
