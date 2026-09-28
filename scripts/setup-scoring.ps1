$ErrorActionPreference = "Stop"
$scoringRoot = Split-Path -Parent $PSScriptRoot
$scoringPython = Join-Path $scoringRoot ".runtime/python-auto-venv/Scripts/python.exe"
$scoringEnvironment = Join-Path $scoringRoot ".runtime/scoring-venv"
$scoringWheel = Join-Path $scoringRoot ".runtime/mahjong-2.0.0-py3-none-any.whl"
if (-not (Test-Path -LiteralPath $scoringPython)) { throw "Run operator:setup first." }
Invoke-WebRequest -Uri "https://files.pythonhosted.org/packages/30/02/687973dca9ab7372a8db48752fd3350a6b9c36b7807efdeb55e1ebf3779c/mahjong-2.0.0-py3-none-any.whl" -OutFile $scoringWheel
if ((Get-FileHash -LiteralPath $scoringWheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne "52f63a8dfda5a9e81542642ed315f0e1e8626c0d324c8d8eabb3418ae7d43870") { throw "Scoring wheel hash mismatch." }
& $scoringPython -m venv $scoringEnvironment
if ($LASTEXITCODE -ne 0) { throw "Scoring environment creation failed." }
& (Join-Path $scoringEnvironment "Scripts/python.exe") -m pip install --no-index --no-deps $scoringWheel
if ($LASTEXITCODE -ne 0) { throw "Scoring package installation failed." }
