# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.3] - 2026-11-26

### Fixed

- `writehawk probe` stops with a message when a test writer has not finished
  after 5 minutes, instead of waiting forever on a stalled volume, and removes
  its scratch folder either way.
- On Linux, reading or changing a service's start type through `systemctl`
  gives up after 5 and 20 seconds and reports an error, instead of waiting
  forever.

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
- The project page and README stated Docker `max-size 50m` and journald
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

- Linux and NAS support, as a preview. `writehawk context` recognizes UGREEN UGOS
  Pro, Synology DSM, TrueNAS SCALE, Unraid and QNAP QTS, and other Linux
  distributions by their `/etc/os-release`.
- Linux `/proc/<pid>/stat` and `/proc/<pid>/io` reader measuring process-level VFS I/O (`rchar`, `wchar`) and physical storage bytes (`read_bytes`, `write_bytes`, `cancelled_write_bytes`).
- Linux `/proc/diskstats` and `/proc/mounts` metrics parser tracking physical sector writes and discard (TRIM) operations.
- Linux `/proc/<pid>/fd` descriptor crawler resolving active file paths via `os.readlink`.
- File tracing on Linux through `/proc/<pid>/io` and `/proc/<pid>/fd`.
- Rules for Linux and NAS settings:
  - `linux-btrfs-sqlite-nocow`: SQLite databases and WAL files on Btrfs volumes
    that are not mounted `nodatacow`.
  - `linux-docker-json-log-limit`: Docker without a container log size limit
    (`max-size`, `max-file`).
  - `linux-journald-flash-cap`: `systemd-journald` without a size limit for its
    persistent journal.
  - `linux-ssd-swappiness`: a high `vm.swappiness` on flash storage, with
    `vm.swappiness = 10` as the fix.
- Linux workarounds and undo:
  - Settings written to `/etc/sysctl.d`, `/etc/docker/daemon.json`,
    `/etc/systemd/journald.conf.d` and `/etc/writehawk`.
  - Service management via `systemctl` (`is-enabled`, `enable`, `disable`, `start`, `stop`).
  - Periodic reporting via `/etc/cron.d/writehawk-report`.
- `writehawk scan` checks only the rules for the system it runs on.
- The protected process list identifies root-owned system binaries on Linux by
  their SHA-256 hash.

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
- The AMD rule reports 26.11.2 as the fixed version. 26.11.1 fixed RX 7000
  and newer only, so an RX 5000 or 6000 card on 26.11.1 was wrongly shown as
  fixed.
- `scan`, `report`, `top` and `trace` show the step they are on and a bar with
  the seconds left while they watch, on standard error and only in a terminal.
  `scan` ends with a one-line summary in plain words.
- Installable package with an `writehawk` command; Python 3.11 to 3.14.
