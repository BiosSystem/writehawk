# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
