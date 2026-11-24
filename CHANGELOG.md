# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.2] - 2026-11-24

### Fixed

- The Btrfs database rule no longer claims a workaround it cannot apply. Its
  old fix wrote a marker file that nothing read, and the rule would then have
  read MITIGATED. Moving a database into a NOCOW folder needs the application
  stopped, so `writehawk fix linux-btrfs-sqlite-nocow` now prints the steps to
  do by hand, `--apply` refuses, and the rule stays EXPOSED.
- On Linux, `fix`, `status` and `rollback` name the file and setting they
  touch (`/etc/docker/daemon.json: log-opts max-size = 10m`) instead of a
  registry-style path. Rolling back the swap setting says that the running
  kernel keeps the current value until the next restart.
- A refused Linux `fix` no longer speaks of display adapters or drivers.
- This page and the README stated Docker `max-size 50m` and journald
  `SystemMaxUse=250M`; the tool writes 10m (with max-file 3) and 64M (with
  RuntimeMaxUse=32M). The NAS demo now shows an elevated scan's real output.

## [0.2.1] - 2026-11-24

### Fixed

- Linux and NAS scans no longer speak of graphics drivers. Each Linux rule says
  whether its recommended setting is in place, names what it looked for when that
  is absent ("no Btrfs volume on this machine"), and the summary tells you to
  apply the setting instead of updating a graphics driver. A scan on Linux also
  shows which storage setup it found. Windows output is unchanged.

## [0.2.0] - 2026-11-22

### Added

- Cross-platform Linux and Network Attached Storage (NAS) support (UGREEN UGOS Pro, Synology DSM, TrueNAS SCALE, Unraid, QNAP QTS, Debian/Ubuntu, Arch, Fedora).
- Linux `/proc/<pid>/stat` and `/proc/<pid>/io` reader measuring process-level VFS I/O (`rchar`, `wchar`) and physical storage bytes (`read_bytes`, `write_bytes`, `cancelled_write_bytes`).
- Linux `/proc/diskstats` and `/proc/mounts` metrics parser tracking physical sector writes and discard (TRIM) operations.
- Linux `/proc/<pid>/fd` descriptor crawler resolving active file paths via `os.readlink`.
- Cross-platform file tracing engine using `/proc/<pid>/io` sampling and non-blocking in-process I/O hooks.
- NAS OS distribution detection in `context.drivers`: recognizes UGREEN UGOS Pro, Synology DSM, Unraid OS, QNAP QTS, TrueNAS, and standard Linux distributions.
- Subsystem diagnostic rules for Linux and NAS storage workloads:
  - `linux-btrfs-sqlite-nocow`: Diagnoses SQLite databases and WAL files on Btrfs copy-on-write mounts missing `NOCOW` (`nodatacow` / `chattr +C`), preventing high write amplification.
  - `linux-docker-json-log-limit`: Checks Docker daemon configuration for unbounded JSON container logging (`max-size`, `max-file`).
  - `linux-journald-flash-cap`: Inspects `systemd-journald` configuration to prevent excessive persistent index and log rewrites to flash boot SSDs.
  - `linux-ssd-swappiness`: Identifies aggressive kernel `vm.swappiness >= 60` on SSD/NVMe root pools and provides wear-reducing configurations.
- Linux `/etc` configuration management:
  - Registry adapter maps `HKLM\LINUX\...` paths to drop-ins in `/etc/sysctl.d`, `/etc/docker/daemon.json`, `/etc/systemd/journald.conf.d`, and `/etc/writehawk`.
  - Service management via `systemctl` (`is-enabled`, `enable`, `disable`, `start`, `stop`).
  - Periodic reporting via `/etc/cron.d/writehawk-report`.
- Platform-filtered rule evaluations: `writehawk scan` now evaluates rules matching the host platform.
- Linux root-owned system binary identification and SHA-256 verification in `ProtectedList`.

## [0.1.0] - 2026-11-22

### Added

- `writehawk top`: processes ranked by write rate over a short interval.
- `writehawk probe [--dir]`: cost of rewrite and append workloads on the local machine.
- Per-process I/O counter sampler with rolling windows.
- Volume and disk write counters.
- Rewrite tracker: bytes written against distinct bytes covered, per file.
- Kernel-File ETW reader, run live: requested writes and cache flushes are
  counted apart, and a reused file key starts a new file.
- `writehawk probe` prints the traced rewrite ratio and flushed bytes when elevated.
- `writehawk trace`: files ranked by bytes written, with rewrite ratio, flushed
  bytes and path. Files opened before the trace started are named through the
  writer's handles.
- `writehawk context`: display adapters with driver versions and whether each
  drives a display, volumes with media type and bus, idle time and fullscreen
  state. No elevation needed.
- Protected process list: a process counts as protected only when its image is
  at a listed path and signed by a listed signer. `writehawk context` reports how
  many running processes are protected and how many could not be identified.
- Rule catalog with two known causes, and `writehawk scan`: per cause, whether
  the hardware is present, whether the installed driver has the fix, whether a
  workaround is in place and whether the writes are happening now. Explains
  why a published fix may not have reached the machine. Lists rewrite loops no
  rule explains when elevated.
- `writehawk fix`, `writehawk rollback` and `writehawk status`: apply a rule's
  workaround and undo it from a ledger that is written before any change.
  Dry run unless `--apply` is given.
- `writehawk report`: scan and context as JSON. `writehawk watch`: a scheduled task
  that writes the report and changes nothing.
- MIT license.
- `writehawk selftest`: checks each part of the tool on the machine it runs
  on and prints pass, fail or skipped with the Windows build, for sharing
  through a test report form.
- `tools/verify/Test-NvidiaRule.ps1`: checks the NVIDIA rule against the real
  bug on a machine that has it.
- The AMD rule reports 26.11.2 as the fixed version. 26.11.1 fixed RX 7000
  and newer only, so an RX 5000 or 6000 card on 26.11.1 was wrongly shown as
  fixed.
- `scan`, `report`, `top` and `trace` show the step they are on and a bar with
  the seconds left while they watch, on standard error and only in a terminal.
  `scan` ends with a one-line summary in plain words.
- Named writehawk. A page for the project under `docs/index.html`, with an
  easy step by step guide beside the advanced one.
- The project page opens with a short demo of a real scan, facts about
  testing, a will and won't list, link preview data and a fuller footer.
- Installable package with an `writehawk` command; Python 3.11 to 3.14.
