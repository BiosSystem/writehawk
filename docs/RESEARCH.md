# Research notes

What the design rests on, how each point was checked, and where it came from.
Anything not run on a real machine is marked unverified. Update this file when
a claim is re-tested or a vendor ships a fix.

Last reviewed: 2026-11-21.

## Vendor bugs that motivated the project

### NVIDIA Display Container log rewrite

| | |
|---|---|
| Process | `NVDisplay.Container.exe` (service `NVDisplay.ContainerLocalSystem`) |
| File | `%ProgramData%\NVIDIA Corporation\nvtopps\nct\nvlog.nvlgstg` |
| Affected | GeForce drivers 621.14 and 621.24 |
| Fixed in | Hotfix 621.35, released 2026-11-20, NVIDIA bug 7116722 |
| Reported scale | Up to 30 GB per hour in the worst reports; most reports are lower |

Not every system on an affected driver shows the behaviour. A registry value
that disables the `_nvtopps` container plugin (`DisableLoad = 1` under the
service's `Parameters\LocalSystem\_nvtopps` key) stopped the writes on one
affected machine. NVIDIA does not document that value, so it is a workaround
candidate, not a vendor fix.

Sources:
- https://www.nvidia.com/en-us/geforce/forums/game-ready-drivers/13/592907/continuous-writing-of-gigabytes-to-ssd-to-nvtopps-/
- https://wccftech.com/nvidia-releases-gpu-hotfix-driver-621-35-fixes-excessive-ssd-writes/
- https://www.guru3d.com/download/geforce-hotfix-driver-62135-download/
- https://hothardware.com/news/nvidia-latest-gpu-drivers-write-ssds

### AMD External Events Utility dump files

| | |
|---|---|
| Process | `atiesrxx.exe` / `atieclxx.exe` (service `AMD External Events Utility`) |
| Files | `EeuDumps` folder, under `%SystemRoot%\System32\AMD` or the `amdfendr` driver store folder depending on driver version |
| Trigger | Idle, and moving or resizing windows |
| Fixed in | Adrenalin 26.11.1 (2026-11-12) for RX 7000 and newer; 26.11.2 (2026-11-18) for RX 5000 and 6000 |

Nothing is stated for adapters older than RX 5000 or for integrated graphics.
AMD's notes are reported not to name the service or the folder; that link
comes from press and users. Disabling the
service stops the writes but is reported to affect FreeSync and hotkeys when the
AMD adapter drives a display.

Sources:
- https://www.igorslab.de/en/amd-adrenalin-26-11-1-fixes-excessive-ssd-writes-radeon-rx-7000-rx-9000/
- https://www.techspot.com/news/114496-amd-confirms-gpu-driver-bug-writing-data-continuously.html

### Windows versions

Both bugs concern Windows 10 as well as Windows 11. The NVIDIA hotfix is a
single package for both. AMD's 26.11.2 notes name Windows 10 for the RX 5000
and RX 6000 fix, and the dump-file writes are reported on Windows 10 22H2 and
LTSC. No source ties either bug to a Windows 11 feature; AMD staff are quoted
blaming an interaction between `atieclxx.exe` and a Microsoft PCIe filter
driver. All of this is from press and user reports: the vendor pages could not
be opened when it was checked.

Sources:
- https://www.back2gaming.com/news/nvidia-geforce-hotfix-display-driver-621-35-released/
- https://www.guru3d.com/story/amd-adrenalin-26112-fixes-more-radeon-ssd-writes-and-game-crashes/
- https://windowsforum.com/news/amd-radeon-ssd-write-bug-how-to-check-atieclxx-exe-on-windows-10-and-11.450605/

### Why a published fix does not reach every machine

| Reason | Basis | Local check |
|---|---|---|
| NVIDIA hotfix drivers are a separate manual download and are folded into the next regular driver | Vendor wording as quoted by press | Installed release is 621.14 or 621.24 |
| AMD's first fix was an Optional release while an older one stayed Recommended | Vendor download page as quoted in search results | Installed release older than 26.11.1 |
| AMD's fix arrived per adapter generation: RX 7000 and newer in 26.11.1, RX 5000 and 6000 in 26.11.2, nothing stated for older or integrated adapters | Press | Adapter device id |
| Windows Update installs the best-ranked driver, not the newest; rank is signature, feature and identifier score, with date and version only breaking ties | Microsoft documentation | Driver provider and date |
| Policy `ExcludeWUDriversInQualityUpdate` keeps drivers out of Windows Update | Microsoft documentation | The policy value |
| Notebook and prebuilt makers ship their own driver builds, and vendors point owners to those | Vendor recommendation; the delay itself is not verified | Battery present, system maker |
| No vendor updater installed, as with a driver that came from Windows Update | Follows from the above | Installed program names |

Seen on the development machine: an adapter of one vendor with that vendor's
updater installed and still on an affected release, because the fix is a
hotfix; and an integrated adapter of the other vendor on a two year old
release with no updater installed.

Sources:
- https://learn.microsoft.com/en-us/windows-hardware/drivers/install/how-windows-selects-a-driver-for-a-device
- https://learn.microsoft.com/en-us/windows/client-management/mdm/policy-csp-update
- https://nvidia.custhelp.com/app/answers/detail/a_id/5940

### Builds the suite has run on

| Build | Where | Result |
|---|---|---|
| 10.0.26300, Windows 11 | Development machine, standard user | Host suite passes; elevated tests skip |
| 10.0.26100, Windows 11 | Windows Sandbox, elevated | Full suite and ten repeats of the live tests pass |
| Windows Server 2025 | Hosted runner, elevated | Suite passes, including the live trace tests |
| 10.0.20348, Windows Server 2022 | Hosted runner, elevated | Suite passes, including the live trace tests |
| Windows 10 desktop | Not run | |

Server 2022 shares its kernel line with Windows 10, which is the nearest
evidence so far that the trace and the handle lookup work there.

### Unverified

Write loops have been claimed for other vendor utilities (system control
suites, peripheral software, sync clients). None has been checked here and none
is in the rule catalog until someone records a trace of it.

## Windows API facts

### Process I/O counters

`GetProcessIoCounters` works with `PROCESS_QUERY_LIMITED_INFORMATION`. The
transfer counts cover every read and write call the process makes, including
pipes, sockets and devices. Verified: a process that wrote 3,276,800 bytes to a
pipe and nothing to disk showed a write counter delta of exactly 3,276,800.

Opening services from a standard user account fails with access denied. On the
development machine a standard user could read 197 of 473 processes.

### Volume counters

`IOCTL_DISK_PERFORMANCE` on `\\.\C:` (or `\\.\PhysicalDriveN`) works with a
handle opened with no access rights, so no elevation is needed. Verified.

### Kernel-File ETW provider

Provider `Microsoft-Windows-Kernel-File`,
GUID `{EDD08927-9CC4-4E65-B970-C2560FB5C289}`.

Keywords used: `FILENAME 0x10`, `CREATE 0x80`, `WRITE 0x200`. `FILEIO 0x20` is
left out on purpose: it also enables read events.

Payload layouts, from the provider manifest
(`(Get-WinEvent -ListProvider Microsoft-Windows-Kernel-File).Events`), 64-bit:

| Event | Version | Fields in order |
|---|---|---|
| 10 NameCreate | 0 | FileKey ptr, FileName wide string |
| 12 Create, 30 CreateNewFile | 0 | Irp ptr, ThreadId ptr, FileObject ptr, CreateOptions u32, CreateAttributes u32, ShareAccess u32, FileName |
| 12 Create, 30 CreateNewFile | 1 | Irp ptr, FileObject ptr, IssuingThreadId u32, CreateOptions u32, CreateAttributes u32, ShareAccess u32, FileName |
| 16 Write | 0 | ByteOffset u64, Irp ptr, ThreadId ptr, FileObject ptr, FileKey ptr, IOSize u32, IOFlags u32 |
| 16 Write | 1 | ByteOffset u64, Irp ptr, FileObject ptr, FileKey ptr, IssuingThreadId u32, IOSize u32, IOFlags u32, ExtraFlags u32 |

Starting a session from a standard user returns access denied. Verified.

Run live, elevated, Windows 11 build 26300 (2026-11-21). Sessions delivered
100,000 to 480,000 events in about 40 seconds with no callback errors.

**I/O flags on write events.** 200 writes of 4 KB by one process, per file:

| Workload | Events from the writer | Events from System (pid 4) |
|---|---|---|
| Buffered rewrite | 199 with flags `0x0`, 1 with `0x60a00` | 1 with `0x60003` |
| Rewrite, flush each | 199 with `0x0`, 1 with `0x60a00`, 200 with `0x60043` | none |
| Buffered append | 199 with `0x0`, 16 with `0x60a00` | 2 with `0x60003`, 819,200 bytes together |

Reading, using the IRP flag values from the driver kit (`0x1` no cache, `0x2`
paging I/O, `0x40` synchronous paging I/O, `0x200` write operation):

- Flags 0 is the fast I/O path: no IRP exists.
- `0x60a00` is an ordinary IRP write. The first write to a file takes this path.
- `0x60043` is a flush issued in the writer's own context, one per `fsync`.
- `0x60003` is the lazy writer.
- The append shows 215 requested-write events for 200 writes: a fast I/O write
  that is refused (here, when the file must grow) is logged, then logged again
  as an IRP with the same thread, offset and size.

Counting every event as a write gave a ratio of 3000 for 1500 flushed rewrites
and 1.2 for an append. With paging writes counted as flushes and the repeat
dropped, three runs gave 5000, 1500 and 1.0 exactly.

**A flush also writes the file system log.** During the flushed rewrite the
writer's pid issued a second stream of about 200 paging writes, 995,328 bytes,
to an unnamed file key shared with System: about 4.9 KB per flush. Together
with the 4 KB of data that matches the 9 KB per write seen on the volume
counter. That stream is very likely the NTFS log; the trace does not name it.

**File keys are reused.** A probe that created and deleted three files in turn
showed 0.41 MB flushed for a file that had put 0.02 MB on the volume. The key
had been handed to a later file. After mapping each key to a new id on the
name-delete event (id 11) the figure is 0.00 MB in three runs.

**Files opened before the session are not named.** A file opened before the
session started, then written 50 times during it, produced write events with a
file object and file key but no event anywhere containing its name. Checked
with every provider keyword enabled (`0x1fff`), with a capture-state request
(`EnableTraceEx2` control code 2, which returned success), and through closing
the handle.

**The handle table names them.** `NtQuerySystemInformation` class 64 lists
every handle with its owning pid and object address. The address equals the
file object in the write event, so the writer's handle can be found,
duplicated and asked for its path. Verified in Windows Sandbox on build 26100
for a file held by the tracing process itself, by another process of the same
user, and by a process running as SYSTEM (started from a scheduled task), all
opened before the session.

`writehawk trace` in the same sandbox named four event log files that the event
log service had held open since boot, which is the real case the lookup is for.

Limits seen in the same runs: object addresses read as zero for a standard
user, so the lookup needs elevation; files written by the Registry and System
processes through kernel handles (hives among them) and files of processes
that had exited stayed unnamed.

On one Windows Server machine a file opened before the session was already
named correctly by the trace's own events, before any handle lookup. Why that
build names it is not known; the lookup stays, since desktop builds 26100 and
26300 do not.

**Events can arrive late.** Buffers are per processor. With the default
settings, 80 writes by a second process were not delivered within 2.5 seconds
and appeared only when the session stopped, while writes by the tracing
process itself arrived in time. A fixed 0.3 second wait after a flush request
(`ControlTrace` code 3) was not enough either: a lookup made straight after a
SYSTEM process's writes found nothing to look up. Waiting for one event
stamped after the request was not enough either: with the lookup test repeated
ten times in the sandbox, up to seven runs found the writer's events still
undelivered, because that one later event came from another processor's
buffer. The trace now sets a one second flush timer, and before reading it
repeats the flush request until a later-stamped event has arrived and no
earlier-stamped one has for 0.3 seconds. Ten of ten repeats then passed.

**A paging write can carry a recycled file object address.** In the same
repeats, up to three of ten runs named the file after a different file. The recorded
events showed why: the flush to disk (flags `0x60003` from the System process,
or `0x20043` in the writer) used a file object the writer never opened, at an
address that a failed open of another path had used shortly before, and the
trace had kept that open's name under the address. Paging writes are now named
by file key only. Ten of ten repeats then passed.

### Display adapters and display paths

All of this works for a standard user. Verified on Windows 11 builds 26100 and
26300.

- `CM_Get_Device_ID_List` with the display class GUID and the "present" filter
  lists the adapters. The device's key under `HKLM\SYSTEM\CurrentControlSet\Enum`
  holds a `Driver` value that names its key under `Control\Class`, where
  `DriverVersion`, `DriverDate` and `ProviderName` are.
- `QueryDisplayConfig` with only active paths, then `DisplayConfigGetDeviceInfo`
  for the adapter name, gives a device path that contains the same instance id
  with `#` in place of `\`. That is the join.
- The NVIDIA public version is the last five digits of the Windows driver
  version (`32.0.15.6094` is 560.94). The AMD driver key has
  `RadeonSoftwareVersion`. Both were read on a machine with one adapter of each
  vendor and gave current release numbers; neither was compared with the
  vendor's own tool.

Results:

| Machine | Reported |
|---|---|
| Desktop, discrete card with two monitors, integrated adapter with nothing connected | Discrete: drives 2 displays. Integrated: drives no display |
| Windows Sandbox | Remote display adapter: drives 1 display. Two virtual render adapters: drive no display |

The sandbox row matters for rules: "drives no display" is also true of
render-only adapters, so a rule must name the vendor or device it means and
not rely on that fact alone.

Not tested: a laptop with switchable graphics, a machine with a single
physical adapter, and a caller without a desktop session.

### Storage properties

`IOCTL_STORAGE_QUERY_PROPERTY` and `IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS` work
on a volume handle opened with no access rights, so no elevation is needed.
Verified on NVMe and SATA devices: NVMe reported bus 17, no seek penalty and
trim; a SATA hard disk reported bus 11, a seek penalty and no trim.

Two cases answer only in part. One volume returned its disk number and failed
every property query with `ERROR_INVALID_FUNCTION`. The sandbox's virtual disk
reported its bus and trim but no seek penalty. Both are reported as media
`unknown`.

### Idle and fullscreen state

`GetLastInputInfo` gives the tick of the last input in the caller's session;
the tick counter is 32 bits and wraps after about 49.7 days.
`SHQueryUserNotificationState` returns `QUNS_BUSY` when a window covers the
screen. Verified in Windows Sandbox: the state was `normal`, a borderless
topmost window covering the screen changed it to `busy` within the eight
seconds the test allows, and the test asserts both. Exclusive Direct3D fullscreen (`d3d_fullscreen`),
a locked session and a screen saver were not tested.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-querydisplayconfig
- https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_storage_query_property
- https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shqueryusernotificationstate

### File signatures and process images

`WinVerifyTrust` with the generic verify action checks an embedded signature.
A file without one fails with `TRUST_E_NOSIGNATURE`, or with
`TRUST_E_SUBJECT_FORM_UNKNOWN` when it is not a signable format; either way it
may still be signed through a system catalog, which is looked up by file hash
(`CryptCATAdminCalcHashFromFileHandle2`, `CryptCATAdminEnumCatalogFromHash`)
and verified as a catalog member. The signer name comes from the first
certificate of the first signer in the verified chain.

Verified as a standard user on Windows 11 build 26300, with revocation checks
off and URL retrieval limited to the cache:

| File | Result |
|---|---|
| `csrss.exe`, `smss.exe`, `wininit.exe`, `services.exe`, `lsass.exe`, `svchost.exe` in System32 | Embedded, signer "Microsoft Windows Publisher" |
| `winlogon.exe`, `dwm.exe`, `fontdrvhost.exe`, `explorer.exe` | Embedded, signer "Microsoft Windows" |
| `MsMpEng.exe` under Program Files and under the versioned platform folder | Embedded, signer "Microsoft Windows Publisher" |
| A copy of `notepad.exe` in a temp folder | Catalog, signer "Microsoft Windows" |
| A copy of `csrss.exe` in a temp folder | Embedded, valid, same signer as the original |
| A file with a few bytes and an `.exe` name | No signature |

The two copies are why the path is part of the match: a signature says who
built a file, not where it is supposed to run from. A check takes 3 to 20 ms.

`QueryFullProcessImageNameW` needs only `PROCESS_QUERY_LIMITED_INFORMATION`.
A standard user could identify about 200 of about 470 processes; the rest
could not be opened. Elevated in Windows Sandbox (build 26100), 81 of 84 processes were identified, 51 of them protected, and the real `csrss.exe`, `services.exe`, `lsass.exe` and `winlogon.exe` were all classified as protected.

Limits: the signer is matched by certificate subject name after the chain has
verified, not by pinning a root. Revocation is not checked. Not tested: a
listed path reached through a junction or a short name, and Windows 10.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/api/wintrust/nf-wintrust-winverifytrust
- https://learn.microsoft.com/en-us/windows/win32/api/mscat/nf-mscat-cryptcatadminenumcatalogfromhash

### Job object I/O rate control

`SetIoRateControlInformationJobObject` is documented by Microsoft as "no longer
supported" starting with Windows 10 version 1607. The export is still present
and the call succeeds on Windows 11 build 26300.

Measured there with a writer doing 4 KB writes, limit `MaxIops = 20`:

| Writer | Before limit | After limit |
|---|---|---|
| Write then flush | about 430 writes/s | 10 writes/s |
| Buffered write, no flush | about 670 writes/s | about 670 writes/s |

So the limit applies to I/O that reaches the storage stack on the caller's
behalf, and a buffered writer is not slowed. Whether the later cache flush is
limited was not measured. A process cannot be removed from a job once assigned;
only the limit can be lifted.

Sources:
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setioratecontrolinformationjobobject
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/ns-jobapi2-jobobject_io_rate_control_information

## Measurements

### Cost of rewrite and append workloads

`writehawk probe --dir <folder on a quiet volume>`, Windows 11 build 26300, NVMe
data volume, NTFS. Six runs in total, three as a standard user and three
elevated with the trace; idle baseline 0.03 to 0.27 MB per 8 seconds.

| Workload | Process counter | File size after | Volume writes | Traced ratio | Flushed to the file |
|---|---|---|---|---|---|
| Rewrite one 4 KB block 5000 times, buffered | 19.53 MB | 4 KB | 0.02 to 0.03 MB | 5000 | 0.00 MB |
| Rewrite one 4 KB block 1500 times, flush each | 5.86 MB | 4 KB | 13.13 to 13.41 MB | 1500 | 5.86 MB |
| Append 4 KB 5000 times, buffered | 19.53 MB | 19.53 MB | 20.09 to 20.15 MB | 1.0 | 19.53 MB |

Reading:

- Buffered rewrites of the same block are merged by the cache. The process
  counter overstated volume writes by a factor of about 1000.
- With a flush after every write, each 4 KB write cost about 9 KB on the volume:
  the data once, plus file system log and metadata. 2.3 times the counter.
- An append costs its size plus about 3 percent.
- The rewrite ratio separates the two rewrite cases from the append whatever
  the flushing. Flushed bytes then separate the harmless rewrite loop (nothing
  flushed) from the costly one.

A process write counter therefore neither bounds nor estimates disk load for a
rewriting process. Whether a given logger flushes decides everything.

The same probe on a busy system volume is not usable for the volume column: two
runs there gave 14.5 MB and 163.8 MB for the buffered rewrite, both dominated
by other activity. An earlier reading of "ten times" for flushed rewrites came
from such a run and was wrong.

The same suite and probe also pass in Windows Sandbox on build 26100: 35
passed, ratios 5000 / 1500 / 1.0, flushed 0.00 / 5.86 / 19.53 MB. The sandbox
volume is busy after boot, so its volume column is not comparable.

To do: repeat on a SATA SSD and a hard disk, and on Windows 10.
