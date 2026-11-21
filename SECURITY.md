# Security

## Reporting

Report a vulnerability through the repository's private security advisory form
(Security tab, "Report a vulnerability"). Do not open a public issue for it.
Include the version, the Windows build and steps to reproduce.

## What the tool does with privilege

Useful results need an elevated terminal, so the tool is written to do as
little as possible with that privilege.

Everything is read-only except `fix --apply` and `rollback --apply`:

- Reads I/O counters of running processes.
- Reads write counters of volumes and disks.
- Starts a real-time ETW session on the Kernel-File provider and reads file
  names, offsets and sizes of writes. No file content is read.
- To name a file that was opened before the trace started, enables the debug
  privilege in its own process, duplicates the writer's file handle with no
  access rights, reads the path and closes the duplicate. The duplicate cannot
  read or write the file.
- `writehawk context` reads the list of display adapters and their driver
  versions from the registry, the active display paths, the bus and media type
  of each volume, and the time since the last input. It does not read disk
  serial numbers and needs no elevation.
- To decide whether a process is on the protected list, reads its image path
  and checks that file's signature. The check does no revocation lookup and
  fetches nothing from the network.
- `writehawk scan` reads driver versions, the registry values a workaround would
  set, the names of installed programs (to see whether a vendor's updater is
  present), one Windows Update policy value and the system maker's name. It
  lists the files a rule names and, when elevated, runs the file trace. It
  changes nothing.
- The rule catalog is data. A rule cannot run a command; the only step it can
  describe is a registry value under `HKLM`.
- `writehawk fix <rule> --apply` sets the registry values the rule lists, all
  under `HKLM`, after writing their prior state to a ledger under
  `%ProgramData%\writehawk\ledger`. With `--now` it also stops or restarts one
  named service. Without `--apply` it only prints what it would do.
- `writehawk rollback --apply` restores those values from the ledger. It does
  not touch a value that something else has changed since, unless `--force`.
- `writehawk watch install` registers one scheduled task that runs
  `writehawk report` as SYSTEM and writes `%ProgramData%\writehawk\report.json`.
  The task changes nothing else. `writehawk watch remove` deletes it.
- `writehawk probe` creates and deletes its own files in a new temp folder.

It does not open network connections, send data anywhere, install a service or
load a driver.

## Rules for future changes to the system

When fixes are added they follow the rules in
[ARCHITECTURE.md](ARCHITECTURE.md): nothing is changed without an explicit
request, the prior state is recorded before the change, and every change can be
undone from that record.

## In scope

- Anything that lets a standard user gain privilege through an elevated run of
  the tool, for example by planting a file or path the tool trusts.
- A fix that cannot be rolled back, or a rollback that restores the wrong state.
- A way to make the tool act on a process or file other than the one reported.
