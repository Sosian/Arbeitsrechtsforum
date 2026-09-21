<#
Pester tests for publish.ps1 (reworked in commit 1401d00, September 2026).

Run with: Invoke-Pester tests\publish.Tests.ps1

SAFETY - read this before touching this file: publish.ps1 creates a real
"Sent_<date>" git tag and a real zip in Versendete_Versionen every time it
runs. NEVER run it against this repository directly. Every test below
clones the repo into a short-lived, short-path throwaway clone under
$env:TEMP\arf-pester\<random> first, runs publish.ps1 only inside that
clone, and deletes the clone again afterwards (pass or fail).

The clone root has to be SHORT: the German Vortrag filenames make the
deepest paths already tracked in this repo around 130+ characters long
(e.g. pdf\2019\pdf\Konformität_des_Arbeitszeitrechts_...pdf), so cloning
under a long scratch path risks the Windows 260-character MAX_PATH limit.
Hence $env:TEMP\arf-pester\<8 hex chars>, not a nested project scratch dir.
#>

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$CloneBase = Join-Path $env:TEMP "arf-pester"

function New-ThrowawayClone {
    # A plain local `git clone` gives us a clean, deterministic worktree at
    # HEAD - exactly the "clean working tree" precondition publish.ps1
    # requires - regardless of whatever is sitting uncommitted in the real
    # repo right now.
    if (-not (Test-Path $CloneBase)) {
        New-Item -ItemType Directory -Path $CloneBase -Force | Out-Null
    }
    $name = [System.Guid]::NewGuid().ToString("N").Substring(0, 8)
    $dest = Join-Path $CloneBase $name

    # --no-tags: the real repo carries years of real "Sent_*" tags from
    # actual publishes (including a stray unpadded "Sent_2026.9.20" - the
    # very bug this rework fixed - and a real "Sent_2026.09.20_Part2" from
    # today). Cloning tags along would silently make every throwaway clone
    # think earlier "Part"s of today's date were already taken. The tests
    # only care about tags created inside the clone itself.
    $cloneOutput = & git clone --quiet --no-tags --local $RepoRoot $dest 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git clone into $dest failed with exit code ${LASTEXITCODE}: $cloneOutput"
    }
    return $dest
}

function Remove-ThrowawayClone {
    param([string]$Path)
    if ($Path -and (Test-Path $Path)) {
        Remove-Item -Recurse -Force $Path -ErrorAction SilentlyContinue
    }
}

function Get-StagingSiblingLeftovers {
    # publish.ps1 stages its copy at "..\<name>" relative to the repo root,
    # i.e. as a SIBLING of the clone directory, before zipping it. Confirms
    # nothing of that staging copy survives a run (successful or aborted).
    param([string]$ClonePath)
    $parent = Split-Path $ClonePath -Parent
    Get-ChildItem -Path $parent -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "website_arbeitsrechtsforum_*" }
}

function Get-SentTags {
    param([string]$ClonePath)
    Push-Location $ClonePath
    try {
        & git tag --list "Sent_*"
    } finally {
        Pop-Location
    }
}

Describe "publish.ps1 - packaging a normal run" {

    It "zips the site without publish.ps1, Versendete_Versionen, Flyer or .git, and names it correctly" {
        $clone = New-ThrowawayClone
        try {
            Push-Location $clone
            try {
                & (Join-Path $clone "publish.ps1") | Out-Null
            } finally {
                Pop-Location
            }

            $zips = @(Get-ChildItem (Join-Path $clone "Versendete_Versionen\*.zip"))
            $zips.Count | Should Be 1
            $zips[0].Name | Should Match '^website_arbeitsrechtsforum_\d{4}_\d{2}_\d{2}(_Part\d+)?\.zip$'

            $extractDir = Join-Path $clone "extracted"
            Expand-Archive -Path $zips[0].FullName -DestinationPath $extractDir

            $allEntries = Get-ChildItem -Path $extractDir -Recurse -Force
            ($allEntries.Name -contains "publish.ps1") | Should Be $false
            ($allEntries.Name -contains "Versendete_Versionen") | Should Be $false
            ($allEntries.Name -contains "Flyer") | Should Be $false
            ($allEntries.Name -contains ".git") | Should Be $false

            # Sanity check the zip is not just empty / everything filtered out.
            ($allEntries.Name -contains "index.html") | Should Be $true
        } finally {
            Remove-ThrowawayClone $clone
        }
    }

    It "zero-pads the date in the zip name (2026_09_20, not 2026_9_20)" {
        $clone = New-ThrowawayClone
        try {
            Push-Location $clone
            try {
                & (Join-Path $clone "publish.ps1") | Out-Null
            } finally {
                Pop-Location
            }

            $expectedDate = Get-Date -Format "yyyy_MM_dd"
            $zip = Get-ChildItem (Join-Path $clone "Versendete_Versionen\*.zip") | Select-Object -First 1
            $zip.Name | Should Be "website_arbeitsrechtsforum_$expectedDate.zip"
        } finally {
            Remove-ThrowawayClone $clone
        }
    }
}

