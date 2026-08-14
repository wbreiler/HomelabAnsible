#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [string]$WindowsUser = 'Techn'
)

$ErrorActionPreference = 'Stop'

$capability = Get-WindowsCapability -Online |
    Where-Object Name -Like 'OpenSSH.Server*'
if ($capability.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $capability.Name
}

Set-Service -Name sshd -StartupType Automatic
Start-Service -Name sshd

if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' `
        -DisplayName 'OpenSSH Server (sshd)' -Enabled True `
        -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
}

$shellPath = 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell `
    -Value $shellPath -PropertyType String -Force | Out-Null

Write-Host "OpenSSH is ready. Test from the Ansible controller with:"
Write-Host "  ssh ${WindowsUser}@<gaming-pc-ip>"

