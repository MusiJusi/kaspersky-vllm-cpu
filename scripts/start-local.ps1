[CmdletBinding()]
param(
    [switch]$SkipBuild,
    [string]$ClusterProfile = 'kaspersky-vllm-cpu',
    [int]$Cpus = 6,
    [int]$MemoryMB = 10240
)

$ErrorActionPreference = 'Stop'
$taskProjectRoot = Split-Path -Parent $PSScriptRoot
$taskMinikubeCommand = Get-Command minikube -ErrorAction SilentlyContinue
if ($taskMinikubeCommand) {
    $taskMinikube = $taskMinikubeCommand.Source
} else {
    $taskMinikube = Join-Path $taskProjectRoot '.local\bin\minikube.exe'
}
if (-not (Test-Path -LiteralPath $taskMinikube)) { throw 'Install Minikube or place minikube.exe in .local/bin/.' }

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('Command failed: ' + $Executable) }
}

Push-Location $taskProjectRoot
try {
    if (-not $SkipBuild) {
        Invoke-Checked 'docker' @('build', '--tag', 'kaspersky-model-downloader:dev', '--file', 'downloader/Dockerfile', '.')
        Invoke-Checked 'docker' @('build', '--tag', 'kaspersky-vllm-cpu:dev', '--file', 'Dockerfile', '.')
    }
    Invoke-Checked $taskMinikube @('start', '--profile', $ClusterProfile, '--driver=docker', '--keep-context', ('--cpus=' + $Cpus), ('--memory=' + $MemoryMB))
    Invoke-Checked $taskMinikube @('image', 'load', '--profile', $ClusterProfile, 'kaspersky-model-downloader:dev', 'kaspersky-vllm-cpu:dev')

    $taskNamespace = 'llm-inference'
    $taskNamespaceJson = @{ apiVersion = 'v1'; kind = 'Namespace'; metadata = @{ name = $taskNamespace } } | ConvertTo-Json -Depth 5
    $taskNamespaceJson | kubectl --context $ClusterProfile apply -f -
    if ($LASTEXITCODE -ne 0) { throw 'Namespace creation failed.' }

    New-Item -ItemType Directory -Force -Path .local | Out-Null
    $taskTokenPath = Join-Path $taskProjectRoot '.local\api-token'
    if (Test-Path -LiteralPath $taskTokenPath) {
        $taskApiToken = [System.IO.File]::ReadAllText($taskTokenPath).Trim()
    } else {
        $taskRandom = New-Object byte[] 32
        $taskGenerator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try { $taskGenerator.GetBytes($taskRandom) } finally { $taskGenerator.Dispose() }
        $taskApiToken = [Convert]::ToBase64String($taskRandom)
        [System.IO.File]::WriteAllText($taskTokenPath, $taskApiToken)
    }
    if ($taskApiToken.Length -lt 32) { throw 'The local API token must have at least 32 characters.' }
    $taskSecret = @{
        apiVersion = 'v1'; kind = 'Secret'; type = 'Opaque'
        metadata = @{ name = 'vllm-secrets'; namespace = $taskNamespace }
        stringData = @{ 'api-token' = $taskApiToken; 'hf-token' = [string]$env:HF_TOKEN }
    } | ConvertTo-Json -Depth 5
    # Secret values travel through stdin, never command-line arguments or stdout.
    $taskSecret | kubectl --context $ClusterProfile apply -f -
    if ($LASTEXITCODE -ne 0) { throw 'Secret creation failed.' }
    $taskExistingDeployment = @(kubectl --context $ClusterProfile --namespace $taskNamespace get deployment vllm --ignore-not-found -o name)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the current deployment.' }
    Invoke-Checked 'kubectl' @('--context', $ClusterProfile, 'apply', '-k', 'k8s/overlays/local')
    if ($taskExistingDeployment.Count -gt 0) {
        Invoke-Checked 'kubectl' @('--context', $ClusterProfile, '--namespace', $taskNamespace, 'rollout', 'restart', 'deployment/vllm')
    }
    Invoke-Checked 'kubectl' @('--context', $ClusterProfile, '--namespace', $taskNamespace, 'rollout', 'status', 'deployment/vllm', '--timeout=15m')
    Write-Host ('Ready. API token is stored locally in .local/api-token. Forward the API with: kubectl --context {0} -n llm-inference port-forward service/vllm 8000:8000' -f $ClusterProfile)
} finally {
    Pop-Location
}
