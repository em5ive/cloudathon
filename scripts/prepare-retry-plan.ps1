[CmdletBinding()]
param(
    [string]$Profile = '',
    [switch]$ShareCliSession,
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]*\.(tfplan|tfretry)$')]
    [string]$PlanFileName = 'retry.tfplan',
    [switch]$VerifyStateOnly
)

# Recovery planning only. Never initializes, migrates, selects a workspace,
# applies, or writes state. The used original binary plan is never executed.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$terraformDirectory = Join-Path $projectRoot 'terraform'
$reportDirectory = Join-Path $projectRoot 'reports'
$statePath = Join-Path $terraformDirectory 'terraform.tfstate'
$inputRecord = Join-Path $reportDirectory 'review-plan.json'
$originalPlanPath = Join-Path $reportDirectory 'review.tfplan'
$retryPath = Join-Path $reportDirectory $PlanFileName
$retryInputsPath = "$retryPath.inputs.tfvars.json"
$retryTextPath = "$retryPath.txt"
$retryJsonPath = "$retryPath.json"
$auditPath = "$retryPath.audit.json"
$stateCheckPath = "$retryPath.state-check.json"
$guardPath = Join-Path $PSScriptRoot 'retry-plan-guard.py'

if (!(Test-Path -LiteralPath $statePath)) { throw 'The partial-apply local state was not found. Stop; do not initialize an empty deployment.' }
if (!(Test-Path -LiteralPath $inputRecord)) { throw 'The original input-variable record was not found.' }
if (!$VerifyStateOnly) {
    foreach ($path in @($retryPath, $retryInputsPath, $retryTextPath, $retryJsonPath, $auditPath, $stateCheckPath)) {
        if (Test-Path -LiteralPath $path) { throw 'A requested retry output already exists. Preserve it; choose a fresh -PlanFileName for another plan.' }
    }
}

# Check before invoking Terraform: injected CLI flags or a different data
# directory/workspace can silently redirect state selection.
$redirectNames = @([Environment]::GetEnvironmentVariables('Process').Keys | Where-Object {
    ($_ -match '^TF_CLI_ARGS' -or $_ -in @('TF_WORKSPACE', 'TF_DATA_DIR')) -and
    ![string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($_, 'Process'))
})
if ($redirectNames.Count) { throw "State-selection environment overrides are set: $($redirectNames -join ', '). Review and remove them in this terminal before retrying; values were not printed." }
foreach ($configuration in Get-ChildItem -LiteralPath $terraformDirectory -File -Filter '*.tf') {
    if ([IO.File]::ReadAllText($configuration.FullName) -match '\b(backend\s+"|cloud\s*\{)') {
        throw 'Backend/cloud configuration differs from the reviewed implicit local backend. Stop and review it; this helper will not initialize or migrate state.'
    }
}
if (Get-ChildItem -LiteralPath $terraformDirectory -File -Filter '*.tf.json') {
    throw 'Unexpected JSON Terraform configuration requires backend review before recovery planning.'
}
$backendMetadataPath = Join-Path $terraformDirectory '.terraform\terraform.tfstate'
if (Test-Path -LiteralPath $backendMetadataPath) {
    $backendMetadata = [IO.File]::ReadAllText($backendMetadataPath) | ConvertFrom-Json
    if (!($backendMetadata.PSObject.Properties.Name -contains 'backend') -or $backendMetadata.backend.type -ne 'local') {
        throw 'Cached backend is not the reviewed local backend. No initialization or migration was attempted.'
    }
    $backendPath = $backendMetadata.backend.config.path
    if (!$backendPath) { $backendPath = 'terraform.tfstate' }
    if (![IO.Path]::IsPathRooted($backendPath)) { $backendPath = Join-Path $terraformDirectory $backendPath }
    if ([IO.Path]::GetFullPath($backendPath) -ne $statePath) { throw 'Cached local backend points at a different state file.' }
}

