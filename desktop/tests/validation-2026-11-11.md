# Clips regression validation — 2026-11-11

This is a dated isolated test result, not an assessment of the live gaming PC.

| Run | Passed | Failed | Unexecuted | Exit code |
| --- | ---: | ---: | ---: | ---: |
| Original harness | 21 | 5 | 0 | 1 |
| Corrected harness | 26 | 0 | 0 | 0 |

## Environment and isolation

- Microsoft Windows Server 2022 Standard Evaluation, x64, build 20348.
- Windows PowerShell 5.1.20348.558 Desktop, local NTFS, Robocopy 10.0.20348.1.
- QEMU 11.1.3 with TCG on macOS. Fresh 40 GiB sparse disk and read-only test ISO.
- Initial run had no NIC. The successful run used one emulated NIC connected
  only to a QEMU internal hub, with no NAT, bridge, host network, or default route.
- Both network cases used a temporary `\\localhost\ClipsRegression` share
  inside the guest. No real recordings, production share, or homelab credentials
  were supplied. The guest share and test fixtures were removed after the run.

The VM shut down normally after testing. Its temporary disk, installation media,
and generated guest setup credentials were then removed. Only evidence logs
remain outside the repository.

The installation ISO came from the
[Microsoft Evaluation Center](https://www.microsoft.com/en-us/evalcenter/download-windows-server-2022).
Its SHA-256 was
`3e4fa6d8507b554856fc9ca6079cc402df11a8b79344871669f0251535255325`.

## Failures and corrections

1. The batching assertion read `.Count` from a single `PSCustomObject`, which
   does not provide that count in Windows PowerShell 5.1. Wrap the filtered
   result in `@(...)` before checking the count.
2. .NET Framework `File.WriteAllText` rejected the alternate-stream path.
   Use the filesystem provider's `Set-Content -Stream` and `Get-Content -Stream`
   to create and inspect the actual NTFS stream.
3. The writer-lock case correctly rejected verified removal, but its own
   `ReadAllText` check conflicted with the still-open writer. Check retained
   contents after disposing the test's writer handle.
4. Both SMB cases failed with an unreachable network location when the VM had
   no NIC. Attach an internal-only virtual NIC to the disposable guest. No
   production code or network preservation assertions changed.

`desktop/copy-clips.ps1` remained byte-for-byte unchanged during this validation.
The corrected harness still executes real Robocopy and Windows deletion APIs.
Fault injection changes only the Robocopy dispatch in memory.

## Successful invocation

The disposable guest runner created the scratch share, then invoked a fresh
Windows PowerShell process:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\ClipsRun\tests\copy-clips.Tests.ps1 -NetworkRoot '\\localhost\ClipsRegression'
```

The runner used the temporary guest Administrator account. It removed the share
in `finally`. The execution-policy override applied only to that test process.
Guest-reported SHA-256 values matched the local files:

- `copy-clips.ps1`: `eca12aa00edc02d54aa26b875a94468f4e4e3d62308e54da930370ee27dd6b13`
- `tests/copy-clips.Tests.ps1`: `f368e286d518d3617c3e6410a74d75d18e7968245c30d66fd5269a9fbc5d8b3d`

## Final case results

```text
PASS Parameter binding preserves default, positional paths, and existing switches
PASS Real Robocopy: published SHA-256 matches and original is deleted
PASS Real Robocopy: empty file and multiple positional selections
PASS Existing destination and duplicate selections preserve skipped originals
PASS Same basename: first wins and second original remains (case insensitive)
PASS Repeated same path transfers and verifies only once
PASS Batches only selected files once per source directory
PASS Injected exit8 preserves original and cleans staging
PASS Injected exit16 preserves original and cleans staging
PASS Injected short preserves original and cleans staging
PASS Injected missing preserves original and cleans staging
PASS Injected mismatch preserves original and cleans staging
PASS Injected collision preserves original and cleans staging
PASS Injected replace preserves original and cleans staging
PASS Robocopy exit 7 still requires verification and permits a matching copy
PASS Real Robocopy: named NTFS stream retains original and reports why
PASS Open writer prevents verified removal
PASS Destination read lock blocks flush and preserves source
PASS Length mismatch in verifier retains source
PASS Relative selected path resolves to the same file and completes
PASS Directory junction resolves elsewhere and retains source
PASS Deletion handle rejects replacement while open and cannot delete a later file
PASS Missing selection fails before any transfer
PASS Empty selection and directory selection report errors
PASS UNC source is copied but retained
PASS Mapped network source is copied but retained
Results: 26 passed, 0 failed, 0 unexecuted.
```

## Limits

This validates the recorded Windows Server environment and localhost SMB.
Windows 11 on the gaming PC, standard-user execution, the production SMB server,
Explorer UI, installation of the Send To shortcut, power loss, and forced-process
termination were not tested. Transfer interruptions were injected Robocopy
failures. No production deployment is implied by this result.
