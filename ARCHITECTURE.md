# Architecture

## Problem

Some background software writes to disk in a loop while doing nothing useful: a
driver service rewriting a small log every few seconds, a telemetry agent
rotating dump files while the machine is idle. Task Manager shows a modest
write rate and no file name, so it goes unnoticed for weeks.

writehawk answers three questions, in this order:

1. Which process is writing, and to which file?
2. Is it rewriting the same bytes, and how much of that reaches the disk?
3. Is there a known, reversible fix?

## Non-goals

- No kernel driver and no file system filter.
- No killing of processes.
- No general "optimizer". A change is applied only for a specific, sourced cause.
- No guessing at SSD lifetime. The tool reports bytes written, not wear.

## Pipeline

```
 measure  ->  context  ->  rules  ->  act  ->  cli
 (exists)     (exists)     (exists)   (exists)  (exists)
```

| Stage | Package | Job | Changes the system |
|---|---|---|---|
| Measure | `writehawk.measure` | Collect write activity per process, per file, per volume | No |
| Context | `writehawk.context` | GPU and display topology, drives, idle and fullscreen state, protected processes | No |
| Rules | `writehawk.rules` | Match measurements and context against a catalog of known causes | No |
| Act | `writehawk.act` | Apply a rule's fix, record the prior state, roll back | Yes |
| Interface | `writehawk.cli` | Commands and reports | No |

Each stage depends only on the stages to its left. `measure` imports nothing
from the rest of the package, so it stays usable on its own.

All five exist today. Packages are added when their
first real code lands, not as empty placeholders.

## Measurement

No single Windows source answers the three questions, so three are combined.

| Source | Module | Tells you | Does not tell you |
|---|---|---|---|
| Process I/O counters (`GetProcessIoCounters`) | `sampler.py` | Who calls write, how often, how large | Which file. Whether it was a file at all: pipes and sockets count too |
| Volume counters (`IOCTL_DISK_PERFORMANCE`) | `diskstat.py` | Bytes the storage stack was asked to write | Who caused them |
| Kernel-File ETW events | `filetrace.py` | Pid, file and byte offset of every write; bytes flushed from the cache per file | File system log and metadata cost; names of files opened before the trace |

`rewrite.py` turns the offsets into one number per (process, file):

```
rewrite ratio = bytes written / distinct bytes covered
```

A download covers each byte once, so the ratio is 1. A 4 KB block rewritten 500
times has a ratio of 500. The covered range is kept as merged extents and capped
at 4096 extents per file; past the cap it collapses to one span, which can only
lower the ratio.

Process counters alone mislead in both directions. Measured with `writehawk probe`
(see [docs/RESEARCH.md](docs/RESEARCH.md)): 19.5 MB of buffered rewrites to one
block put about 0.02 MB on the volume, because the cache merged them, while the
same rewrites with a flush after each write cost 2.3 times their counter bytes.

### Data types

| Type | Module | Fields |
|---|---|---|
| `IoCounters` | sampler | read/write/other operation counts and byte counts, cumulative |
| `ProcSample` | sampler | pid, image name, creation time, `IoCounters` |
| `ProcRate` | sampler | deltas over a window, with `write_bps`, `write_iops`, `avg_write_size` |
| `DiskCounters` | diskstat | bytes and operation counts read and written, cumulative |
| `FileWrites` | rewrite | per (pid, file): write count, bytes written, distinct bytes, `rewrite_ratio` |
| `FlushTotals` | rewrite | per file: paging write count and bytes, whoever issued them |

A process is identified by pid plus creation time, so a reused pid starts a new
history instead of inheriting the old one.

A file is identified in events by the ETW `FileKey`, which stays the same across
handles to the same file. The key is a kernel address and is reused after the
file is closed everywhere, often by the next file the same program creates, so
the trace maps each key to a fresh id after its name-delete event. Without that
a rotated log would inherit the totals of the file it replaced.

One write call can produce several write events. They are sorted by the I/O
flags in the event:

| Event | Meaning | Counted as |
|---|---|---|
| Flags 0 | Fast I/O write into the cache | Requested write |
| IRP write, not paging | Write through the IRP path | Requested write, unless it repeats a fast I/O write just refused on the same thread |
| Paging bit set, caller's pid | Flush forced by the caller | Flushed bytes for the file |
| Paging bit set, System pid | Lazy writer | Flushed bytes for the file |

The rewrite ratio uses requested writes only. Flushed bytes say how much of the
file's data went to the storage stack. They do not include the file system log
and metadata that a flush also forces out; the volume counter does.

