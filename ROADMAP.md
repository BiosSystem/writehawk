# Roadmap

Five phases. Each ends at a gate: a concrete result that has been run, not
reasoned about. A phase is not done until its gate passes.

## Phase 1: Measurement

State: done. Gate passed 2026-11-21.

- [x] Per-process I/O counters over rolling windows
- [x] Volume write counters
- [x] Rewrite tracker
- [x] Kernel-File ETW reader
- [x] Installable package, `writehawk top` and `writehawk probe`
- [x] Run the trace and the probe elevated and record the result
- [x] Separate requested writes from cache flushes; handle file key reuse
- [x] Name files that were opened before the trace started, by looking up the
      file object from the write event among the writer's handles
- [x] `writehawk trace`: files ranked by bytes written with ratio and flushed bytes

Gate: elevated, the live trace test passes, and `writehawk probe` reports a high
rewrite ratio for the rewrite workloads and about 1 for the append workload.

## Phase 2: Context

State: done. Gate passed 2026-11-21, with the limits listed in [docs/RESEARCH.md](docs/RESEARCH.md).

- [x] GPU list with vendor, driver version and which adapters drive a display
- [x] Drives and volumes with media type
- [x] User idle time and fullscreen state
- [x] `writehawk context`
- [x] Protected process list, matched by image path and signer

Gate: on a machine with an unused integrated GPU and on one without, the
topology is reported correctly; a renamed copy of a protected image is not
treated as protected.

## Phase 3: Rule catalog

State: done, with the gate met on a simulated write pattern only.

- [x] Catalog format: id, vendor, source link, detection, hardware precondition,
      workaround steps, fixed-in version, how the fix is delivered
- [x] The first two rules, with their evidence in
      [docs/RESEARCH.md](docs/RESEARCH.md)
- [x] Generic finding for unknown rewrite loops: detect and report only
- [x] Why a published fix may not have reached the machine
- [x] `writehawk scan`
- [ ] A trace of each real bug. Neither can be produced on demand; the rules
      were checked against a writer that rewrites a file at the rule's path

Gate: each rule matches a recorded trace of its bug, does not match on a
machine with the fixed version installed, and is skipped when its hardware
precondition is not met.

## Phase 4: Fixes and rollback

State: done. Gate passed in the sandbox on a scratch key and a scratch service.

- [x] Registry and service changes, dry run by default
- [x] Ledger written before any change; undo from the ledger alone
- [x] `writehawk fix`, `writehawk rollback`, `writehawk status`
- [ ] Applying a real rule on a machine that has the bug. Not done: the only
      such machine at hand already has both workarounds in place
- Dropped: process throttle. See ARCHITECTURE.md, "Acting"

Gate: apply, verify, roll back and verify again for every fix type, with the
registry and service state compared byte for byte before and after.

## Phase 5: Interface and release

State: in progress. Commands are done; the Windows 10 run and the release are not.

- [x] `scan`, `fix`, `status`, `rollback`, `report`
- [x] Scheduled task that writes the report
- [x] License
- [x] Sandbox run builds the package, installs it into a new environment and
      uses the installed command
- [ ] Windows 10 run of the full suite. Both known causes are reported on
      Windows 10 as well, so it is a supported target, not an optional one.
      Closest so far: the suite passes elevated on Windows Server 2022
      (build 20348), including the live trace tests
- [ ] First tagged release
- Not planned for the first release: the scheduled task applying pre-approved
  rules

Gate: a fresh machine can install, scan, apply one fix, roll it back and
uninstall with nothing left behind. The sandbox covers install and scan with
the installed command, and apply and rollback through the test suite on a
scratch key and service. No catalog rule applies in the sandbox, so `fix
--apply` through the installed command on a real rule is still open.

## Open questions

| Question | Blocks |
|---|---|
| Can a service running as SYSTEM be placed in a job object for throttling? | Phase 4 throttle |
| Does throttling reduce volume writes for a buffered writer, or only delay the caller? | Phase 4 throttle |
