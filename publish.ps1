# Packs the website into a zip to send to the host and tags the commit it was
# built from. Run from the repository root with a clean working tree.

$ErrorActionPreference = "Stop"

# A native command returning non zero does not stop the script on its own, so
# every git call goes through here and the exit code is checked.
# No param block on purpose: with one, PowerShell tries to bind git's own
# switches like -a and -m to the function and the call fails.
function Invoke-Git {
  $Output = & git $args
  if ($LASTEXITCODE -ne 0) {
    throw "git $($args -join ' ') failed with exit code $LASTEXITCODE"
  }
  return $Output
}

if (Invoke-Git status --porcelain) {
  throw "Git repository is not clean"
}

# Zero padded, otherwise the archives sort wrong: 2026_9_20 comes before
# 2026_12_03 in a file listing.
$CurrentDate = Get-Date
$DateForName = $CurrentDate.ToString("yyyy_MM_dd")
$DateForTag = $CurrentDate.ToString("yyyy.MM.dd")

# A second publish on the same day becomes _Part2, a third _Part3 and so on.
# Both the tag and the zip have to be free: if either already exists the run
# would fail halfway and leave the staging folder behind.
$Part = 1
$Suffix = ""
while ($true) {
  $TagString = "Sent_$($DateForTag)$($Suffix)"
  $NameOfNewFolder = "website_arbeitsrechtsforum_$($DateForName)$($Suffix)"
  $ArchivePath = ".\Versendete_Versionen\$($NameOfNewFolder).zip"

  if (-not (Invoke-Git tag --list $TagString) -and -not (Test-Path $ArchivePath)) {
    break
  }

  $Part++
  $Suffix = "_Part$($Part)"
}

$PathToNewFolder = "..\$($NameOfNewFolder)"

if (Test-Path $PathToNewFolder) {
  throw "$PathToNewFolder already exists - remove it and run again"
}

if (-not (Test-Path .\Versendete_Versionen)) {
  New-Item -ItemType Directory -Path .\Versendete_Versionen | Out-Null
}

# Kept out of the sent version: the script itself, the previous archives and
# the flyer. Excluded while copying rather than deleted afterwards, so the
# 120 MB of old archives is not copied just to be thrown away again.
$ExcludeFromSite = @("publish.ps1", "Versendete_Versionen", "Flyer", ".git")

New-Item -ItemType Directory -Path $PathToNewFolder | Out-Null

try {
  Get-ChildItem -Path . -Force |
    Where-Object { $ExcludeFromSite -notcontains $_.Name } |
    Copy-Item -Destination $PathToNewFolder -Recurse -Force

  # The web server is case sensitive, so an uppercase folder name means links
  # that work here on Windows but 404 once the site is online. Checked on the
  # staged copy so that it looks at exactly what gets sent.
  $UppercaseFolders = Get-ChildItem -Path $PathToNewFolder -Recurse -Directory -Force |
    Where-Object { $_.Name -cmatch "[A-Z]" } |
    Select-Object -ExpandProperty Name

  if ($UppercaseFolders) {
    throw "Uppercase folder found in the site: $($UppercaseFolders -join ', ')"
  }

  Compress-Archive -Path $PathToNewFolder -DestinationPath $ArchivePath
}
finally {
  if (Test-Path $PathToNewFolder) {
    Remove-Item -Recurse -Force $PathToNewFolder
  }
}

# Tagged last, once the zip exists. Tagging first meant that anything failing
# below it left a Sent_ tag behind for a version that was never sent - and the
# next run then saw that tag and thought it was the second publish of the day.
Invoke-Git tag -a $TagString -m $TagString | Out-Null

Write-Host "Created $ArchivePath and tagged $TagString"