$record = [IO.File]::ReadAllText($inputRecord) | ConvertFrom-Json
$retryVariables = [ordered]@{}
foreach ($property in $record.variables.PSObject.Properties) {
    if ($property.Name -match '(?i)password|secret_access_key|access_key_id|session_token|credential') {
        throw 'Unexpected sensitive input name; do not copy credentials into plan variables.'
    }
    $retryVariables[$property.Name] = $property.Value.value
}
foreach ($flag in @('database_bootstrapped', 'enable_bootstrap')) {
    $retryVariables[$flag] = [bool]::Parse([string]$retryVariables[$flag])
}
if ($retryVariables['database_bootstrapped'] -or !$retryVariables['enable_bootstrap']) {
    throw 'Retry variables do not describe the first-stage bootstrap deployment.'
}
if ($retryVariables['aws_region'] -ne 'us-west-2' -or $retryVariables['expected_account_id'] -ne '708661874787') {
    throw 'The original input record does not match the reviewed competition account and region.'
}

$stateHashBefore = (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash
$stateBefore = [IO.File]::ReadAllText($statePath) | ConvertFrom-Json
$inputHashBefore = (Get-FileHash -LiteralPath $inputRecord -Algorithm SHA256).Hash
$originalPlanHashBefore = if (Test-Path -LiteralPath $originalPlanPath) { (Get-FileHash -LiteralPath $originalPlanPath -Algorithm SHA256).Hash } else { $null }
$savedEnvironment = @{}
$sessionNames = @('AWS_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION', 'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'TF_LOG', 'TF_LOG_PATH')
$sessionNames = @($sessionNames + @([Environment]::GetEnvironmentVariables('Process').Keys | Where-Object { $_ -match '^TF_LOG' }) | Select-Object -Unique)
foreach ($name in $sessionNames) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

try {
    if ($Profile) { [Environment]::SetEnvironmentVariable('AWS_PROFILE', $Profile, 'Process') }
    [Environment]::SetEnvironmentVariable('AWS_REGION', 'us-west-2', 'Process')
    [Environment]::SetEnvironmentVariable('AWS_DEFAULT_REGION', 'us-west-2', 'Process')
    foreach ($name in $sessionNames | Where-Object { $_ -match '^TF_LOG' }) {
        [Environment]::SetEnvironmentVariable($name, $null, 'Process')
    }

    $workspaceLines = & terraform "-chdir=$terraformDirectory" workspace show -no-color
    if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the existing workspace. No initialization was attempted.' }
    $workspace = ($workspaceLines -join '').Trim()
    if ($workspace -ne 'default') { throw 'The active workspace is not default. Stop; this helper will not switch workspaces.' }
    $effectiveStateLines = & terraform "-chdir=$terraformDirectory" state pull
    if ($LASTEXITCODE -ne 0) { throw 'Could not read the selected backend state. Do not plan against an empty deployment.' }
    $checkDirectory = Join-Path $projectRoot '.build'
    New-Item -ItemType Directory -Path $checkDirectory -Force | Out-Null
    $selectionReport = Join-Path $checkDirectory "retry-state-check-$([guid]::NewGuid().ToString('N')).json"
    # State JSON stays in memory/stdin. Do not print it or duplicate it to disk.
    ($effectiveStateLines -join [Environment]::NewLine) | & python $guardPath selection --state $statePath --effective-state - --workspace $workspace --terraform-dir $terraformDirectory --report $selectionReport
    if ($LASTEXITCODE -ne 0) {
        $reason = 'See the recovery diagnostic report.'
        if (Test-Path -LiteralPath $selectionReport) {
            $selectionFailure = [IO.File]::ReadAllText($selectionReport) | ConvertFrom-Json
            if ($selectionFailure.PSObject.Properties.Name -contains 'violations') {
                $reason = $selectionFailure.violations -join ' '
            }
        }
        throw "Recovery state verification failed: $reason No plan was generated. Report: $selectionReport"
    }
    $effectiveStateLines = $null
    if ($VerifyStateOnly) {
        Write-Output 'State-selection verification passed. No AWS request or plan was made.'
        return
    }

    $identityLines = & aws sts get-caller-identity --region us-west-2 --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw 'AWS identity failed in this terminal; no retry plan was created.' }
    $identity = ($identityLines -join [Environment]::NewLine) | ConvertFrom-Json
    if ($identity.Account -ne $retryVariables['expected_account_id']) { throw 'Active AWS account differs from the partial deployment.' }
    Write-Output "Verified existing deployment account $($identity.Account), region us-west-2, state serial $($stateBefore.serial)."

    if ($ShareCliSession) {
        $credentialLines = & aws configure export-credentials --format process
        if ($LASTEXITCODE -ne 0) { throw 'The CLI session could not be shared with Terraform; credential values were not printed.' }
        try { $sessionCredentials = ($credentialLines -join [Environment]::NewLine) | ConvertFrom-Json }
        catch { throw 'CLI session response could not be parsed; credential values were not printed.' }
        if (!$sessionCredentials.AccessKeyId -or !$sessionCredentials.SecretAccessKey) { throw 'The CLI did not return usable session credentials.' }
        [Environment]::SetEnvironmentVariable('AWS_ACCESS_KEY_ID', $sessionCredentials.AccessKeyId, 'Process')
        [Environment]::SetEnvironmentVariable('AWS_SECRET_ACCESS_KEY', $sessionCredentials.SecretAccessKey, 'Process')
        $sessionToken = if ($sessionCredentials.PSObject.Properties.Name -contains 'SessionToken') { $sessionCredentials.SessionToken } else { $null }
        [Environment]::SetEnvironmentVariable('AWS_SESSION_TOKEN', $sessionToken, 'Process')
        $credentialLines = $null; $sessionCredentials = $null; $sessionToken = $null
    }

    & python (Join-Path $PSScriptRoot 'verify-lambda-packages.py')
    if ($LASTEXITCODE -ne 0) { throw 'Package verification failed; preserve the existing deployed packages and investigate.' }
    & terraform "-chdir=$terraformDirectory" fmt -check -recursive
    if ($LASTEXITCODE -ne 0) { throw 'Terraform formatting must pass before the retry plan.' }
    & terraform "-chdir=$terraformDirectory" validate -no-color
    if ($LASTEXITCODE -ne 0) { throw 'Terraform validation failed.' }
    if ((Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash -ne $stateHashBefore) {
        throw 'State changed after verification. Stop and reconcile concurrent deployment activity.'
    }
    [IO.File]::Copy($selectionReport, $stateCheckPath, $false)
    [IO.File]::WriteAllText($retryInputsPath, ($retryVariables | ConvertTo-Json -Depth 30), [Text.UTF8Encoding]::new($false))
    # -state is valid for this verified local/default backend. Normal refresh
    # reads AWS into the plan, without persisting refreshed state to disk.
    # No -target, -replace, -refresh=false, or old saved-plan execution is used.
    & terraform "-chdir=$terraformDirectory" plan -input=false -no-color -lock-timeout=30s "-state=$statePath" "-var-file=$retryInputsPath" "-out=$retryPath"
    if ($LASTEXITCODE -ne 0) { throw 'Retry planning failed; inspect the exact error. No apply was run.' }
    $retryText = & terraform "-chdir=$terraformDirectory" show -no-color $retryPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the new retry plan.' }
    [IO.File]::WriteAllText($retryTextPath, ($retryText -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    $retryJson = & terraform "-chdir=$terraformDirectory" show -json $retryPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the new retry plan JSON.' }
    [IO.File]::WriteAllText($retryJsonPath, ($retryJson -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    & python $guardPath plan --state $statePath --plan $retryPath --json $retryJsonPath --input-record $inputRecord --report $auditPath
    if ($LASTEXITCODE -ne 0) { throw 'The saved plan failed recovery checks. Preserve the generated review files and investigate; do not apply.' }
    Write-Output "Recovery plan saved to $retryPath. Only the missing SNS policy is allowed. No apply was run."
}
finally {
    foreach ($name in $sessionNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    $credentialLines = $null; $sessionCredentials = $null; $sessionToken = $null; $effectiveStateLines = $null
    $stateHashAfter = (Get-FileHash -LiteralPath $statePath -Algorithm SHA256).Hash
    if ($stateHashAfter -ne $stateHashBefore) { throw 'State bytes changed during planning. Stop and reconcile concurrent activity; this helper does not edit or restore state.' }
    if ((Get-FileHash -LiteralPath $inputRecord -Algorithm SHA256).Hash -ne $inputHashBefore) { throw 'The original variable record changed during recovery planning.' }
    if ($originalPlanHashBefore -and (Get-FileHash -LiteralPath $originalPlanPath -Algorithm SHA256).Hash -ne $originalPlanHashBefore) { throw 'The historical original plan changed during recovery planning.' }
    Write-Output 'PASS: existing Terraform state and historical plan/input bytes are unchanged.'
}