Names arrive separately (create events and name events) and are attached when
known. A file opened before the trace started gets no such event, which is the
normal case for a service that opened its log at boot. For those,
`handles.py` takes the file object address from the write event, finds the
handle that points at it in the writer's handle table, duplicates that handle
with no access rights and asks for its path. The lookup runs on request
(`FileTrace.resolve_names`), not per event, and only for files above a byte
threshold.

Some files stay unnamed by design: files written through kernel handles, such
as registry hives written by the Registry process, and files whose writer
closed them or exited before the lookup.

Trace buffers are per processor and are handed over when full. The session
sets a one second flush timer. Before anything reads the totals,
`FileTrace.flush` asks for the buffers and waits until an event stamped after
the call has arrived and no earlier-stamped event has arrived for a short
quiet period. One later event is not enough: it proves delivery for its own
processor only.

A flush to disk does not come through the writer's file object. The cache
manager uses a file object of its own, which no create event announces, and
its address can be one that a short-lived open used a moment before. So a
paging write is named by file key only, never by file object. `name_sources`
records where each name came from (name event, create event or handle lookup).

## Context

Rules need to know what the machine is before they can say whether a known
cause applies to it, and what they must leave alone. `writehawk.context` answers
four questions without writing anything.

**Which display adapters are present, and which are in use.** `gpu.py` joins
three sources on the device instance id: the configuration manager's list of
present display class devices, each device's driver key in the registry
(version, provider, date), and the active display paths with the adapter
behind each. An adapter that is present and drives no display is reported as
such. That is the hardware precondition of at least one known cause: a driver
component busy on behalf of an adapter nobody is using.

Vendors publish their own version numbers, and fixes are announced in those.
For NVIDIA the number is the last five digits of the Windows driver version;
for AMD the driver key carries it. `Gpu.release` holds it when it is known.

Whether an adapter is integrated or discrete is not reported: no documented
source says so for a desktop machine. Rules match on vendor, device id and
whether the adapter drives a display.

Display paths belong to a desktop session. A process without one, such as a
service, cannot read them; `Gpu.displays` is then `None`, not zero, so that
"unknown" is never read as "unused".

**What is behind each volume.** `storage.py` reports, per drive letter, the
physical disk numbers, the bus (NVMe, SATA, USB and so on), whether the device
has a seek penalty, and whether it accepts trim. No seek penalty is reported as
`ssd`. A device that does not answer is `unknown`, never guessed. The serial
number is not read.

**Whether someone is at the machine.** `session.py` reports the time since the
last input and the shell's notification state, which says when a fullscreen
application is in front or the session is locked. Both describe the session of
the calling process.

**Which processes must never be acted on.** `protect.py` holds a list of
entries, each a full image path and the signers accepted for it. A process is
protected when its image is at a listed path and that file has a valid
signature, embedded or through a system catalog, from one of those signers.
Path and signer are both required because each fails alone: a copy of a system
image elsewhere keeps its valid signature, and a file at any path can borrow a
name. The signature check asks for no revocation lookup and fetches nothing,
so it stays off the network. Results are cached per file and dropped when the
file's size or modification time changes.

A process that cannot be opened has no known image and is classified
`unknown`. Every caller that changes anything treats `unknown` as protected.
The system idle process and the System process are protected by pid.

The default list covers the core session processes and the built-in antivirus
service. It is a floor, not a judgment of what is safe to act on: the stages
that change things only ever act on what a rule names.

## Rules

A rule is an entry in `rules/catalog.json`. It names its sources, the vendor
versions it affects and the one that fixes it, the files and processes that
show it, and a workaround as a list of registry values. The loader refuses a
rule without a source, with a version it cannot parse, with a step outside
`HKLM`, or with a step type it does not know. There is no step type that runs a
command.

Evaluating a rule keeps three questions apart:

| Question | Source | Answers |
|---|---|---|
| Is the hardware here? | Display adapters of the rule's vendor | not applicable |
| Does the installed version have the problem? | Vendor release number of each adapter | not affected, exposed, fixed, version unknown |
| Is it happening now? | File trace, or changes to the rule's files | active |

Writes that are seen outrank a version that is listed as fixed: the status is
`active` and the report says the version disagrees. An exposed machine whose
workaround values are already set is `mitigated`. With two adapters of one
vendor the worse version decides.

Activity has two sources. Elevated, the file trace gives bytes and rewrite
ratio per file. Not elevated, the rule's file patterns are listed before and
after the wait and anything new or changed counts; that misses a rewrite which
leaves size and time alone, and says so in the code.

A workaround can carry a requirement. One that has a side effect when the
adapter is in use is offered only when the adapter drives no display, and
"unknown" is not "none".

