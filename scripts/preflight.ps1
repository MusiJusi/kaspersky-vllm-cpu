[CmdletBinding()]
param(
    [switch]$CheckCluster
)

$ErrorActionPreference = 'Continue'
$taskFailures = 0

function Write-Check {
    param([string]$Status, [string]$Message)
    Write-Host ('[{0}] {1}' -f $Status, $Message)
}

Write-Host 'Checking local prerequisites for CPU inference on Kubernetes.'
Write-Host ('Logical processors visible to PowerShell: {0}' -f [Environment]::ProcessorCount)

foreach ($taskCommand in @('git', 'docker', 'kubectl')) {
    if (Get-Command $taskCommand -ErrorAction SilentlyContinue) {
        Write-Check 'OK' ($taskCommand + ' is installed.')
    } else {
        Write-Check 'FAIL' ($taskCommand + ' is not installed or is missing from PATH.')
        $taskFailures++
    }
}

if (Get-Command minikube -ErrorAction SilentlyContinue) {
    Write-Check 'OK' 'Minikube is installed.'
} else {
    Write-Check 'INFO' 'Minikube is unavailable. Install it for the planned local setup, or use an existing Kubernetes cluster.'
}

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $taskDockerOutput = @(docker info --format '{{json .}}' 2>&1)
    $taskDockerExit = $LASTEXITCODE
    if ($taskDockerExit -ne 0) {
        Write-Check 'FAIL' 'Docker Engine is unreachable. Check Docker Desktop, its selected context, and access permissions.'
        $taskDockerOutput | Where-Object { -not $_.ToString().TrimStart().StartsWith('{') } | ForEach-Object { Write-Host $_ }
        $taskFailures++
    } else {
        try {
            $taskDockerJson = $taskDockerOutput | Where-Object { $_ -is [string] -and $_.TrimStart().StartsWith('{') } | Select-Object -Last 1
            if (-not $taskDockerJson) { throw 'Docker did not return a JSON status.' }
            $taskDockerInfo = $taskDockerJson | ConvertFrom-Json -ErrorAction Stop
            if ($taskDockerInfo.OSType -ne 'linux') {
                Write-Check 'FAIL' 'Docker must use Linux containers for this project.'
                $taskFailures++
            } else {
                Write-Check 'OK' ('Linux Docker Engine {0}; CPUs: {1}; RAM: {2:N1} GiB.' -f $taskDockerInfo.ServerVersion, $taskDockerInfo.NCPU, ($taskDockerInfo.MemTotal / 1GB))
            }
        } catch {
            Write-Check 'FAIL' ('Cannot read Docker Engine status: ' + $_.Exception.Message)
            $taskFailures++
        }
    }
}

if ($CheckCluster -and (Get-Command kubectl -ErrorAction SilentlyContinue)) {
    $taskContextOutput = @(kubectl config current-context 2>&1)
    if ($LASTEXITCODE -ne 0) {
        Write-Check 'FAIL' 'No Kubernetes context is selected or the configuration cannot be read.'
        $taskFailures++
    } else {
        Write-Check 'INFO' ('Kubernetes context: ' + ($taskContextOutput -join ' '))
        $taskClusterOutput = @(kubectl cluster-info --request-timeout=10s 2>&1)
        if ($LASTEXITCODE -ne 0) {
            Write-Check 'FAIL' 'The selected Kubernetes API is unreachable.'
            $taskClusterOutput | ForEach-Object { Write-Host $_ }
            $taskFailures++
        } else {
            Write-Check 'OK' 'Kubernetes API is reachable.'
        }
    }
}

if ($taskFailures -gt 0) {
    Write-Check 'FAIL' ('Prerequisite checks failed: {0}.' -f $taskFailures)
    exit 1
}

Write-Check 'OK' 'Prerequisite checks passed. Model compatibility and inference still need a separate runtime check.'
exit 0
