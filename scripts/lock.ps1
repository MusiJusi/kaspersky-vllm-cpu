[CmdletBinding()]
param([string]$Uv = 'uv')

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskProjectRoot
try {
    foreach ($taskInput in @('requirements.in', 'downloader/requirements.in')) {
        $taskOutput = $taskInput -replace '\.in$', '.txt'
        $taskArguments = @('pip', 'compile', $taskInput, '--python-version', '3.12', '--python-platform', 'x86_64-manylinux_2_34', '--generate-hashes', '--no-header', '--output-file', $taskOutput)
        if ($taskInput -eq 'requirements.in') { $taskArguments += @('--torch-backend', 'cpu') }
        & $Uv @taskArguments
        if ($LASTEXITCODE -ne 0) { throw ('Failed to lock ' + $taskInput) }
    }
} finally {
    Pop-Location
}
