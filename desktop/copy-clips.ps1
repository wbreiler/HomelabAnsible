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
    $names = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $files = @(foreach ($item in $Path) {
        $file = Get-Item -LiteralPath $item
        if ($file -isnot [IO.FileInfo]) { throw "Select a file: $item" }
        $target = [IO.Path]::Combine($destination, $file.Name)
        if ((Test-Path -LiteralPath $target) -or -not $names.Add($file.Name)) {
            Write-Warning "Skipped existing or duplicate name: $target"
            $skipped = $true
            continue
        }
        $file
    })
    if ($files) {
        # Publish completed files with a same-share rename that cannot overwrite a concurrent copy.
        $stage = (New-Item -Path $destination -Name ('.clips-upload-' + [guid]::NewGuid()) -ItemType Directory).FullName
    }
    foreach ($folder in ($files | Group-Object -Property DirectoryName)) {
        $sourceFolder = [IO.Path]::Combine($folder.Name, '.')
        $selected = @($folder.Group | ForEach-Object { $_.Name })
        & "$env:SystemRoot\System32\robocopy.exe" $sourceFolder $stage @selected /J /MT:1 /R:1 /W:1 /COPY:DAT
        if ($LASTEXITCODE -ge 8) { throw "Robocopy failed for $sourceFolder (exit $LASTEXITCODE)." }
        foreach ($file in $folder.Group) {
            $partial = [IO.Path]::Combine($stage, $file.Name)
            $target = [IO.Path]::Combine($destination, $file.Name)
            if ((Get-Item -LiteralPath $partial).Length -ne $file.Length) { throw "Incomplete copy of $($file.FullName)" }
            [IO.File]::Move($partial, $target)
        }
    }
} catch {
    if ($FromExplorer) {
        Write-Warning $_.Exception.Message
        [void](Read-Host 'Press Enter to close')
    }
    throw
} finally {
    if ($stage) {
        foreach ($partial in [IO.Directory]::GetFiles($stage)) {
            if ($names.Contains([IO.Path]::GetFileName($partial))) {
                [IO.File]::SetAttributes($partial, [IO.FileAttributes]::Normal)
                [IO.File]::Delete($partial)
            }
        }
        [IO.Directory]::Delete($stage)
    }
}
if ($FromExplorer -and $skipped) { [void](Read-Host 'Press Enter to close') }
