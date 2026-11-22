<div align="center">

# writehawk

**Finds the program that is quietly wearing out your SSD.**

[![Platform](https://img.shields.io/badge/Platform-Windows_10_%2F_11_x64-0078D6?style=flat-square&logo=windows)](https://biossystem.github.io/writehawk/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://biossystem.github.io/writehawk/)
[![Release](https://img.shields.io/badge/Release-v0.1.0-brightgreen?style=flat-square&logo=github)](https://github.com/BiosSystem/writehawk/releases/tag/v0.1.0)
[![Guide](https://img.shields.io/badge/Interactive_Guide-Live-success?style=flat-square)](https://biossystem.github.io/writehawk/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

<br/>

| Package | Platform | Target | Download Link |
|---|---|---|---|
| **Python Wheel** | Windows 10/11 x64 | Python 3.11+ | [writehawk-0.1.0-py3-none-any.whl](https://github.com/BiosSystem/writehawk/releases/download/v0.1.0/writehawk-0.1.0-py3-none-any.whl) |
| **Source Archive** | Cross-platform | Tarball (.tar.gz) | [writehawk-0.1.0.tar.gz](https://github.com/BiosSystem/writehawk/releases/download/v0.1.0/writehawk-0.1.0.tar.gz) |
| **Offline Bundle** | Windows 10/11 x64 | Wheel + Offline Guide | [writehawk-v0.1.0-bundle.zip](https://github.com/BiosSystem/writehawk/releases/download/v0.1.0/writehawk-v0.1.0-bundle.zip) |

[Interactive Guide & Live Demos](https://biossystem.github.io/writehawk/) · [Changelog](CHANGELOG.md) · [Security Policy](SECURITY.md)

</div>

---

## Overview

Some background software rewrites the same small file thousands of times an hour. Task Manager shows a modest write rate, nothing looks wrong, and the drive absorbs gigabytes a day. In late 2026 two graphics driver releases were reported doing exactly that. 

**writehawk** finds this kind of silent write loop, tells you whether a known cause applies to your machine, and can safely apply and undo verified workarounds.

- **Windows 10 and 11, 64-bit**
- **Python 3.11 or newer**, zero external runtime dependencies
- **No kernel driver** and no background service required
- **Safe by default**: changes nothing on its own; workarounds require `--apply`, scheduled reporting requires `watch install`

---

## Interactive Guide & Web Documentation

New to the command line or want a visual breakdown with pictures?  
Visit the official **[writehawk Interactive Product Guide](https://biossystem.github.io/writehawk/)** for step-by-step walkthroughs, real-time rewrite simulations, and driver vulnerability charts.

---

## Quick Start

```powershell
# Install latest release wheel:
pip install https://github.com/BiosSystem/writehawk/releases/download/v0.1.0/writehawk-0.1.0-py3-none-any.whl

# Run a non-elevated diagnostic scan
writehawk scan
```

`scan` needs no administrator rights. While it watches it displays a progress indicator, evaluates all known vendor issues, and outputs a concise diagnostic summary:

```text
> writehawk scan
Looking at the graphics cards ... 1 found
Watching for disk writes  ████████████████████████  done
Checking 2 known problems ... done

nvidia-nvtopps-log-rewrite: EXPOSED
  NVIDIA display container rewrites its log file without pause
  Example GeForce card: driver 621.24 (affected from 621.14, fixed in 621.35)
  note: 621.35 is a hotfix driver based on 621.24, for Windows 10 and 11.
  workaround: available, not documented by the vendor. Stops the container from loading the plugin that writes the log.
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

### Scan Status Indicators

| Status | Meaning |
|---|---|
| `NOT APPLICABLE` | The target hardware is not present in this machine |
| `NOT AFFECTED` | The installed driver is older than the vulnerable range |
| `FIXED` | The installed driver includes the vendor's official fix |
| `EXPOSED` | The installed driver has the bug; no active loop was seen during this scan |
| `MITIGATED` | The driver has the bug and a verified workaround is active |
| `ACTIVE` | Heavy disk rewrite loop actively observed during the scan window |

Run from an administrator terminal to enable deep kernel ETW tracing for the duration of the scan, measuring loop overhead and identifying unexplained rewrite patterns.

---

## Known Causes & Vendor Fixes

| Cause | Vendor Patch | Delivery |
|---|---|---|
| NVIDIA display container rewriting `nvlog.nvlgstg` | Hotfix Driver 621.35 | Manual standalone installer |
| AMD External Events Utility writing `EeuDumps` while idle | Adrenalin 26.11.1 (RX 7000+) / 26.11.2 (RX 5000/6000) | Adrenalin Software Update |

Each catalog rule carries direct citations to vendor advisories and community verification threads.

---

## Commands

```powershell
writehawk scan                  # Evaluate known issues: affected, fixed, mitigated, or active
writehawk top --seconds 5       # Processes ranked by disk write rate
writehawk trace --seconds 15    # Files ranked by bytes written, with rewrite ratio (Admin)
writehawk context               # Display adapters, volumes, idle state, protected processes
writehawk fix <rule>            # Preview workaround changes; append --apply to execute
writehawk rollback              # Undo the most recent change using the local ledger
writehawk status                # Review active modifications and verify integrity
writehawk report --out r.json   # Comprehensive diagnostic payload as JSON
writehawk watch install         # Register scheduled task for periodic reporting
writehawk selftest              # Validate operational subsystems on this PC
writehawk probe --dir <folder>  # Benchmark rewrite vs append disk costs on your hardware
```

---

## Applying Workarounds & Safe Rollback

```powershell
# Dry-run preview
writehawk fix nvidia-nvtopps-log-rewrite

# Apply workaround (Elevated terminal)
writehawk fix nvidia-nvtopps-log-rewrite --apply

# Roll back all changes
writehawk rollback --apply
```

- **Reversible & Documented**: Workarounds adjust explicit registry values to disable affected logging plugins or idle services.
- **Pre-Execution Ledger**: The exact prior state of every modified key is recorded in `%ProgramData%\writehawk\ledger` before any modification takes place.
- **Safe Rollback**: `rollback` restores exclusively from the pre-modification ledger and halts if values were changed by third-party software since apply.
- **Zero Surprises**: Modifications take effect when the targeted service restarts (`--now` restarts it immediately).

---

## Why Task Manager Misleads

A process rewriting a single 4 KB block 5,000 times reports **19.5 MB written** in Task Manager, yet almost zero bytes reach the physical NAND flash because Windows caches and merges the rewrites in memory. 

However, if that loop flushes after writes, it forces repetitive write-amplification onto the drive. `writehawk` calculates the true **rewrite ratio** per file (total bytes written divided by distinct byte offsets) and measures hardware flush commands separately, differentiating benign memory writes from destructive drive wear.

---

## Privacy & System Safety

- **100% Local**: No network connections, telemetry, or phone-home requests.
- **Read-Only Inspection**: File tracing inspects metadata (offsets, sizes, process names). Document contents are never inspected.
- **Clean Reports**: Diagnostic JSON reports redact hardware serials, device instance IDs, and system UUIDs.
- **Non-Destructive**: Scheduled reporting (`watch`) only logs telemetry; it never applies modifications autonomously.

See [SECURITY.md](SECURITY.md) for detailed permission scopes.

---

## Uninstallation

```powershell
writehawk watch remove
writehawk status          # Roll back any active mitigations
```

Then remove `%ProgramData%\writehawk`.

---

## License

MIT License. See [LICENSE](LICENSE).