Rewrites that no rule explains are listed and never acted on.

`explain.py` answers a different question: the vendor published a fix, so why
is it not here. It combines how the fix is delivered (a catalog field, with
its source) with what `context/drivers.py` reads from the machine: whether the
vendor's updater is installed, who supplied the driver, whether policy keeps
drivers out of Windows Update, and whether the machine is a portable one whose
maker ships its own drivers.

## Acting

`writehawk.act` is the only package that writes outside its own ledger folder.
A workaround is a list of registry values, so applying one is: read the prior
state of every value, write the ledger entry, then set the values one at a
time, saving the entry after each.

A ledger entry is one JSON file. For each value it holds whether the value
existed, its type and data, and which keys had to be created to hold it. It is
flushed to disk before the first change, so a crash at any point leaves a
record of exactly what was touched. Rollback reads the entry and nothing else:
it restores each value in reverse order, deletes a value that did not exist
before, and removes a key it created only if that key is empty again.

Before restoring a value, rollback checks that it still holds what the tool
wrote. If something else has changed it since, the value is left alone and
reported; `--force` overwrites it.

A service start type is changed through the service control manager, which
writes the same registry value and keeps its own state consistent. A change
takes effect when the service next starts. `--now` stops or restarts the
service the rule names, records whether it was running, and reverses that on
rollback. It is refused when the service runs in a process that is on the
protected list or cannot be identified.

`fix` refuses a rule whose hardware is absent, whose installed version is
fixed or unaffected, or whose workaround carries a requirement the machine
does not meet. Everything is a dry run until `--apply` is given.

Process throttling is not built. The job object rate limit is documented as
unsupported and does not slow a buffered writer (see `docs/RESEARCH.md`), so
there is no case yet where it helps.

## Report and schedule

`report.py` turns one scan into a JSON document with a format number. It is
the interface for scripts and for bug reports, so it omits what identifies a
machine and keeps "the trace did not run" (`null`) apart from "the trace found
nothing" (an empty list).

`act/watch.py` registers one scheduled task that runs `writehawk report` as
SYSTEM every few hours. It lives in `act` because registering a task changes
the system, but the task itself is read-only. It does not apply workarounds:
that stays a deliberate act at a terminal until the manual path has been used
on real machines. A task running as SYSTEM has no desktop, so it cannot see
which adapters drive a display and reports that as unknown.

## Privilege model

| Operation | Standard user | Elevated |
|---|---|---|
| I/O counters of own processes | Yes | Yes |
| I/O counters of services and other users' processes | No, counted as unreadable | Yes |
| Volume counters | Yes | Yes |
| Display adapters, volumes, idle and fullscreen state | Yes | Yes |
| Rule status from versions, registry values and file changes | Yes | Yes |
| Rule activity with bytes and rewrite ratio; unknown rewrite loops | No | Yes |
| Image path of a process, for the protected list | Own processes only; the rest are `unknown` | Yes |
| File trace session | No, `PermissionError` | Yes |
| Path lookup through another process's handles | No | Yes, with the debug privilege enabled for the lookup |
| Dry run of a fix or a rollback; `status` | Yes | Yes |
| Applying a fix or a rollback | No, refused with a message | Yes |
| Installing or removing the scheduled report | No, refused with a message | Yes |

Code must degrade, not fail, when not elevated: report what could not be read
and carry on. Nothing requests elevation on its own; the user starts an
elevated terminal.

## Portability rules

These hold for every module. A change that breaks one needs a reason written
down here.

- **No fixed paths.** Drive letters, profile folders, driver store folder names
  and device names are discovered at run time. Driver store folders carry a
  per-machine hash and are matched by pattern.
- **No fixed hardware.** Nothing assumes a GPU vendor, a GPU count, a laptop or
  a desktop. Rules state their hardware precondition and are skipped when it is
  not met.
- **No localized text.** Detection never parses command output or display
  names, which change with the Windows language. Use API values, service key
  names and image names.
- **Versions are checked, not assumed.** Event payloads are parsed by event
  version. Anything unknown is skipped and counted, never guessed.
- **Standard library only.** Win32 calls go through `ctypes` with explicit
  argument and return types. No compiled extension, no third-party package at
  run time.
- **64-bit Windows 10 and 11.** The file trace refuses to start under 32-bit
  Python. Importing the package on another operating system raises
  `ImportError` with a plain message.
- **Vendor knowledge is data.** Known causes and their fixes live in a catalog,
  each with a source, a precondition and the version that fixed it, so a rule
  retires itself once the fix is installed.

Tested so far on Windows 11 only (builds 26100 and 26300). Windows 10 is supported by design (the APIs
and event versions used exist there) but has not been run.

