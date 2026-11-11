# Run only in a disposable Windows PowerShell 5.1 / NTFS environment.
# No Pester, installation, production SMB access, or existing recordings required.
param(
    # Optional existing scratch share on this disposable Windows machine.
    [string]$NetworkRoot
)

$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT' -or $PSVersionTable.PSEdition -ne 'Desktop' -or
    $PSVersionTable.PSVersion -lt [version]'5.1') {
    throw 'Use Windows PowerShell 5.1 in a disposable Windows environment. No tests ran.'
}
if ($NetworkRoot -and $NetworkRoot -notmatch '^\\\\(localhost|127\.0\.0\.1)\\[^\\]+(\\.*)?$') {
    throw 'NetworkRoot must be an existing localhost scratch share, never the production share.'
}
$temp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$drive = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($temp))
if ($drive.DriveType -ne [IO.DriveType]::Fixed -or $drive.DriveFormat -ne 'NTFS') {
    throw 'TEMP must be on a local NTFS volume. No tests ran.'
}
$script:Robocopy = Join-Path $env:SystemRoot 'System32\robocopy.exe'
if (-not (Test-Path -LiteralPath $script:Robocopy)) { throw 'Robocopy is required.' }
$script:Subject = Join-Path $PSScriptRoot '..\copy-clips.ps1'
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($script:Subject, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors) { throw ($parseErrors | Out-String) }
$text = $ast.Extent.Text
$destinationWrites = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.AssignmentStatementAst] -and
    $node.Left -is [Management.Automation.Language.VariableExpressionAst] -and
    $node.Left.VariablePath.UserPath -ieq 'destination'
}, $true))
if ($destinationWrites.Count) { throw 'The script overwrites Destination. Refusing to risk a production transfer.' }

# Replace only native dispatch in a memory-only copy for deterministic fault injection.
# Real-copy cases execute the original file. Verification and deletion are never mocked.
$commands = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.CommandAst] -and
    $node.CommandElements[0].Extent.Text -eq '"$env:SystemRoot\System32\robocopy.exe"'
}, $true))
if ($commands.Count -ne 1) { throw 'Expected exactly one Robocopy dispatch. Review the test adapter.' }
$dispatch = $commands[0].CommandElements[0].Extent
$script:Injected = [scriptblock]::Create($text.Remove($dispatch.StartOffset,
    $dispatch.EndOffset - $dispatch.StartOffset).Insert($dispatch.StartOffset, 'Invoke-TestRobocopy'))
$functions = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $node.Name -eq 'Remove-VerifiedOriginal'
}, $true))
if ($functions.Count -ne 1) { throw 'Expected the production verification function.' }
. ([scriptblock]::Create($functions[0].Extent.Text))

