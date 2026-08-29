param(
  [string]$RepoRoot = ".",
  [string]$AdapterDir = ".control-plane"
)

$ErrorActionPreference = "Stop"

$resolvedRepoRoot = (Resolve-Path $RepoRoot).Path
$resolvedAdapterDir = Join-Path $resolvedRepoRoot $AdapterDir
$pointerPath = Join-Path $resolvedAdapterDir "control-plane-root.txt"
$adapterPath = Join-Path $resolvedAdapterDir "adapter.json"

$candidates = @()

if (-not [string]::IsNullOrWhiteSpace($env:AI_CONTROL_PLANE_ROOT)) {
  $candidates += $env:AI_CONTROL_PLANE_ROOT
}

if (Test-Path -LiteralPath $pointerPath) {
  $pointerValue = (Get-Content -LiteralPath $pointerPath -Raw).Trim()
  if (-not [string]::IsNullOrWhiteSpace($pointerValue)) {
    $candidates += $pointerValue
  }
}

if (Test-Path -LiteralPath $adapterPath) {
  $adapter = Get-Content -LiteralPath $adapterPath -Raw | ConvertFrom-Json
  if (-not [string]::IsNullOrWhiteSpace($adapter.controlPlaneRepo)) {
    $candidates += $adapter.controlPlaneRepo
  }
}

foreach ($candidate in $candidates) {
  $path = $candidate.Trim()
  if (-not [System.IO.Path]::IsPathRooted($path)) {
    $path = Join-Path $resolvedRepoRoot $path
  }

  if (Test-Path -LiteralPath $path) {
    Write-Output (Resolve-Path -LiteralPath $path).Path
    exit 0
  }
}

throw "Unable to resolve control-plane root. Set AI_CONTROL_PLANE_ROOT, .control-plane/control-plane-root.txt, or adapter.json controlPlaneRepo."
