$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$candidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'),
    (Join-Path $env:USERPROFILE 'miniconda3\envs\desktop-ai\pythonw.exe'),
    (Join-Path $env:USERPROFILE 'anaconda3\envs\desktop-ai\pythonw.exe')
)
$agentPython = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $agentPython) { throw 'Cannot find desktop-ai Python. Create the environment before launching.' }
if (-not $env:DEEPSEEK_API_KEY) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
}
if (-not $env:DEEPSEEK_API_KEY) { throw 'DEEPSEEK_API_KEY is missing. Set the user environment variable first.' }
Start-Process -FilePath $agentPython -ArgumentList ('"' + (Join-Path $PSScriptRoot 'desktop_app.py') + '"') -WorkingDirectory $PSScriptRoot
