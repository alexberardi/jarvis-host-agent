# Install the host agent as a Scheduled Task in the interactive user session.
#
# Never a Windows Service: services run in Session 0, which has no desktop.
# Volume would work, `open` would launch into an invisible session, and window
# enumeration would come back empty. Session 0 isolation is not bypassable.

[CmdletBinding()]
param(
    [string]$AgentBin = (Get-Command jarvis-host-agent -ErrorAction SilentlyContinue).Source,
    [string]$TaskName = "Jarvis\JarvisHostAgent"
)

$ErrorActionPreference = "Stop"

if (-not $AgentBin) {
    throw "jarvis-host-agent not found on PATH; pass -AgentBin with its full path."
}

$xmlPath = Join-Path $PSScriptRoot "JarvisHostAgent.xml"
$userId  = "$env:USERDOMAIN\$env:USERNAME"

$xml = (Get-Content -Raw -Path $xmlPath).
    Replace("__AGENT_BIN__", $AgentBin).
    Replace("__USER_ID__", $userId)

# Unregister first so a re-run updates rather than failing on a duplicate.
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Xml $xml | Out-Null
Start-ScheduledTask -TaskName $TaskName

Write-Host "installed scheduled task: $TaskName"
Write-Host "running as: $userId (interactive session)"
Write-Host "agent:      $AgentBin"
Write-Host ""
Write-Host "It starts at logon. It does NOT run while signed out - that is"
Write-Host "deliberate; there is no desktop to control when nobody is logged in."
