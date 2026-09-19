$utf8 = New-Object System.Text.UTF8Encoding $false
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
chcp 65001 > $null
if (-not $env:DEEPSEEK_API_KEY) {
    throw "请先设置 DEEPSEEK_API_KEY 环境变量"
}
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Get-Command conda -ErrorAction SilentlyContinue) {
    conda activate desktop-ai
}
python main.py run "我要看复仇者联盟" --yes
