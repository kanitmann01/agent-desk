<#
.SYNOPSIS
  Export Outlook mail headers into an .eml folder the Outlook Brief can read.

.DESCRIPTION
  Uses the local Outlook desktop client over COM. There is no connector,
  no OAuth and no network call: the script copies what Outlook already
  has on this machine into one .eml file per message.

  Privacy rule: the export is header-only. Subject, sender, recipients,
  date, Message-ID, In-Reply-To and Importance are written. The body is
  left empty on purpose, so the app can never read or store it.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools/export-outlook.ps1 -OutDir demo/outlook-inbox
#>

param(
  [Parameter(Mandatory = $true)]
  [string]$OutDir,
  [int]$Days = 14,
  [int]$Limit = 100,
  [string]$Folder = "Inbox"
)

$ErrorActionPreference = "Stop"

function Get-SmtpAddress($mail) {
  if ($mail.SenderEmailType -eq "EX") {
    try {
      $exchange = $mail.Sender.GetExchangeUser()
      if ($exchange -and $exchange.PrimarySmtpAddress) {
        return $exchange.PrimarySmtpAddress
      }
    } catch { }
    return $mail.SenderName
  }
  return $mail.SenderEmailAddress
}

function Get-Header([string]$value) {
  if ($null -eq $value) { return "" }
  return ($value -replace "[\r\n]+", " ").Trim()
}

function Get-Property($mail, [string]$tag) {
  try { return [string]$mail.PropertyAccessor.GetProperty($tag) } catch { return "" }
}

if (-not (Test-Path -LiteralPath $OutDir)) {
  New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
}
$OutDir = (Resolve-Path -LiteralPath $OutDir).Path

try {
  $outlook = New-Object -ComObject Outlook.Application
  $namespace = $outlook.GetNamespace("MAPI")
  $root = $namespace.GetDefaultFolder(6) # olFolderInbox
  if ($Folder -and $Folder -ne "Inbox") {
    $root = $root.Folders.Item($Folder)
  }
} catch {
  Write-Error ("Outlook could not be opened. Configure a mail profile in Outlook first, " +
    "or export .eml files another way. Details: " + $_.Exception.Message)
  exit 1
}

$cutoff = (Get-Date).AddDays(-1 * $Days)
$items = $root.Items
$items.Sort("[ReceivedTime]", $true)
$filter = "[ReceivedTime] >= '" + $cutoff.ToString("g") + "'"
$restricted = $items.Restrict($filter)

$PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
$PR_IN_REPLY_TO_ID = "http://schemas.microsoft.com/mapi/proptag/0x1042001F"

$index = 0
$written = 0
foreach ($mail in $restricted) {
  if ($written -ge $Limit) { break }
  if ($mail.Class -ne 43) { continue } # olMail only
  $index++
  $sender = Get-Header $mail.SenderName
  $address = Get-Header (Get-SmtpAddress $mail)
  $subject = Get-Header $mail.Subject
  $to = @()
  $cc = @()
  foreach ($recipient in $mail.Recipients) {
    $line = Get-Header $recipient.Address
    if ($recipient.Type -eq 2) { $cc += $line } else { $to += $line }
  }
  $messageId = Get-Header (Get-Property $mail $PR_INTERNET_MESSAGE_ID)
  if (-not $messageId) { $messageId = "<outlook-" + $mail.EntryID.GetHashCode() + "@agent-desk.local>" }
  $inReplyTo = Get-Header (Get-Property $mail $PR_IN_REPLY_TO_ID)
  $importance = switch ($mail.Importance) { 2 { "High" } 0 { "Low" } default { "Normal" } }
  $lines = @(
    "From: $sender <$address>",
    "To: " + ($to -join ", "),
    "Subject: $subject",
    "Date: " + $mail.ReceivedTime.ToUniversalTime().ToString("r"),
    "Message-ID: $messageId",
    "Importance: $importance",
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8"
  )
  if ($cc.Count -gt 0) { $lines += "CC: " + ($cc -join ", ") }
  if ($inReplyTo) { $lines += "In-Reply-To: $inReplyTo" }
  # The blank line ends the headers. No body is written on purpose.
  $text = ($lines -join "`r`n") + "`r`n`r`n"
  $stamp = $mail.ReceivedTime.ToString("yyyyMMdd-HHmmss")
  $name = "{0}-{1:D4}.eml" -f $stamp, $index
  $path = Join-Path $OutDir $name
  [System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))
  $written++
}

Write-Host ("Exported {0} header-only message(s) to {1}" -f $written, $OutDir)
if ($written -eq 0) {
  Write-Host "Nothing matched. Widen -Days or choose another -Folder."
}
