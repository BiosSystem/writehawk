# Security

## Reporting a vulnerability

Use the repository's private vulnerability report form: the **Security** tab,
then **Report a vulnerability**. Do not open a public issue for it. Include the
writehawk version, your Windows build or Linux distribution, and the steps to
reproduce.

## What writehawk does with privilege

Useful results need an administrator terminal on Windows or root on Linux, so
writehawk is written to do as little as possible with that privilege. It makes
no network connections, sends no data anywhere, installs no service and loads
no driver.

Everything is read only except `fix --apply`, `rollback --apply` and
`watch install`.

### Reading

- I/O counters of running processes, and write counters of volumes and disks.
- On Windows, a real-time event session on the Kernel-File provider: file
  names, offsets and sizes of writes. It reads no file content. The session is
  named `writehawk`; if the process is killed while it runs, the session stays
  until the next run stops it or Windows restarts. It holds no data on disk.
- On Windows, to name a file that was opened before the trace started:
  writehawk enables the debug privilege in its own process, duplicates the
  writer's file handle with no access rights, reads the path and closes the
  duplicate. The duplicate cannot read or write the file.
- On Linux, `/proc/<pid>/io` and the links under `/proc/<pid>/fd`, which give
  write counts and file names, not content.
- Display adapters and driver versions, active displays, the bus and media type
  of each volume, and the time since the last input. Disk serial numbers are
  not read.
- To decide whether a process is on the protected list: its image path and the
  signature of that file (Windows) or a hash of a root-owned binary (Linux).
  The signature check does no revocation lookup and fetches nothing.
- `scan` also reads the settings a workaround would change, the names of
  installed programs (to see whether a vendor's updater is present), one
  Windows Update policy value, the system maker's name and, on Linux,
  `/proc/mounts`, `/etc/docker/daemon.json`, the journald configuration and
  `vm.swappiness`.
- When the trace starts, it writes one byte to a file of its own in a new temp
  folder until it sees that write, which proves the trace is live, and then
  deletes the folder. `probe` creates and deletes its own files in a new temp
  folder.

### Changing

- The rule catalog is data. A rule cannot run a command. Its steps can only
  name a registry value under `HKLM` or the start type of one named service on
  Windows, and on Linux one of the three settings below.
- `fix <rule> --apply` writes the prior state to a ledger before it changes
  anything: `%ProgramData%\writehawk\ledger` on Windows,
  `/var/lib/writehawk/ledger` on Linux. Without `--apply` it only prints what it
  would do. With `--now` it also stops or restarts the one service the rule
  names.
- On Linux the only files a fix writes are `/etc/docker/daemon.json` (log
  size limit), `/etc/systemd/journald.conf.d/writehawk.conf` (journal size
  limit) and `/etc/sysctl.d/99-writehawk-swappiness.conf`. The swap fix also
  sets `/proc/sys/vm/swappiness` for the running system. The Btrfs rule changes
  nothing: it prints the steps to do by hand.
- `rollback --apply` restores the prior state from the ledger. It does not
  touch a value that something else has changed since, unless `--force`.
- `watch install` registers one scheduled task on Windows, which runs
  `writehawk report` as SYSTEM and writes `%ProgramData%\writehawk\report.json`,
  or one cron entry on Linux (`/etc/cron.d/writehawk-report`, writing
  `/var/lib/writehawk/report.json`). It changes nothing else. `watch remove`
  deletes it.

## Rules for future changes

Nothing is changed without an explicit request, the prior state is recorded
before the change, and every change can be undone from that record.

## In scope

- Anything that lets a standard user gain privilege through an elevated run of
  writehawk, for example by planting a file or path it trusts.
- A fix that cannot be rolled back, or a rollback that restores the wrong state.
- A way to make writehawk act on a process or file other than the one reported.
