# One-time setup on Windows: finds (or installs) Python 3, creates .venv and installs the packages.
# Run from VS Code: Terminal > Run Task... > "1. Setup Python environment"
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
Write-Host "Project folder: $root"

function Test-Python($exe, $argsList) {
    try {
        $v = & $exe @argsList -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(1[0-9])$') { return $true }
    } catch { }
    return $false
}

$py = $null; $pyArgs = @()
foreach ($cand in @(@("py", @("-3.12")), @("py", @("-3.13")), @("py", @("-3.11")), @("py", @("-3")), @("python", @()))) {
    if (Test-Python $cand[0] $cand[1]) { $py = $cand[0]; $pyArgs = $cand[1]; break }
}
if (-not $py) {
    $local = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $local) { $py = $local }
}
if (-not $py) {
    Write-Host "No Python 3.10+ found - installing Python 3.12 with winget (needs internet)..."
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-source-agreements --accept-package-agreements
    $py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (-not (Test-Path $py)) { throw "Python install failed - install Python 3.12 from python.org and re-run this task." }
}
Write-Host "Using Python: $py $pyArgs"
& $py @pyArgs --version

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment .venv ..."
    & $py @pyArgs -m venv .venv
}
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -r requirements.txt
& $venvPy -c "import simpy, numpy, scipy, pandas, matplotlib, yaml; print('simpy', simpy.__version__, '| numpy', numpy.__version__, '| scipy', scipy.__version__, '| pandas', pandas.__version__, '| matplotlib', matplotlib.__version__)"

Write-Host ""
Write-Host "== Other tools =="
foreach ($t in @("git", "gh")) {
    $c = Get-Command $t -ErrorAction SilentlyContinue
    if ($c) { Write-Host "$t found: $($c.Source)"; & $t --version | Select-Object -First 1 } else { Write-Host "$t NOT found" }
}
Write-Host ""
Write-Host "SETUP DONE"
