# writehawk

Finds the program that is quietly wearing out your SSD.

Some software rewrites the same small file thousands of times an hour. Task
Manager shows a modest write rate, nothing looks wrong, and the drive absorbs
gigabytes a day. In late 2026 two graphics driver releases were reported doing
exactly that. writehawk finds this kind of write loop, tells you whether a
known cause applies to your machine, and can apply and undo a workaround.

- Windows 10 and 11, 64-bit
- Python 3.11 or newer, nothing else to install
- No kernel driver and no background service
- Changes nothing on its own: workarounds need `--apply`, the scheduled
  report needs `watch install`

## Quick start

```
python -m pip install https://github.com/BiosSystem/writehawk/archive/refs/heads/master.zip
python -m writehawk scan
```

New to the command line? The [project page](https://biossystem.github.io/writehawk/)
has a step by step guide with pictures.

`scan` needs no administrator rights. While it watches it shows a bar with
the seconds left, then answers four questions for every cause it knows and
ends with a one-line summary:

```
> writehawk scan
Looking at the graphics cards ... 1 found
Watching for disk writes  ████████████████████████  done
Checking 2 known problems ... done

nvidia-nvtopps-log-rewrite: EXPOSED
  NVIDIA display container rewrites its log file without pause
  Example GeForce card: driver 621.24 (affected from 621.14, fixed in 621.35)
  note: 621.35 is a hotfix driver based on 621.24, for Windows 10 and 11.
  workaround: available, not documented by the vendor. Stops the container from loading the plugin that writes the log. NVIDIA does not document this value. It was seen to stop the writes on one affected machine.
  why the fix may not have reached this machine:
    - The fix is a hotfix driver. NVIDIA publishes hotfix drivers as a separate download from its support site and folds them into the next regular driver; no report shows the NVIDIA app or Windows Update offering this one. It has to be downloaded and installed by hand.
  source: https://www.nvidia.com/en-us/geforce/forums/game-ready-drivers/13/592907/continuous-writing-of-gigabytes-to-ssd-to-nvtopps-/
  source: https://wccftech.com/nvidia-releases-gpu-hotfix-driver-621-35-fixes-excessive-ssd-writes/
  source: https://nvidia.custhelp.com/app/answers/detail/a_id/5940

amd-eeu-dump-files: NOT APPLICABLE
  AMD External Events Utility writes dump files while idle
  no amd display adapter in this machine

unknown rewrite loops: not checked, the file trace needs an elevated terminal

Summary: your graphics driver has 1 known problem. Update it to the version named above.
```

| Status | Meaning |
|---|---|
| `NOT APPLICABLE` | The hardware is not in this machine |
| `NOT AFFECTED` | The installed driver is older than the problem |
| `FIXED` | The installed driver has the vendor's fix |
| `EXPOSED` | The installed driver has the problem; no writes were seen during the scan |
| `MITIGATED` | The driver has the problem and a workaround is already in place |
| `ACTIVE` | The writes were seen during the scan |

Run it from an administrator terminal and it also traces file writes for the
length of the scan, measures the loop, and lists rewrite loops that no known
cause explains.

## What it knows today

| Cause | Fixed by the vendor in |
|---|---|
| NVIDIA display container rewriting `nvlog.nvlgstg` | Hotfix driver 621.35 |
| AMD External Events Utility writing `EeuDumps` files while idle | Adrenalin 26.11.1 for RX 7000 and newer, 26.11.2 for RX 5000 and 6000 |

The catalog is a data file. Each entry carries its sources, and a rule is only
added with evidence. Sources and what was and was not verified are in
[docs/RESEARCH.md](docs/RESEARCH.md).

## Commands

```
writehawk scan                  # known causes: affected, fixed, mitigated or writing now
writehawk top --seconds 5       # processes ranked by write rate
writehawk trace --seconds 15    # files ranked by bytes written, with rewrite ratio (administrator)
writehawk context               # display adapters, volumes, idle state, protected processes
writehawk fix <rule>            # show what a workaround would change; --apply to do it
writehawk rollback              # undo the newest change from its record
writehawk status                # changes this tool made and whether they still hold
writehawk report --out r.json   # everything above as JSON, for a bug report or a script
writehawk watch install         # scheduled task that writes the report every few hours
writehawk selftest              # check that each part works on this PC
writehawk probe --dir <folder>  # what rewrite and append workloads cost on this machine
```

## Applying a workaround, and undoing it

```
writehawk fix nvidia-nvtopps-log-rewrite            # prints the change, does nothing
writehawk fix nvidia-nvtopps-log-rewrite --apply    # administrator terminal
writehawk rollback --apply                          # puts everything back
```

- A workaround is a short list of registry values. A catalog entry cannot run
  a command.
- Before anything is changed, the prior state of every value is written to
  `%ProgramData%\writehawk\ledger`. `rollback` restores from that record alone.
- `rollback` leaves a value alone if something else has changed it since, and
  says so. `--force` overwrites it.
- A workaround takes effect when the affected service next starts. `--now`
  stops or restarts that service at once.
- A workaround with a side effect is offered only where the side effect cannot
  bite. Disabling the AMD service, for example, is offered only when the AMD
  adapter drives no display.

The vendor's fixed driver is always the better answer. `scan` tells you which
version that is and why it may not have reached you on its own.

## Why the numbers in Task Manager mislead

A program that rewrites one 4 KB block 5000 times reports 19.5 MB written, and
almost none of it reaches the drive, because Windows merges the rewrites in
memory. The same loop with a flush after each write puts more than twice its
reported bytes on the drive. writehawk measures the rewrite ratio per file
(bytes written divided by distinct bytes covered) and counts flushes
separately, which is what tells a harmless loop from a harmful one.
[ARCHITECTURE.md](ARCHITECTURE.md) has the details and `writehawk probe`
reproduces the measurement on your own machine.

## Privacy and safety

- No network access. Nothing is sent anywhere.
- No document or data file is read. The trace sees names, offsets and sizes.
  `context` and `report` read the program files of running processes, only to
  check who signed them.
- `report` leaves out device instance ids, serial numbers, the system maker
  and the names of installed programs. Paths of observed writes can contain a user
  name, so read a report before sharing it.
- The scheduled task from `watch install` only writes the report. It never
  applies a workaround.

[SECURITY.md](SECURITY.md) lists everything the tool does with administrator
rights.

## Status

Early. Be aware of the limits:

- The suite passes on Windows 11 and on Windows Server 2022 and 2025. Server
  2022 shares its core with Windows 10, but a Windows 10 PC has not run it yet.
  On Windows 10? Run `python -m writehawk selftest` and
  [share the result](https://github.com/BiosSystem/writehawk/issues/new?template=test-report.yml).
- The two rules were checked against a replay of their write pattern, not
  against the real bugs, which cannot be produced on demand.
  `tools\verify\Test-NvidiaRule.ps1` checks the NVIDIA rule against the real
  bug on a PC that has it; it has not had its first run yet.
- Applying and undoing a workaround was verified on a scratch registry key and
  a scratch service in a disposable machine. The same script covers the real
  NVIDIA service.

[ROADMAP.md](ROADMAP.md) tracks all of it. Reports from affected machines are
the most useful contribution: attach the output of `writehawk report`.

## Remove

```
writehawk watch remove
writehawk status          # roll back anything it still lists
python -m pip uninstall writehawk
```

Then delete `%ProgramData%\writehawk`.

## Develop

```
python -m pip install . pytest ruff
python -m ruff check .
python -m pytest -rs
```

Tests that need administrator rights or change the system run only inside
Windows Sandbox, through `tools\sandbox\Invoke-SandboxRun.ps1`.
[CONTRIBUTING.md](CONTRIBUTING.md) explains the setup, and
[ARCHITECTURE.md](ARCHITECTURE.md) the design and the layout of the source.

## License

MIT. See [LICENSE](LICENSE).