Describe "publish.ps1 - repeated runs on the same day" {

    It "produces _Part2 on the second run and _Part3 on the third" {
        $clone = New-ThrowawayClone
        try {
            Push-Location $clone
            try {
                & (Join-Path $clone "publish.ps1") | Out-Null
                & (Join-Path $clone "publish.ps1") | Out-Null
                & (Join-Path $clone "publish.ps1") | Out-Null
            } finally {
                Pop-Location
            }

            $today = Get-Date -Format "yyyy_MM_dd"
            $names = @(Get-ChildItem (Join-Path $clone "Versendete_Versionen\*.zip") |
                Select-Object -ExpandProperty Name)

            $names.Count | Should Be 3
            ($names -contains "website_arbeitsrechtsforum_$today.zip") | Should Be $true
            ($names -contains "website_arbeitsrechtsforum_${today}_Part2.zip") | Should Be $true
            ($names -contains "website_arbeitsrechtsforum_${today}_Part3.zip") | Should Be $true
        } finally {
            Remove-ThrowawayClone $clone
        }
    }
}

Describe "publish.ps1 - failure handling" {

    It "leaves no tag, no zip and no leftover staging folder when the run aborts" {
        $clone = New-ThrowawayClone
        try {
            # An uppercase folder name makes the staged copy fail its
            # case-sensitivity check further down the script. "Bilder" is
            # deliberately a name that does not already exist anywhere in
            # the repo (unlike e.g. "Media", which would silently land
            # inside the existing lowercase media/ folder on Windows and
            # prove nothing).
            New-Item -ItemType Directory -Path (Join-Path $clone "Bilder") | Out-Null
            Set-Content -Path (Join-Path $clone "Bilder\dummy.txt") -Value "x"
            Push-Location $clone
            try {
                & git add -A | Out-Null
                & git commit --quiet -m "Add Bilder folder to trip the uppercase check" | Out-Null
            } finally {
                Pop-Location
            }

            Push-Location $clone
            try {
                { & (Join-Path $clone "publish.ps1") } | Should Throw
            } finally {
                Pop-Location
            }

            $zips = @(Get-ChildItem (Join-Path $clone "Versendete_Versionen\*.zip") -ErrorAction SilentlyContinue)
            $zips.Count | Should Be 0

            (Get-SentTags $clone) | Should BeNullOrEmpty

            (Get-StagingSiblingLeftovers $clone) | Should BeNullOrEmpty
        } finally {
            Remove-ThrowawayClone $clone
        }
    }

    It "aborts when the staged copy contains an uppercase folder name" {
        $clone = New-ThrowawayClone
        try {
            # Two traps avoided here: (1) a folder literally named "Media"
            # would collide with the existing lowercase media/ and be
            # created inside it on a case-insensitive filesystem, proving
            # nothing - so this uses "Bilder", a name that doesn't exist
            # yet. (2) Flyer and Versendete_Versionen are legitimately
            # uppercase and must NOT trip this check - which is exactly why
            # publish.ps1 runs the case check on the staged copy, after
            # those two are already excluded, rather than on the raw repo.
            New-Item -ItemType Directory -Path (Join-Path $clone "Bilder") | Out-Null
            Set-Content -Path (Join-Path $clone "Bilder\dummy.txt") -Value "x"
            Push-Location $clone
            try {
                & git add -A | Out-Null
                & git commit --quiet -m "Add Bilder folder to trip the uppercase check" | Out-Null
            } finally {
                Pop-Location
            }

            Push-Location $clone
            try {
                { & (Join-Path $clone "publish.ps1") } | Should Throw "Uppercase folder"
            } finally {
                Pop-Location
            }
        } finally {
            Remove-ThrowawayClone $clone
        }
    }
}

Describe "repository hygiene" {

    It "does not version anything under Versendete_Versionen (a 15 MB zip lived there for years)" {
        Push-Location $RepoRoot
        try {
            $tracked = & git -c core.quotepath=false ls-files "Versendete_Versionen"
        } finally {
            Pop-Location
        }
        $tracked | Should BeNullOrEmpty
    }

    It "has no versioned file larger than 1 MB outside pdf/" {
        Push-Location $RepoRoot
        try {
            # core.quotepath=false: without it, git escapes the umlauts in
            # this repo's German filenames as quoted backslash-octal
            # sequences (e.g. "Konformit\303\244t...") instead of raw UTF-8,
            # which then fails Test-Path with "Illegal characters in path".
            $files = & git -c core.quotepath=false ls-files
        } finally {
            Pop-Location
        }

        $tooLarge = foreach ($f in $files) {
            if ($f -notmatch '^pdf/') {
                $full = Join-Path $RepoRoot ($f -replace '/', '\')
                if (Test-Path $full -PathType Leaf) {
                    $size = (Get-Item $full).Length
                    if ($size -gt 1MB) {
                        "$f ($size bytes)"
                    }
                }
            }
        }

        $tooLarge | Should BeNullOrEmpty
    }
}
