[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string] $Channel,

    [string] $OutputDirectory,
    [string] $Langs = 'en,ko',
    [string] $Since,
    [int] $Limit,
    [string] $TranslateTo,
    [double] $DelayMin = 0.5,
    [double] $DelayMax = 2.0,
    [switch] $Force,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $AdditionalArgs
)

$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
$venvPython = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPython) {
    $pythonPath = $venvPython
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
    $pythonPath = if ($python) { $python.Source } else { $null }
}
if (-not $pythonPath) { throw 'Python 3.10+ is required and must be on PATH.' }

$argsForRunner = @(
    (Join-Path $repoRoot 'run_research.py'),
    '--channel', $Channel,
    '--langs', $Langs,
    '--delay-min', $DelayMin.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--delay-max', $DelayMax.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($OutputDirectory) { $argsForRunner += @('--output', $OutputDirectory) }
if ($Limit -gt 0) { $argsForRunner += @('--limit', "$Limit") }
if ($Since) { $argsForRunner += @('--since', $Since) }
if ($TranslateTo) { $argsForRunner += @('--translate-to', $TranslateTo) }
if ($Force) { $argsForRunner += '--force' }
if ($AdditionalArgs) { $argsForRunner += $AdditionalArgs }

Push-Location $repoRoot
$previousLauncher = $env:YT_RESEARCH_LAUNCHER
$env:YT_RESEARCH_LAUNCHER = 'powershell'
try {
    if ($pythonPath -like '*\py.exe') {
        & $pythonPath -3 @argsForRunner
    } else {
        & $pythonPath @argsForRunner
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    if ($null -eq $previousLauncher) {
        Remove-Item Env:\YT_RESEARCH_LAUNCHER -ErrorAction SilentlyContinue
    } else {
        $env:YT_RESEARCH_LAUNCHER = $previousLauncher
    }
    Pop-Location
}
