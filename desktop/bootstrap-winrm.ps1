#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$AccountName = 'ansible'
)

$ErrorActionPreference = 'Stop'

$account = Get-LocalUser -Name $AccountName -ErrorAction SilentlyContinue
if (-not $account) {
    $password = Read-Host `
        "Enter a password for the local $AccountName account" `
        -AsSecureString
    $account = New-LocalUser -Name $AccountName -Password $password `
        -Description 'Local account for Ansible WinRM automation' `
        -AccountNeverExpires
    Write-Host "Created local account: $AccountName"
} elseif (-not $account.Enabled) {
    Enable-LocalUser -Name $AccountName
    Write-Host "Enabled local account: $AccountName"
} else {
    Write-Host "Local account already exists and is enabled: $AccountName"
}

$administrators = Get-LocalGroupMember -Group 'Administrators' |
    Select-Object -ExpandProperty Name
$qualifiedName = "${env:COMPUTERNAME}\${AccountName}"
if ($qualifiedName -notin $administrators) {
    Add-LocalGroupMember -Group 'Administrators' -Member $AccountName
    Write-Host "Added $AccountName to the local Administrators group"
}

Set-Service -Name WinRM -StartupType Automatic
Enable-PSRemoting -Force -SkipNetworkProfileCheck

# Permit local administrator accounts to receive a full elevated token over
# WinRM. Without this policy, remote UAC filtering can block administrator work.
$policyPath = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System'
New-ItemProperty -Path $policyPath -Name LocalAccountTokenFilterPolicy `
    -PropertyType DWord -Value 1 -Force | Out-Null

Write-Host ''
Write-Host 'WinRM bootstrap complete.'
Write-Host "Ansible username: ${qualifiedName}"
Write-Host 'The password was entered securely and was not written to disk.'
