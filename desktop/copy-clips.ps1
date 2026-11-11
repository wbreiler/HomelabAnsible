param(
    [switch]$Install,
    [switch]$FromExplorer,
    [ValidateNotNullOrEmpty()]
    [string]$Destination = '\\10.10.20.3\clips',
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$Path
)

$ErrorActionPreference = 'Stop'

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
    $shortcut.Description = 'Move local files to Clips after verifying the uploaded contents'
    $shortcut.Save()
    return
}

function Remove-VerifiedOriginal([IO.FileInfo]$File, [string]$Target) {
    # A normal path-based deletion could remove a replacement after we close the verified file.
    if (-not ('ClipsVerifiedOriginal' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class ClipsVerifiedOriginal {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetFinalPathNameByHandle(SafeFileHandle handle, StringBuilder path, uint size, uint flags);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetFileInformationByHandle(SafeFileHandle handle, int infoClass, ref byte value, uint size);

    public static void MarkForDeletion(FileStream verified, string selectedPath) {
        var path = new StringBuilder(32768);
        uint length = GetFinalPathNameByHandle(verified.SafeFileHandle, path, (uint)path.Capacity, 0);
        if (length == 0) throw new Win32Exception();
        if (!String.Equals(path.ToString(), @"\\?\" + selectedPath, StringComparison.OrdinalIgnoreCase))
            throw new IOException("The selected path resolves to a different location. Original retained.");
        const int FileDispositionInfo = 4;
        byte delete = 1;
        if (!SetFileInformationByHandle(verified.SafeFileHandle, FileDispositionInfo, ref delete, 1))
            throw new Win32Exception();
    }
}
'@
    }
    $rights = [Security.AccessControl.FileSystemRights]::Read -bor [Security.AccessControl.FileSystemRights]::Delete
    $copy = [IO.FileStream]::new($Target, 'Open', [IO.FileAccess]::ReadWrite, 'Read', 4MB, [IO.FileOptions]::SequentialScan)
    try {
        $copy.Flush($true)
        $original = [IO.FileStream]::new($File.FullName, 'Open', $rights, 'Read', 4MB, [IO.FileOptions]::SequentialScan)
        try {
            $extraStreams = Get-Item -LiteralPath $File.FullName -Stream * | Where-Object Stream -ne ':$DATA'
            if ($extraStreams) { throw 'The original has additional data streams that have not been verified.' }
            $hash = [Security.Cryptography.SHA256]::Create()
            try {
                if ($original.Length -ne $copy.Length -or
                    [BitConverter]::ToString($hash.ComputeHash($original)) -ne [BitConverter]::ToString($hash.ComputeHash($copy))) {
                    throw 'The uploaded file does not match the original.'
                }
            } finally { $hash.Dispose() }
            [ClipsVerifiedOriginal]::MarkForDeletion($original, $File.FullName)
        } finally { $original.Dispose() }
    } finally { $copy.Dispose() }
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
            if ($file.FullName -notmatch '^[a-z]:\\' -or
                [IO.DriveInfo]::new($file.Directory.Root.FullName).DriveType -eq [IO.DriveType]::Network) {
                Write-Warning "Copied network file; kept original: $($file.FullName)"
                $skipped = $true
                continue
            }
            try { Remove-VerifiedOriginal $file $target }
            catch { throw "Could not complete verified removal of $($file.FullName): $($_.Exception.Message)" }
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
