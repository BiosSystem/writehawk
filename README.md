<div align="center">

# writehawk

**Finds the program or background workload quietly wearing out your SSD.**

[![Platform](https://img.shields.io/badge/Platform-Windows_%7C_Linux_%7C_NAS-0078D6?style=flat-square&logo=linux)](https://biossystem.github.io/writehawk/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://biossystem.github.io/writehawk/)
[![Release](https://img.shields.io/badge/Release-v0.2.1-brightgreen?style=flat-square&logo=github)](https://github.com/BiosSystem/writehawk/releases/tag/v0.2.1)
[![Guide](https://img.shields.io/badge/Interactive_Guide-Live-success?style=flat-square)](https://biossystem.github.io/writehawk/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

<br/>

| Package | Platform | Target | Download Link |
|---|---|---|---|
| **Python Wheel** | Cross-platform | Python 3.11+ | [writehawk-0.2.1-py3-none-any.whl](https://github.com/BiosSystem/writehawk/releases/download/v0.2.1/writehawk-0.2.1-py3-none-any.whl) |
| **Source Archive** | Cross-platform | Tarball (.tar.gz) | [writehawk-0.2.1.tar.gz](https://github.com/BiosSystem/writehawk/releases/download/v0.2.1/writehawk-0.2.1.tar.gz) |
| **Offline Bundle** | Cross-platform | Wheel + Offline Guide | [writehawk-v0.2.1-bundle.zip](https://github.com/BiosSystem/writehawk/releases/download/v0.2.1/writehawk-v0.2.1-bundle.zip) |

[Interactive Guide & Live Demos](https://biossystem.github.io/writehawk/) · [Changelog](CHANGELOG.md) · [Security Policy](SECURITY.md)

</div>

---

## Overview

Some background software rewrites the same small file thousands of times an hour, or subjects flash storage to continuous write amplification loops. On Windows, graphics drivers have been found repeatedly rewriting log and dump files. On 24/7 Linux servers and Network Attached Storage (NAS) units (UGREEN UGOS Pro, Synology DSM, TrueNAS SCALE, Unraid), unconstrained Docker container logs, continuous `systemd-journald` flushes, SQLite write-ahead-logs (WAL) on Btrfs copy-on-write volumes, and default `vm.swappiness` quietly burn through flash endurance without user notification.

**writehawk** finds these silent write loops, diagnoses whether known subsystem issues or driver bugs apply to your system, and safely applies and rolls back verified mitigations.

- **Platforms**: Windows 10 and 11, 64-bit (tested on Windows 11 and Windows Server; a Windows 10 PC has not run it yet). Linux and NAS systems as a preview: tested inside a Linux container, not yet on a real NAS. See [What has been tested](#what-has-been-tested).
- **Python 3.11 or newer**, zero external runtime dependencies (pure standard library).
- **No kernel driver** and no persistent background daemon required.
- **Safe by default**: changes nothing on its own; mitigations require `--apply`, periodic reporting requires `watch install`.

---

## Interactive Guide & Web Documentation

New to the command line or want a visual breakdown with pictures?  
Visit the official **[writehawk Interactive Product Guide](https://biossystem.github.io/writehawk/)** for step-by-step walkthroughs, real-time rewrite simulations, and vulnerability charts.

---

## Quick Start

```bash
# Install latest release wheel:
pip install https://github.com/BiosSystem/writehawk/releases/download/v0.2.1/writehawk-0.2.1-py3-none-any.whl

# Run a non-elevated diagnostic scan
writehawk scan
```

`scan` evaluates the rules for your platform. This is the real output on a Windows PC with an
affected NVIDIA driver (source links omitted):

```text
> writehawk scan
Looking at the graphics cards ... 1 found
Watching for disk writes  ████████████████████████  done
Checking 2 known problems ... done

nvidia-nvtopps-log-rewrite: EXPOSED
  NVIDIA display container rewrites its log file without pause
  NVIDIA GeForce RTX 4080: driver 621.24 (affected from 621.14, fixed in 621.35)
  note: 621.35 is a hotfix driver based on 621.24, for Windows 10 and 11.
  workaround: available, not documented by the vendor. Stops the container from loading the plugin that writes the log. NVIDIA does not document this value. It was seen to stop the writes on one affected machine.
  why the fix may not have reached this machine:
    - The fix is a hotfix driver. NVIDIA publishes hotfix drivers as a separate download from its support site and folds them into the next regular driver; no report shows the NVIDIA app or Windows Update offering this one. It has to be downloaded and installed by hand.

amd-eeu-dump-files: NOT APPLICABLE
  AMD External Events Utility writes dump files while idle
  no amd display adapter in this machine

unknown rewrite loops: not checked, the file trace needs an elevated terminal

Summary: your graphics driver has 1 known problem. Update it to the version named above.
```

### Scan Status Indicators

| Status | Meaning |
|---|---|
| `NOT APPLICABLE` | The target hardware or subsystem is not present on this machine |
| `NOT AFFECTED` | The installed version or configuration is safe from the issue |
| `FIXED` | The system includes the official fix or recommended baseline |
| `EXPOSED` | Configuration has the vulnerability; no active loop was seen during this scan |
| `MITIGATED` | Known issue detected and a verified workaround is active |
| `ACTIVE` | Heavy disk rewrite loop actively observed during the scan window |

On Windows, run from an administrator terminal to enable kernel ETW tracing. On Linux/NAS, run with `sudo` to inspect `/proc/<pid>/io` for all processes and apply configuration mitigations.

---

## Supported Platforms & Diagnostic Catalog

### Windows
- **NVIDIA Display Container** (`nvtopps`): Detects continuous log file rewrite loop (`nvlog.nvlgstg`) in drivers 621.14 through 621.24 (fixed in hotfix 621.35).
- **AMD External Events Utility** (`EeuDumps`): Detects the dump file loop during idle. Fixed in 26.11.1 for RX 7000 and newer and in 26.11.2 for RX 5000 and 6000; writehawk asks for 26.11.2.

### Linux & NAS (UGREEN UGOS, Synology DSM, TrueNAS, Unraid, Generic Linux)
- **Btrfs SQLite NOCOW** (`linux-btrfs-sqlite-nocow`): Detects SQLite databases and WAL files running without `chattr +C` on copy-on-write Btrfs shares, preventing rapid flash wear and metadata fragmentation.
- **Docker JSON Log Limits** (`linux-docker-json-log-limit`): Checks whether the Docker daemon enforces log size and file rotation limits (`max-size`, `max-file`), preventing runaway container write churn.
- **Journald Flush Cap** (`linux-journald-flash-cap`): Verifies `systemd-journald` configuration enforces caps on persistent disk logging (`SystemMaxUse`) on root SSDs.
- **SSD Swap Aggressiveness** (`linux-ssd-swappiness`): Identifies aggressive default Linux kernel swap tendencies (`vm.swappiness >= 60`) on SSD/NVMe root pools and configures wear-reducing thresholds.

---

## Commands

```bash
writehawk scan                  # Evaluate known platform rules
writehawk top --seconds 5       # Processes ranked by disk write rate
writehawk trace --seconds 15    # Files ranked by bytes written and rewrite ratio (Admin/root)
writehawk context               # Display adapters, mount points, volumes, and protected processes
writehawk fix <rule>            # Preview mitigation changes; append --apply to execute
writehawk rollback              # Undo the most recent change using the local ledger
writehawk status                # Review active modifications and verify integrity
writehawk report --out r.json   # Comprehensive diagnostic payload as JSON
writehawk watch install         # Register scheduled task/cron for periodic reporting
writehawk selftest              # Validate operational subsystems on this machine
writehawk probe --dir <folder>  # Benchmark rewrite vs append disk costs on your hardware
```

---

## Applying Workarounds & Safe Rollback

```bash
# Dry-run preview
writehawk fix linux-ssd-swappiness

# Apply workaround (root / Administrator)
writehawk fix linux-ssd-swappiness --apply

# Roll back all changes
writehawk rollback --apply
```

- **Reversible & Documented**: Workarounds modify explicit registry values (Windows) or `/etc` configuration drop-ins (Linux) without touching third-party binaries.
- **Pre-Execution Ledger**: The exact prior state of every modified file or key is recorded in `%ProgramData%\writehawk\ledger` (Windows) or `/var/lib/writehawk/ledger` (Linux) before any change occurs.
- **Safe Rollback**: `rollback` restores exclusively from the pre-modification ledger and halts if files were modified externally since application.

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

## What has been tested

| Area | Tested | Not tested yet |
|---|---|---|
| Windows | Windows 11 desktop; Windows Server 2022 and 2025 on every change (Server 2022 shares its core with Windows 10) | A Windows 10 PC |
| Linux & NAS | Test suite, and the installed package's scan and selftest, inside a Linux container | A real NAS: UGOS, DSM, TrueNAS, Unraid |
| NVIDIA and AMD bugs | A replay of each bug's write pattern at the real file paths | A machine with the live bug |
| Applying and undoing a fix | Byte for byte on a test registry key and service in a throwaway Windows | NVIDIA's or AMD's own service |

On Windows 10, Linux or a NAS? Run `writehawk selftest` and
[share what it prints](https://github.com/BiosSystem/writehawk/issues/new?template=test-report.yml).

## License

MIT License. See [LICENSE](LICENSE).
