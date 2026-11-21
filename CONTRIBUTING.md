# Contributing

Read [ARCHITECTURE.md](ARCHITECTURE.md) first. The portability rules and the
rules for code that changes the system are requirements, not suggestions.

## Setup

Windows 10 or 11, 64-bit, Python 3.11 or newer.

```
python -m venv .venv
.venv\Scripts\python -m pip install -e . pytest ruff
```

## Checks

Run both before every pull request:

```
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m pytest -rs
```

`-rs` lists skipped tests with their reason. Two tests start a real trace
session and need elevation. Run them in Windows Sandbox, not on your machine:

```
powershell -ExecutionPolicy Bypass -File tools\sandbox\Invoke-SandboxRun.ps1
```

That starts a disposable sandbox with no network, maps the repository and your
Python installation read-only, runs the suite, then the live tests ten more
times (they depend on timing, and one pass proves little), and `writehawk probe` elevated
inside it, prints the result, closes the sandbox and waits a few minutes for
its virtual machine to go away (`-NoWait` skips the wait). Logs stay in
`tools\sandbox\results`. It needs the Windows Sandbox feature
(`Containers-DisposableClientVM`) and a Python installation, not a virtual
environment, that has pytest.

Run it when you touch `filetrace.py`, `handles.py` or anything that needs
elevation, and say in the pull request whether you did. Code that changes the
system (registry, services, tasks) is tested only this way: such a test checks
that `WRITEHAWK_SANDBOX` is `1`, which only the sandbox harness sets, and skips
everywhere else.

If you must run elevated on the host, give pytest its own temp folder and skip
its cache, or it leaves admin-owned folders in the shared temp location and the
next standard-user run fails with "Access is denied":

```
python -m pytest -rs -p no:cacheprovider --basetemp <a folder you can delete>
```

## Checking a rule against the real bug

The sandbox has no NVIDIA or AMD hardware. `tools\verify\Test-NvidiaRule.ps1`
runs on a machine that has an affected NVIDIA driver with the workaround in
place: it switches the workaround off for a few minutes, scans, applies the
workaround with `fix --apply --now`, rolls it back and applies it again, and
ends by comparing the registry key with a backup taken first, restoring it if
it differs. Run it with `-DryRun` first to see every step. Results go to
`tools\verify\results`; add what they show to `docs/RESEARCH.md`.

## Workflow

1. Open an issue that states why, the scope and how it will be accepted.
2. Branch as `feature/<slug>`.
3. Open a pull request. List what you ran and what you did not. End the body
   with `Closes #<n>`, or `Part of #<n>` when the acceptance is not fully met.
4. Squash merge.

Commit messages: imperative mood, short, no type prefixes. Say what changed and
why; for a fix, say what the broken behaviour was.

## Code conventions

- Standard library only at run time.
- One package per pipeline stage. A stage imports only from stages before it.
- Every `ctypes` function gets explicit `argtypes` and `restype`. Check the
  return value and raise `ctypes.WinError` or a specific exception.
- Split Win32 access from logic so the logic takes plain values and can be
  tested with fakes. `Sampler` (injected source and clock) and
  `FileTrace.on_event` (plain bytes in) are the patterns to follow.
- Discover paths, drives and devices at run time. Never commit a drive letter,
  a user name, a driver store hash or a hardware model as a constant.
- Do not parse localized text.
- Comments explain why, or a constraint the code cannot show. No commented-out
  code.

## Tests

- Test files mirror the source tree: `src/writehawk/measure/x.py` is tested by
  `tests/measure/test_x.py`.
- Live tests must pass on any supported machine as a standard user, or skip
  with a reason.
- A test that needs elevation checks `is_elevated()` and skips otherwise.
- Tests clean up after themselves and write only under pytest's `tmp_path`.

## Claims need evidence

Anything stated about Windows behaviour or a vendor bug goes in
[docs/RESEARCH.md](docs/RESEARCH.md) with how it was checked or a source link.
Mark what has not been run as unverified. A rule for a vendor bug is accepted
only with a recorded trace or a vendor statement.

## Changelog

Add a line under `[Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for anything a
user of the tool would notice.
