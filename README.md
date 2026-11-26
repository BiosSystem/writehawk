<div align="center">

# writehawk

**Finds programs that keep rewriting the same file and wear out your SSD, and tells you what to do.**

Made by [BiosSystem](https://github.com/BiosSystem)

[Project page](https://biossystem.github.io/writehawk/) ·
[Download 0.2.3](https://github.com/BiosSystem/writehawk/releases/tag/v0.2.3) ·
[Changelog](CHANGELOG.md) ·
[Security](SECURITY.md)

</div>

Some programs save the same small file over and over, all day, even while the
computer is idle. An SSD can only take so much writing before it wears out, and
Task Manager does not show the difference between normal writing and a loop.
writehawk checks for known cases (NVIDIA and AMD graphics driver bugs, and on
Linux and NAS systems a few settings that cause extra writing), lists any other
file that keeps being rewritten, and says what to do in plain words.

- Windows 10 and 11. Linux and NAS systems as a preview.
- Python 3.11 or newer. Nothing else to install.
- Changes nothing unless you ask, and every change can be undone.
- Makes no internet connections and does not read what is inside your files.

The [project page](https://biossystem.github.io/writehawk/) has a step by step
guide for people who have never used a command line.

## Check a Windows PC

1. Install [Python](https://www.python.org/downloads/) 3.11 or newer. On the
   first screen of the installer, tick **Add python.exe to PATH**.
2. Open PowerShell and install writehawk:

   ```powershell
   python -m pip install https://github.com/BiosSystem/writehawk/releases/download/v0.2.3/writehawk-0.2.3-py3-none-any.whl
   ```

3. Run the check. It watches for about 20 seconds and changes nothing:

   ```powershell
   python -m writehawk scan
   ```

Run the same command in a PowerShell opened as administrator for the full
check: writehawk then also watches every file write and lists any file that
keeps being rewritten.

On Linux or a NAS:

```sh
python3 -m venv ~/writehawk
~/writehawk/bin/pip install https://github.com/BiosSystem/writehawk/releases/download/v0.2.3/writehawk-0.2.3-py3-none-any.whl
sudo ~/writehawk/bin/writehawk scan
```

If `python3 -m venv` is missing, install your system's `python3-venv` package.

## Example

Output of writehawk 0.2.3 for a PC with the affected NVIDIA driver (the
graphics card is an example, source links are left out):

```text
> python -m writehawk scan
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

## What the result means

| Result | Meaning |
|---|---|
| `NOT APPLICABLE` | The hardware or software this problem needs is not on this machine |
| `NOT AFFECTED` | The installed version never had this problem |
| `FIXED` | The vendor's fix or the recommended setting is in place |
| `MITIGATED` | The problem version is installed, but a workaround stops the writing |
| `EXPOSED` | The problem version is installed (on Linux: the recommended setting is missing); it was not seen writing during the check |
| `ACTIVE` | The problem was seen writing to the drive during the check |

## Known problems

| Rule | Where | Fix |
|---|---|---|
| `nvidia-nvtopps-log-rewrite` | Windows, NVIDIA drivers 621.14 to 621.24 | Hotfix driver 621.35, or `writehawk fix` |
| `amd-eeu-dump-files` | Windows, AMD External Events Utility | Adrenalin 26.11.2, or `writehawk fix` |
| `linux-docker-json-log-limit` | Docker without a log size limit | `max-size 10m`, `max-file 3` in `/etc/docker/daemon.json` |
| `linux-journald-flash-cap` | systemd journal without a size limit | `SystemMaxUse=64M`, `RuntimeMaxUse=32M` in a journald drop-in |
| `linux-ssd-swappiness` | `vm.swappiness` above 10 | `vm.swappiness = 10` in `/etc/sysctl.d` |
| `linux-btrfs-sqlite-nocow` | Databases on Btrfs without `nodatacow` | By hand, with the application stopped; `writehawk fix` prints the steps |

## Workarounds and undo

```sh
writehawk fix nvidia-nvtopps-log-rewrite           # shows the change, does nothing
writehawk fix nvidia-nvtopps-log-rewrite --apply   # makes it (administrator or root)
writehawk rollback --apply                         # undoes the newest change
writehawk status                                   # changes made and whether they still hold
```

Before any change, writehawk writes the old value to a record in
`%ProgramData%\writehawk\ledger` (Windows) or `/var/lib/writehawk/ledger`
(Linux). `rollback` restores from that record and stops if something else has
changed the value since. A change takes effect when the affected service next
starts; `--now` stops or restarts it at once.

## All commands

```text
writehawk scan                  check the known problems; read only
writehawk top                   programs ranked by write rate
writehawk trace                 files ranked by bytes written and rewrite ratio (administrator or root)
writehawk context               graphics cards, drivers, volumes and drive types
writehawk fix <rule>            show a workaround; --apply makes it
writehawk rollback              show how the newest change is undone; --apply undoes it
writehawk status                changes made and whether they still hold
writehawk report --out r.json   everything above as JSON, without device ids or serial numbers
writehawk watch install         a scheduled report every 6 hours; never applies a fix
writehawk selftest              check each part of writehawk on this machine
writehawk probe --dir <folder>  what a rewrite loop costs on your own drive
```

Every command also works as `python -m writehawk <command>`.

## Remove

Undo changes with `writehawk rollback --apply` until `writehawk status` lists
nothing in place, run `writehawk watch remove` if you set up the scheduled
report, then `python -m pip uninstall writehawk`. Delete
`%ProgramData%\writehawk` (Windows) or `/var/lib/writehawk` (Linux) last.

## What has been tested

| Area | Tested | Not tested yet |
|---|---|---|
| Windows | A Windows 11 PC. The full test suite as administrator in Windows Sandbox (a throwaway Windows 11). Versions before 0.1.0 also ran the suite on Windows Server 2022 and 2025; Server 2022 shares its core with Windows 10 | A Windows 10 PC |
| Linux and NAS | The test suite and the installed program in Linux containers. The Docker and journald fixes applied and undone against the real services in containers | A real NAS (UGOS, DSM, TrueNAS, Unraid), a Btrfs volume, applying the swap setting |
| NVIDIA and AMD problems | A replay of each problem's write pattern at the real file locations | A PC with the live problem |
| Making and undoing a change | Byte for byte on a test registry key and a test service in Windows Sandbox | NVIDIA's or AMD's own service |

On Windows 10, Linux or a NAS? Run `writehawk selftest` and
[share what it prints](https://github.com/BiosSystem/writehawk/issues/new?template=test-report.yml).

## License

MIT. See [LICENSE](LICENSE). Not affiliated with NVIDIA, AMD or Microsoft.
