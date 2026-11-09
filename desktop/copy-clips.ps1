param(
    [switch]$Install,
    [switch]$FromExplorer,
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Path
)

$ErrorActionPreference = 'Stop'
$destination = '\\10.10.20.3\clips'

if ($Install) {
    $folder = Join-Path $env:LOCALAPPDATA 'HomelabAnsible'
    $script = Join-Path $folder 'copy-clips.ps1'
    $link = Join-Path ([Environment]::GetFolderPath('SendTo')) 'Clips.lnk'
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
    $powershell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    $arguments = '-NoProfile -ExecutionPolicy RemoteSigned -File "' + $script + '" -FromExplorer'
    if ([IO.File]::Exists($link) -and ($shortcut.TargetPath -ne $powershell -or $shortcut.Arguments -ne $arguments)) {
        throw "A different Clips shortcut already exists at $link"
    }
    [void][IO.Directory]::CreateDirectory($folder)
    if ($PSCommandPath -ne $script) { [IO.File]::Copy($PSCommandPath, $script, $true) }
    $shortcut.TargetPath = $powershell
    $shortcut.Arguments = $arguments
    $shortcut.Description = 'Copy selected files to Clips with Robocopy'
    $shortcut.Save()
    return
}

$skipped = $false
$stage = $null
try {
    if (-not $Path) { throw 'Select one or more clip files, or run this script with -Install.' }
    foreach ($item in $Path) {
        $file = Get-Item -LiteralPath $item
        if ($file -isnot [IO.FileInfo]) { throw "Select a file: $item" }
        $target = [IO.Path]::Combine($destination, $file.Name)
        if (Test-Path -LiteralPath $target) {
            Write-Warning "Skipped existing name: $target"
            $skipped = $true
            continue
        }
        if (-not $stage) {
            # Keep interrupted copies out of the final filename. Rename on the same share.
            $stage = (New-Item -Path $destination -Name ('.clips-upload-' + [guid]::NewGuid()) -ItemType Directory).FullName
        }
        $partial = [IO.Path]::Combine($stage, $file.Name)
        try {
            $sourceFolder = [IO.Path]::Combine($file.DirectoryName, '.')
            & "$env:SystemRoot\System32\robocopy.exe" $sourceFolder $stage $file.Name /J /R:1 /W:1 /COPY:DAT
            if ($LASTEXITCODE -ge 8) { throw "Robocopy failed for $item (exit $LASTEXITCODE)." }
            if ((Get-Item -LiteralPath $partial).Length -ne $file.Length) { throw "Incomplete copy of $item" }
            [IO.File]::Move($partial, $target)
        } finally {
            [IO.File]::Delete($partial)
        }
    }
} catch {
    if ($FromExplorer) {
        Write-Warning $_.Exception.Message
        [void](Read-Host 'Press Enter to close')
    }
    throw
} finally {
    if ($stage) { [IO.Directory]::Delete($stage) }
}
if ($FromExplorer -and $skipped) { [void](Read-Host 'Press Enter to close') }