function Assert([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function New-Clip([string]$Name = 'clip [1].mkv', [string]$Content = 'disposable recording bytes') {
    $file = Join-Path $script:Source $Name
    [IO.File]::WriteAllText($file, $Content)
    return $file
}
function Assert-Content([string]$File, [string]$Expected = 'disposable recording bytes') {
    Assert ([IO.File]::Exists($File)) "Missing retained file: $File"
    Assert ([IO.File]::ReadAllText($File) -ceq $Expected) "Unexpected contents: $File"
}
function Assert-Clean {
    $stages = @(Get-ChildItem -LiteralPath $script:Destination -Force -Filter '.clips-upload-*')
    Assert ($stages.Count -eq 0) 'Staging directory leaked.'
}
function Assert-Failure($Result, [string]$Pattern) {
    Assert ($null -ne $Result.Error -and $Result.Error -match $Pattern) "Expected '$Pattern', got '$($Result.Error)'"
}
function Invoke-Upload([string[]]$Files, [switch]$Real) {
    $message = $null
    $output = @()
    try {
        if ($Real) { $output = @(& $script:Subject -Destination $script:Destination @Files 3>&1) }
        else { $output = @(& $script:Injected -Destination $script:Destination @Files 3>&1) }
    } catch { $message = $_.Exception.Message }
    [pscustomobject]@{ Error = $message; Output = ($output | Out-String) }
}
function Invoke-TestRobocopy {
    param([string]$SourceFolder, [string]$Stage,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    $optionIndex = [Array]::IndexOf($Arguments, '/J')
    Assert ($optionIndex -gt 0) 'Robocopy must receive selected filenames.'
    Assert (($Arguments[$optionIndex..($Arguments.Count - 1)] -join ' ') -eq '/J /MT:1 /R:1 /W:1 /COPY:DAT') 'Robocopy options changed.'
    $names = @($Arguments[0..($optionIndex - 1)])
    $script:Calls.Add([pscustomobject]@{ Source = $SourceFolder; Names = $names })
    foreach ($name in $names) {
        $sourceFile = Join-Path $SourceFolder $name
        $partial = Join-Path $Stage $name
        if ($script:Mode -ne 'missing') { [IO.File]::Copy($sourceFile, $partial) }
        switch ($script:Mode) {
            'short' { [IO.File]::WriteAllText($partial, 'short') }
            'exit8' { [IO.File]::WriteAllText($partial, 'interrupted') }
            'mismatch' {
                $bytes = [IO.File]::ReadAllBytes($partial)
                $bytes[0] = $bytes[0] -bxor 255
                [IO.File]::WriteAllBytes($partial, $bytes)
            }
            'collision' { [IO.File]::WriteAllText((Join-Path $script:Destination $name), 'concurrent upload') }
            'replace' {
                [IO.File]::Move($sourceFile, "$sourceFile.saved")
                [IO.File]::WriteAllText($sourceFile, 'replacement recording XYZZ')
            }
        }
    }
    $exitCode = 1
    if ($script:Mode -eq 'exit8') { $exitCode = 8 }
    if ($script:Mode -eq 'exit16') { $exitCode = 16 }
    if ($script:Mode -eq 'exit7') { $exitCode = 7 }
    Set-Variable -Name LASTEXITCODE -Value $exitCode -Scope 1
}

$script:Results = [Collections.Generic.List[object]]::new()
$root = Join-Path $temp ('clips-regression-' + [guid]::NewGuid())
[void][IO.Directory]::CreateDirectory($root)
function Test-Case([string]$Name, [scriptblock]$Body, [switch]$Network) {
    if ($Network -and -not $NetworkRoot) {
        $script:Results.Add([pscustomobject]@{ Name = $Name; Status = 'SKIP'; Detail = 'No isolated localhost scratch share supplied.' })
        Write-Host "SKIP $Name"
        return
    }
    $caseRoot = Join-Path $root ([guid]::NewGuid().ToString())
    $script:Source = Join-Path $caseRoot 'source'
    $script:Destination = Join-Path $caseRoot 'destination'
    [void][IO.Directory]::CreateDirectory($script:Source)
    [void][IO.Directory]::CreateDirectory($script:Destination)
    $script:Mode = 'copy'
    $script:Calls = [Collections.Generic.List[object]]::new()
    try {
        & $Body
        Assert-Clean
        $script:Results.Add([pscustomobject]@{ Name = $Name; Status = 'PASS'; Detail = '' })
        Write-Host "PASS $Name"
    } catch {
        $script:Results.Add([pscustomobject]@{ Name = $Name; Status = 'FAIL'; Detail = $_.Exception.Message })
        Write-Host "FAIL ${Name}: $($_.Exception.Message)"
    }
}

try {
    Test-Case 'Parameter binding preserves default, positional paths, and existing switches' {
        # Bind only the real parameter block. Do not execute the production default or installer.
        $bind = [scriptblock]::Create($ast.ParamBlock.Extent.Text +
            "`n[pscustomobject]@{ Paths = `$Path; Destination = `$Destination; Install = `$Install; FromExplorer = `$FromExplorer }")
        $bound = & $bind 'first.mkv' 'second.mkv' -FromExplorer
        Assert (($bound.Paths -join '|') -eq 'first.mkv|second.mkv') 'Positional file binding changed.'
        Assert ($bound.Destination -eq '\\10.10.20.3\clips') 'Production default changed.'
        Assert ([bool]$bound.FromExplorer) 'Explorer switch binding changed.'
        Assert ([bool](& $bind -Install).Install) 'Install switch binding changed.'
        $bound = & $bind -Destination $script:Destination 'first.mkv' 'second.mkv'
        Assert ($bound.Destination -eq $script:Destination -and $bound.Paths.Count -eq 2) 'Destination override consumes a selected path.'
    }
    Test-Case 'Real Robocopy: published SHA-256 matches and original is deleted' {
        $file = New-Clip
        $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        $result = Invoke-Upload @($file) -Real
        Assert ($null -eq $result.Error) $result.Error
        $target = Join-Path $script:Destination ([IO.Path]::GetFileName($file))
        Assert ((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash -eq $hash) 'Published hash differs.'
        Assert (-not [IO.File]::Exists($file)) 'Verified original was not deleted.'
    }
    Test-Case 'Real Robocopy: empty file and multiple positional selections' {
        $first = New-Clip 'empty.mkv' ''
        $second = New-Clip 'second.mkv'
        $result = Invoke-Upload @($first, $second) -Real
        Assert ($null -eq $result.Error) $result.Error
        Assert-Content (Join-Path $script:Destination 'empty.mkv') ''
        Assert-Content (Join-Path $script:Destination 'second.mkv')
        Assert (-not [IO.File]::Exists($first) -and -not [IO.File]::Exists($second)) 'Originals remain.'
    }
    Test-Case 'Existing destination and duplicate selections preserve skipped originals' {
        $file = New-Clip
        $target = Join-Path $script:Destination ([IO.Path]::GetFileName($file))
        [IO.File]::WriteAllText($target, 'existing upload')
        $result = Invoke-Upload @($file, $file)
        Assert ($null -eq $result.Error) $result.Error
        Assert-Content $file
        Assert-Content $target 'existing upload'
        Assert ($script:Calls.Count -eq 0) 'Skipped files reached Robocopy.'
        Assert ($result.Output -match 'Skipped existing or duplicate name:') 'Missing skip warning.'
    }
    Test-Case 'Same basename: first wins and second original remains (case insensitive)' {
        $first = New-Clip 'clip.mkv'
        $other = [IO.Directory]::CreateDirectory((Join-Path $script:Source 'other')).FullName
        $second = Join-Path $other 'CLIP.mkv'
        [IO.File]::WriteAllText($second, 'second recording')
        $result = Invoke-Upload @($first, $second)
        Assert ($null -eq $result.Error) $result.Error
        Assert (-not [IO.File]::Exists($first)) 'First selection did not complete.'
        Assert-Content $second 'second recording'
        Assert-Content (Join-Path $script:Destination 'clip.mkv')
        Assert ($result.Output -match 'Skipped existing or duplicate name:') 'Missing duplicate warning.'
    }
    Test-Case 'Repeated same path transfers and verifies only once' {
        $file = New-Clip
        $result = Invoke-Upload @($file, $file)
        Assert ($null -eq $result.Error) $result.Error
        Assert ($script:Calls.Count -eq 1 -and $script:Calls[0].Names.Count -eq 1) 'Repeated path was copied twice.'
        Assert (-not [IO.File]::Exists($file)) 'First selection did not complete.'
        Assert-Content (Join-Path $script:Destination ([IO.Path]::GetFileName($file)))
    }
    Test-Case 'Batches only selected files once per source directory' {
        $first = New-Clip 'one.mkv'
        $second = New-Clip 'two.mkv'
        $unselected = New-Clip 'unselected.mkv'
        $other = [IO.Directory]::CreateDirectory((Join-Path $script:Source 'other')).FullName
        $third = Join-Path $other 'three.mkv'
        [IO.File]::WriteAllText($third, 'disposable recording bytes')
        $result = Invoke-Upload @($first, $second, $third)
        Assert ($null -eq $result.Error) $result.Error
        Assert ($script:Calls.Count -eq 2) 'Expected one invocation per directory.'
        Assert (($script:Calls | Where-Object { $_.Names.Count -eq 2 }).Count -eq 1) 'Same-directory files were not batched.'
        Assert-Content $unselected
        Assert (-not [IO.File]::Exists((Join-Path $script:Destination 'unselected.mkv'))) 'Unselected file was uploaded.'
        foreach ($file in @($first, $second, $third)) {
            Assert (-not [IO.File]::Exists($file)) 'Selected original remains.'
            Assert-Content (Join-Path $script:Destination ([IO.Path]::GetFileName($file)))
        }
    }
    foreach ($faultMode in @('exit8', 'exit16', 'short', 'missing', 'mismatch', 'collision', 'replace')) {
        Test-Case "Injected $faultMode preserves original and cleans staging" {
            $file = New-Clip
            $script:Mode = $faultMode
            $result = Invoke-Upload @($file)
            $target = Join-Path $script:Destination ([IO.Path]::GetFileName($file))
            switch ($faultMode) {
                'exit8' { Assert-Failure $result 'Robocopy failed.*exit 8' }
                'exit16' { Assert-Failure $result 'Robocopy failed.*exit 16' }
                'short' { Assert-Failure $result 'Incomplete copy of' }
                'missing' { Assert-Failure $result ([regex]::Escape([IO.Path]::GetFileName($file))) }
                'mismatch' { Assert-Failure $result 'Could not complete verified removal.*does not match' }
                'collision' { Assert-Failure $result '.+'; Assert-Content $target 'concurrent upload' }
                'replace' {
                    Assert-Failure $result 'Could not complete verified removal.*does not match'
                    Assert-Content $file 'replacement recording XYZZ'
                    Assert-Content "$file.saved"
                }
            }
            if ($faultMode -ne 'replace') { Assert-Content $file }
            if ($faultMode -in @('exit8', 'exit16', 'short', 'missing')) {
                Assert (-not [IO.File]::Exists($target)) 'Failed transfer published a file.'
            }
            if ($faultMode -in @('mismatch', 'replace')) { Assert ([IO.File]::Exists($target)) 'Published copy was unexpectedly removed.' }
        }
    }
    Test-Case 'Robocopy exit 7 still requires verification and permits a matching copy' {
        $script:Mode = 'exit7'
        $file = New-Clip
        $result = Invoke-Upload @($file)
        Assert ($null -eq $result.Error) $result.Error
        Assert (-not [IO.File]::Exists($file)) 'Nonfailure Robocopy status rejected.'
        Assert-Content (Join-Path $script:Destination ([IO.Path]::GetFileName($file)))
    }
    Test-Case 'Real Robocopy: named NTFS stream retains original and reports why' {
        $file = New-Clip
        [IO.File]::WriteAllText("${file}:metadata", 'unverified metadata')
        $result = Invoke-Upload @($file) -Real
        Assert-Failure $result 'Could not complete verified removal.*additional data streams'
        Assert-Content $file
        Assert ([IO.File]::ReadAllText("${file}:metadata") -ceq 'unverified metadata') 'Original named stream changed.'
        Assert-Content (Join-Path $script:Destination ([IO.Path]::GetFileName($file)))
    }
    Test-Case 'Open writer prevents verified removal' {
        $file = New-Clip
        $target = Join-Path $script:Destination 'copy.mkv'
        [IO.File]::Copy($file, $target)
        $writer = [IO.FileStream]::new($file, 'Open', 'ReadWrite', 'ReadWrite')
        try {
            $message = $null
            try { Remove-VerifiedOriginal (Get-Item -LiteralPath $file) $target } catch { $message = $_.Exception.Message }
            Assert ($null -ne $message) 'Verification accepted a concurrently writable source.'
            Assert-Content $file
        } finally { $writer.Dispose() }
    }
    Test-Case 'Destination read lock blocks flush and preserves source' {
        $file = New-Clip
        $target = Join-Path $script:Destination 'copy.mkv'
        [IO.File]::Copy($file, $target)
        $reader = [IO.FileStream]::new($target, 'Open', 'Read', 'Read')
        try {
            $message = $null
            try { Remove-VerifiedOriginal (Get-Item -LiteralPath $file) $target } catch { $message = $_.Exception.Message }
            Assert ($null -ne $message) 'Verification accepted a destination it cannot flush.'
            Assert-Content $file
        } finally { $reader.Dispose() }
    }
    Test-Case 'Length mismatch in verifier retains source' {
        $file = New-Clip
        $target = Join-Path $script:Destination 'copy.mkv'
        [IO.File]::WriteAllText($target, 'short')
        $message = $null
        try { Remove-VerifiedOriginal (Get-Item -LiteralPath $file) $target } catch { $message = $_.Exception.Message }
        Assert ($message -match 'does not match') 'Length mismatch was not rejected.'
        Assert-Content $file
    }
    Test-Case 'Relative selected path resolves to the same file and completes' {
        $file = New-Clip
        Push-Location $script:Source
        try { $result = Invoke-Upload @('.\clip [1].mkv') -Real } finally { Pop-Location }
        Assert ($null -eq $result.Error) $result.Error
        Assert (-not [IO.File]::Exists($file)) 'Resolved local original remains.'
        Assert-Content (Join-Path $script:Destination 'clip [1].mkv')
    }
    Test-Case 'Directory junction resolves elsewhere and retains source' {
        $file = New-Clip
        $junction = Join-Path (Split-Path $script:Source) 'alias'
        [void](New-Item -ItemType Junction -Path $junction -Target $script:Source)
        try {
            $result = Invoke-Upload @((Join-Path $junction ([IO.Path]::GetFileName($file)))) -Real
            Assert-Failure $result 'selected path resolves to a different location'
            Assert-Content $file
            Assert-Content (Join-Path $script:Destination ([IO.Path]::GetFileName($file)))
        } finally { [IO.Directory]::Delete($junction) }
    }
    Test-Case 'Deletion handle rejects replacement while open and cannot delete a later file' {
        # Load the actual native helper through a successful verification first.
        $warmup = New-Clip 'warmup.mkv'
        $target = Join-Path $script:Destination 'warmup.mkv'
        [IO.File]::Copy($warmup, $target)
        Remove-VerifiedOriginal (Get-Item -LiteralPath $warmup) $target
        $file = New-Clip
        $rights = [Security.AccessControl.FileSystemRights]::Read -bor [Security.AccessControl.FileSystemRights]::Delete
        $handle = [IO.FileStream]::new($file, 'Open', $rights, 'Read', 4096, [IO.FileOptions]::None)
        try {
            $blocked = $false
            try { [IO.File]::Move($file, "$file.saved") } catch { $blocked = $true }
            Assert $blocked 'Replacement unexpectedly succeeded while the verification handle was open.'
            [ClipsVerifiedOriginal]::MarkForDeletion($handle, $file)
        } finally { $handle.Dispose() }
        Assert (-not [IO.File]::Exists($file)) 'The verified handle was not deleted.'
        [IO.File]::WriteAllText($file, 'later recording')
        Assert-Content $file 'later recording'
    }
    Test-Case 'Missing selection fails before any transfer' {
        $file = New-Clip
        $result = Invoke-Upload @($file, (Join-Path $script:Source 'missing.mkv'))
        Assert-Failure $result 'missing.mkv'
        Assert-Content $file
        Assert ($script:Calls.Count -eq 0) 'Transfer started before selection validation completed.'
    }
    Test-Case 'Empty selection and directory selection report errors' {
        Assert-Failure (Invoke-Upload @()) 'Select one or more clip files'
        Assert-Failure (Invoke-Upload @($script:Source)) 'Select a file:'
        Assert ($script:Calls.Count -eq 0) 'Invalid selection reached Robocopy.'
    }
    Test-Case 'UNC source is copied but retained' -Network {
        $networkCase = Join-Path $NetworkRoot ('clips-regression-' + [guid]::NewGuid())
        [void][IO.Directory]::CreateDirectory($networkCase)
        try {
            $file = Join-Path $networkCase 'network.mkv'
            [IO.File]::WriteAllText($file, 'network recording')
            $result = Invoke-Upload @($file) -Real
            Assert ($null -eq $result.Error) $result.Error
            Assert-Content $file 'network recording'
            Assert-Content (Join-Path $script:Destination 'network.mkv') 'network recording'
            Assert ($result.Output -match 'Copied network file; kept original:') 'Missing network preservation warning.'
        } finally { [IO.Directory]::Delete($networkCase, $true) }
    }
    Test-Case 'Mapped network source is copied but retained' -Network {
        $letter = 90..68 | ForEach-Object { [string][char]$_ } | Where-Object {
            -not (Get-PSDrive -Name $_ -ErrorAction SilentlyContinue) -and
            -not ([IO.Directory]::Exists("${_}:\"))
        } | Select-Object -First 1
        Assert ($null -ne $letter) 'No unused drive letter for the isolated network test.'
        $networkCase = Join-Path $NetworkRoot ('clips-regression-' + [guid]::NewGuid())
        [void][IO.Directory]::CreateDirectory($networkCase)
        $network = New-Object -ComObject WScript.Network
        $mapped = $false
        try {
            # This optional test creates only a temporary, nonpersistent user mapping.
            $network.MapNetworkDrive("${letter}:", $networkCase, $false)
            $mapped = $true
            $file = "${letter}:\mapped.mkv"
            [IO.File]::WriteAllText($file, 'network recording')
            Assert ([IO.DriveInfo]::new("${letter}:\").DriveType -eq [IO.DriveType]::Network) 'Expected a Windows network drive.'
            $result = Invoke-Upload @($file) -Real
            Assert ($null -eq $result.Error) $result.Error
            Assert-Content $file 'network recording'
            Assert-Content (Join-Path $script:Destination 'mapped.mkv') 'network recording'
            Assert ($result.Output -match 'Copied network file; kept original:') 'Missing network preservation warning.'
        } finally {
            if ($mapped) { $network.RemoveNetworkDrive("${letter}:", $false, $false) }
            [IO.Directory]::Delete($networkCase, $true)
        }
    }
} finally {
    # Delete only this run's newly created fixtures, never a caller-supplied directory.
    [IO.Directory]::Delete($root, $true)
}
$script:Results | Format-Table -AutoSize -Wrap
$passed = @($script:Results | Where-Object Status -eq 'PASS').Count
$failed = @($script:Results | Where-Object Status -eq 'FAIL').Count
$skipped = @($script:Results | Where-Object Status -eq 'SKIP').Count
Write-Host "Results: $passed passed, $failed failed, $skipped unexecuted."
if ($failed) { exit 1 }
