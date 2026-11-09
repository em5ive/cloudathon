[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9]{12}$')][string]$ExpectedAccountId,
    [Parameter(Mandatory = $true)][ValidatePattern('^(16|17)\.[0-9]+(\.[0-9]+)?$')][string]$EngineVersion,
    [ValidatePattern('^[a-z][a-z0-9-]{2,23}$')][string]$ProjectName = 'uh-retail-poc',
    [string]$Profile = '',
    [switch]$ShareCliSession
)

# Run from the terminal that owns the authenticated workshop session. This file
# only reads AWS and writes local review artifacts. It never applies Terraform.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$terraformDirectory = Join-Path $projectRoot 'terraform'
$reportDirectory = Join-Path $projectRoot 'reports'
$planPath = Join-Path $reportDirectory 'review.tfplan'
if ((Test-Path -LiteralPath (Join-Path $terraformDirectory 'terraform.tfstate')) -or
    (Test-Path -LiteralPath $planPath) -or
    (Test-Path -LiteralPath (Join-Path $reportDirectory 'review-plan.json')) -or
    (Test-Path -LiteralPath (Join-Path $reportDirectory 'review-plan.txt'))) {
    throw 'An existing deployment state or original plan is present. Preserve it and use scripts/prepare-retry-plan.ps1 for recovery; this initial-deployment helper must not overwrite the reviewed inputs or plan.'
}
$savedEnvironment = @{}
$sessionNames = @('AWS_PROFILE', 'AWS_REGION', 'AWS_DEFAULT_REGION', 'AWS_ACCESS_KEY_ID',
    'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN', 'TF_LOG', 'TF_LOG_PATH')
foreach ($name in $sessionNames) { $savedEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }

try {
    if ($Profile) { [Environment]::SetEnvironmentVariable('AWS_PROFILE', $Profile, 'Process') }
    [Environment]::SetEnvironmentVariable('AWS_REGION', 'us-west-2', 'Process')
    [Environment]::SetEnvironmentVariable('AWS_DEFAULT_REGION', 'us-west-2', 'Process')
    [Environment]::SetEnvironmentVariable('TF_LOG', $null, 'Process')
    [Environment]::SetEnvironmentVariable('TF_LOG_PATH', $null, 'Process')
    $identityLines = & aws sts get-caller-identity --region us-west-2 --output json --no-cli-pager
    if ($LASTEXITCODE -ne 0) { throw 'AWS identity check failed in this terminal. No plan was created.' }
    $identity = ($identityLines -join [Environment]::NewLine) | ConvertFrom-Json
    if ($identity.Account -ne $ExpectedAccountId) { throw 'AWS account does not match the reviewed competition account. No plan was created.' }
    Write-Output "Verified account $ExpectedAccountId; target region us-west-2."

    if ($ShareCliSession) {
        # Legitimate CLI credentials, temporarily shared in process memory for
        # SDK/provider compatibility. Never echo or write this JSON to a file.
        $credentialLines = & aws configure export-credentials --format process
        if ($LASTEXITCODE -ne 0) { throw 'The CLI session could not be shared with the provider. No credential values were printed.' }
        try { $sessionCredentials = ($credentialLines -join [Environment]::NewLine) | ConvertFrom-Json }
        catch { throw 'The CLI credential response could not be parsed. No credential values were printed.' }
        if (!$sessionCredentials.AccessKeyId -or !$sessionCredentials.SecretAccessKey) { throw 'The CLI did not return usable session credentials.' }
        [Environment]::SetEnvironmentVariable('AWS_ACCESS_KEY_ID', $sessionCredentials.AccessKeyId, 'Process')
        [Environment]::SetEnvironmentVariable('AWS_SECRET_ACCESS_KEY', $sessionCredentials.SecretAccessKey, 'Process')
        $sessionToken = if ($sessionCredentials.PSObject.Properties.Name -contains 'SessionToken') { $sessionCredentials.SessionToken } else { $null }
        [Environment]::SetEnvironmentVariable('AWS_SESSION_TOKEN', $sessionToken, 'Process')
        $credentialLines = $null; $sessionCredentials = $null; $sessionToken = $null
    }

    New-Item -ItemType Directory -Path $reportDirectory -Force | Out-Null
    & python (Join-Path $PSScriptRoot 'verify-lambda-packages.py')
    if ($LASTEXITCODE -ne 0) { throw 'Build current Lambda packages before planning.' }
    # Windows PowerShell can promote native stderr warnings under Stop. Keep
    # quota warnings visible and decide success from the preflight exit code.
    $previousErrorPolicy = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & python (Join-Path $PSScriptRoot 'aws-preflight.py') --region us-west-2 --expected-account-id $ExpectedAccountId --engine-version $EngineVersion --project-name $ProjectName --output (Join-Path $reportDirectory 'aws-preflight.json')
        $preflightExit = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previousErrorPolicy }
    if ($preflightExit -ne 0) { throw 'A confirmed blocker or missing required verification prevents planning. Review reports/aws-preflight.json.' }
    & terraform "-chdir=$terraformDirectory" init -backend=false -input=false -lockfile=readonly
    if ($LASTEXITCODE -ne 0) { throw 'Provider initialization failed.' }
    & terraform "-chdir=$terraformDirectory" validate -no-color
    if ($LASTEXITCODE -ne 0) { throw 'Terraform validation failed.' }
    $planArguments = @("-chdir=$terraformDirectory", 'plan', '-input=false', '-no-color',
        "-var=expected_account_id=$ExpectedAccountId", "-var=aurora_engine_version=$EngineVersion",
        "-var=project_name=$ProjectName", '-var=enable_bootstrap=true', '-var=database_bootstrapped=false',
        '-var=lambda_reserved_concurrency={products=3,orders=3,support=2}',
        '-var=bedrock_model_id=', '-var=bedrock_model_arn=', "-out=$planPath")
    & terraform @planArguments
    if ($LASTEXITCODE -ne 0) { throw 'Terraform plan failed. Review the actual error; no apply was run.' }
    $reviewText = & terraform "-chdir=$terraformDirectory" show -no-color $planPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the saved plan.' }
    [IO.File]::WriteAllText((Join-Path $reportDirectory 'review-plan.txt'), ($reviewText -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    $reviewJson = & terraform "-chdir=$terraformDirectory" show -json $planPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not render the saved plan JSON.' }
    [IO.File]::WriteAllText((Join-Path $reportDirectory 'review-plan.json'), ($reviewJson -join [Environment]::NewLine), [Text.UTF8Encoding]::new($false))
    Write-Output 'Plan saved to reports/review.tfplan; readable text and JSON are beside it. No apply was run.'
}
finally {
    foreach ($name in $sessionNames) { [Environment]::SetEnvironmentVariable($name, $savedEnvironment[$name], 'Process') }
    $credentialLines = $null; $sessionCredentials = $null; $sessionToken = $null
}