## Rules for the stages that change things

Written before that code exists so it is built to them.

- Read-only by default. A fix runs only when asked for by rule id.
- Dry run first: every fix can print what it would change.
- The prior state is written to a ledger before anything is changed, and the
  ledger alone is enough to undo it.
- A background watcher reports. It applies fixes only for rule ids the user has
  approved in advance.
- Protected processes are matched by image path and signer, not by name alone.
- Throttling a process is optional and self-tested at start. It is documented by
  Microsoft as unsupported, and it does not slow buffered writers.

## Decisions

| Decision | Why |
|---|---|
| Combine three sources instead of trusting process counters | Counters include non-disk I/O and carry no offsets; measured off by a factor of about 1000 one way and 2.3 the other |
| ETW Kernel-File provider for offsets | The only driverless source of per-write offsets with the issuing pid |
| Parse payloads by hand from manifest layouts | Avoids a dependency; layouts for versions 0 and 1 are recorded in `docs/RESEARCH.md` and tested |
| `src/` layout with a `measure` subpackage | Tests run against what is installed; one package per pipeline stage |
| Name lookup through the handle table, on request | No trace event names a file opened before the session; a per-event lookup would be too slow and too invasive |
| A process that cannot be identified counts as protected | The alternative is acting on a process without knowing what it is |
| Ledger saved before the first change and after each one | The record must survive a crash between two changes |
| Rollback leaves a value that no longer holds what was written | Something else owns it now; overwriting would be a new change, not an undo |
| Rules are data, and a step can only set a registry value under `HKLM` | A catalog entry must not be able to run anything |
| Observed writes outrank the version number | Vendors list a version as fixed before every configuration is; the trace is the evidence |
| Unknown display paths are `None`, not zero | A service cannot read them; reporting zero would make every adapter look unused |
| Fresh id per file key after name-delete | Kernel reuses the key; seen live as one file's flushes landing on another |
| Drop the IRP repeat of a refused fast I/O write | About 20 percent of appends were counted twice without it |
| Extent cap that lowers the ratio | Bounded memory under random writers without ever overstating a rewrite loop |
| No automatic fixes by default | Fixes touch driver services; a wrong one costs more than a slow one |

## Testing

- Logic is tested with fakes: injected clock and sample source for the sampler,
  synthetic event payloads for the trace.
- Live tests that need no privilege run everywhere: own-process counters,
  volume counters, the command line.
- Tests that need elevation skip with a stated reason. A skipped test is
  reported in the pull request, never counted as passed.
- Elevated tests run in Windows Sandbox through `tools/sandbox`: repository and
  Python mapped read-only, no network, results written to one mapped folder.
  Code that changes the system is tested nowhere else.
- CI runs lint and tests on every supported Python version from an installed
  copy of the package.

## Source layout

```
src/writehawk/
  cli.py             command line entry point
  measure/           read-only measurement
    sampler.py         per-process I/O counters over rolling windows
    diskstat.py        cumulative write counters for a volume or disk
    rewrite.py         bytes written against distinct bytes covered, per file
    filetrace.py       Kernel-File ETW session: pid, file and offset of every write
    handles.py         path of a file from its kernel object, through the handle table
    probe.py           side-by-side cost of rewrite and append workloads
  context/           read-only facts about the machine and its user
    gpu.py             display adapters, driver versions, active display paths
    storage.py         volumes with backing disks, bus, media type and trim
    session.py         idle time and fullscreen state
    protect.py         processes that must never be acted on, by path and signer
    drivers.py         how drivers reach this machine: updaters, policy, maker
  rules/             known causes and whether one applies here
    catalog.json       the rules, as data
    catalog.py         loading and validation
    evaluate.py        status of a rule on this machine; unexplained rewrite loops
    explain.py         why a published fix may not have arrived
  report.py          scan and context as one JSON document
  act/               the only package that changes the system
    regvalues.py       registry values: read with type, set, put back
    services.py        service start type and state
    ledger.py          the record of each change, written first
    apply.py           apply a workaround, roll it back
    commands.py        the decisions behind fix, rollback and status
    watch.py           the scheduled task that writes the report
tests/               mirrors src/writehawk
tools/sandbox/       runs the elevated tests in Windows Sandbox
docs/RESEARCH.md     what was verified, how, and the sources
docs/index.html      the project's web page, one self-contained file
ARCHITECTURE.md      design, data flow, privilege model, portability rules
ROADMAP.md           phases, their gates and current state
CONTRIBUTING.md      setup, checks, conventions
SECURITY.md          reporting and what the tool does with privilege
```
