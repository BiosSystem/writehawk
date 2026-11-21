"""Command line entry point: `writehawk <command>` or `python -m writehawk <command>`."""
from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable, Iterable, Sequence

from . import __version__, report
from .act import apply as act
from .act import commands, ledger, watch
from .context import drivers, gpu, protect, session, storage
from .measure import probe
from .measure.filetrace import FileTrace, is_elevated
from .measure.rewrite import RewriteTracker
from .measure.sampler import ProcRate, Sampler, list_processes
from .rules import catalog, explain
from .rules import evaluate as ev


def format_top(rates: list[ProcRate], limit: int) -> str:
    lines = [f"{'pid':>7}  {'process':<32}{'write KB/s':>11}{'writes/s':>10}{'avg write':>11}"]
    for r in rates[:limit]:
        if r.write_bytes == 0:
            break
        lines.append(f"{r.pid:>7}  {r.name[:31]:<32}{r.write_bps / 1024:>11.1f}"
                     f"{r.write_iops:>10.1f}{r.avg_write_size:>11.0f}")
    return "\n".join(lines)


def _top(args: argparse.Namespace) -> int:
    sampler = Sampler()
    sampler.sample()
    time.sleep(args.seconds)
    sampler.sample()
    print(format_top(sampler.rates(args.seconds + 1), args.limit))
    if sampler.unreadable:
        print(f"{sampler.unreadable} processes could not be read; run elevated to include them")
    print("counters include pipe and socket writes, not only disk")
    return 0


def format_files(tracker: RewriteTracker, names: dict[int, str], limit: int,
                 min_bytes: int) -> str:
    lines = [f"{'pid':>7}  {'process':<24}{'ratio':>9}{'written KB':>12}{'flushed KB':>12}  file"]
    for f in tracker.top(limit, min_bytes):
        lines.append(f"{f.pid:>7}  {names.get(f.pid, '?')[:23]:<24}{f.rewrite_ratio:>8.1f}x"
                     f"{f.bytes_written / 1024:>12.0f}"
                     f"{tracker.flushed_bytes(f.file_id) / 1024:>12.0f}"
                     f"  {tracker.name_of(f.file_id) or '(unnamed)'}")
    return "\n".join(lines)


def _trace(args: argparse.Namespace) -> int:
    if not is_elevated():
        print("writehawk trace needs an elevated terminal")
        return 1
    tracker = RewriteTracker()
    min_bytes = args.min_kb * 1024
    names = dict(list_processes())
    with FileTrace(tracker) as trace:
        time.sleep(args.seconds)
        named = trace.resolve_names(min_bytes)
    names.update(list_processes())  # keeps the names of processes that exited meanwhile
    print(format_files(tracker, names, args.limit, min_bytes))
    shown = tracker.top(args.limit, min_bytes)
    unnamed = sum(1 for f in shown if tracker.name_of(f.file_id) is None)
    print(f"{trace.events} events in {args.seconds:.0f}s, {named} names looked up through "
          f"handles, {unnamed} of {len(shown)} shown files unnamed")
    print("ratio = bytes written / distinct bytes covered; flushed = cache writes to the file")
    return 0


def _adapter_line(g: gpu.Gpu) -> str:
    version = g.driver_version or "unknown"
    if g.release:
        version += f" ({g.release})"
    if g.displays is None:
        drives = "displays unknown"
    elif g.displays == 0:
        drives = "drives no display"
    else:
        drives = f"drives {g.displays} display{'s' if g.displays > 1 else ''}"
    return f"  {g.name[:39] or '(unnamed)':<40}{g.vendor:<10}driver {version:<24}{drives}"


def count_processes(pids: Iterable[int], classify: Callable[[int], str]) -> dict[str, int]:
    counts = {protect.PROTECTED: 0, protect.OPEN: 0, protect.UNKNOWN: 0}
    for pid in pids:
        counts[classify(pid)] += 1
    return counts


def format_context(gpus: list[gpu.Gpu], volumes: list[storage.Volume],
                   now: session.Session, processes: dict[str, int]) -> str:
    lines = ["display adapters", *(_adapter_line(g) for g in gpus)]
    if not gpus:
        lines.append("  none found")
    lines.append("volumes")
    for v in volumes:
        disks = ",".join(str(d) for d in v.disks) or "?"
        trim = {True: "trim", False: "no trim", None: ""}[v.trim]
        lines.append(f"  {v.root[:2]:<4}{v.filesystem or '-':<7}{v.media:<9}{v.bus:<9}"
                     f"disk {disks:<6}{trim:<9}{v.model}".rstrip())
    lines.append("session")
    lines.append(f"  idle {now.idle_seconds:.0f} s, state {now.state}"
                 f"{', fullscreen' if now.fullscreen else ''}")
    lines.append("processes")
    lines.append(f"  {processes[protect.PROTECTED]} protected, {processes[protect.OPEN]} not "
                 f"protected, {processes[protect.UNKNOWN]} could not be identified")
    if processes[protect.UNKNOWN]:
        lines.append("  an unidentified process is treated as protected; run elevated to "
                     "identify more")
    return "\n".join(lines)


def _context(_args: argparse.Namespace) -> int:
    processes = count_processes((pid for pid, _ in list_processes()),
                                protect.ProtectedList().classify)
    print(format_context(gpu.gpus(), storage.volumes(), session.read(), processes))
    return 0


def _workaround_lines(finding: ev.Finding) -> list[str]:
    rule = finding.rule
    if finding.workaround_in_place:
        return ["  workaround: already in place"]
    if finding.status not in (ev.EXPOSED, ev.ACTIVE, ev.UNKNOWN_VERSION):
        return []
    if not finding.workaround_offered:
        return [f"  workaround: not offered on this machine. {rule.workaround_note}"]
    documented = "" if rule.workaround_documented else ", not documented by the vendor"
    return [f"  workaround: available{documented}. {rule.workaround_note}"]


def _finding_lines(finding: ev.Finding, delivery: drivers.DriverDelivery) -> list[str]:
    rule = finding.rule
    lines = [f"{rule.id}: {finding.status.upper()}", f"  {rule.title}"]
    if finding.status == ev.NOT_APPLICABLE:
        lines.append(f"  no {rule.vendor} display adapter in this machine")
        return lines
    since = (f"affected from {rule.affected_from}" if rule.affected_from
             else "first affected version not known")
    for adapter in finding.adapters:
        lines.append(f"  {adapter.name}: driver {adapter.release or 'version not readable'} "
                     f"({since}, fixed in {rule.fixed_in})")
    if rule.fix_note:
        lines.append(f"  note: {rule.fix_note}")
    for seen in finding.activity:
        if seen.how == "trace":
            lines.append(f"  writing now: {seen.path}, {seen.bytes_written / 1024:.0f} KB, "
                         f"rewritten {seen.rewrite_ratio:.0f}x")
        else:
            lines.append(f"  changed on disk during the scan: {seen.path}")
    if finding.status == ev.ACTIVE and finding.version_state == ev.FIXED:
        lines.append("  the installed version is listed as fixed, yet the writes were seen")
    lines.extend(_workaround_lines(finding))
    why = explain.reasons(finding, delivery)
    if why:
        lines.append("  why the fix may not have reached this machine:")
        lines.extend(f"    - {reason}" for reason in why)
    lines.extend(f"  source: {source}" for source in rule.sources)
    if why and rule.delivery_source:
        lines.append(f"  source: {rule.delivery_source}")
    return lines


def format_scan(findings: list[ev.Finding], loops: list[ev.Activity] | None,
                delivery: drivers.DriverDelivery) -> str:
    lines = []
    for finding in findings:
        lines.extend(_finding_lines(finding, delivery))
        lines.append("")
    if loops is None:
        lines.append("unknown rewrite loops: not checked, the file trace needs an elevated "
                     "terminal")
    elif not loops:
        lines.append("unknown rewrite loops: none seen")
    else:
        lines.append("unknown rewrite loops (reported only, no rule explains them)")
        lines.extend(f"  {loop.path}: {loop.bytes_written / (1 << 20):.1f} MB, rewritten "
                     f"{loop.rewrite_ratio:.0f}x" for loop in loops)
    return "\n".join(lines)


def _collect(seconds: float, adapters: list[gpu.Gpu]) -> tuple[list[ev.Finding],
                                                                list[ev.Activity] | None]:
    """Watch for `seconds`, then evaluate every rule. Loops are None without the trace."""
    rules = catalog.load()
    before = {rule.id: ev.snapshot_files(rule) for rule in rules}
    tracker = None
    if is_elevated():
        tracker = RewriteTracker()
        with FileTrace(tracker) as trace:
            time.sleep(seconds)
            trace.resolve_names(ev.TRACE_MIN_BYTES)
    else:
        time.sleep(seconds)
    findings = []
    for rule in rules:
        seen = ev.trace_activity(rule, tracker) if tracker else []
        traced = {os.path.normcase(item.path) for item in seen}
        seen += [item for item in ev.file_activity(before[rule.id], ev.snapshot_files(rule))
                 if os.path.normcase(item.path) not in traced]
        findings.append(ev.evaluate(rule, adapters, ev.read_dword, seen))
    return findings, ev.rewrite_loops(tracker, rules) if tracker else None


def _scan(args: argparse.Namespace) -> int:
    findings, loops = _collect(args.seconds, gpu.gpus())
    print(format_scan(findings, loops, drivers.read()))
    return 1 if any(f.status in (ev.ACTIVE, ev.EXPOSED) for f in findings) else 0


def _report(args: argparse.Namespace) -> int:
    adapters = gpu.gpus()
    findings, loops = _collect(args.seconds, adapters)
    document = report.build(
        elevated=is_elevated(), seconds=args.seconds, gpus=adapters,
        volumes=storage.volumes(), session=session.read(),
        processes=count_processes((pid for pid, _ in list_processes()),
                                  protect.ProtectedList().classify),
        findings=findings, loops=loops, delivery=drivers.read(),
        entries=ledger.load_all(args.ledger_dir),
        created=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    text = json.dumps(document, indent=2)
    if not args.out:
        print(text)
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    temporary = args.out + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, args.out)  # a reader never sees half a report
    return 0


def _watch(args: argparse.Namespace) -> int:
    if args.action == "status":
        print("the scheduled report is installed" if watch.installed()
              else "the scheduled report is not installed")
        return 0
    if not is_elevated():
        print("installing or removing the scheduled report needs an elevated terminal")
        return 1
    if args.action == "install":
        done, message = watch.install(args.hours, args.out)
        if done:
            message = (f"A report is written to {args.out} every {args.hours} hours. "
                       "The task only reports; it never applies a workaround.")
    else:
        done, message = watch.remove()
    print(message)
    return 0 if done else 1


def _fix(args: argparse.Namespace) -> int:
    rules = {rule.id: rule for rule in catalog.load()}
    if args.rule not in rules:
        print(f"No rule {args.rule}. Known rules: {', '.join(sorted(rules))}")
        return 1
    finding = ev.evaluate(rules[args.rule], gpu.gpus(), ev.read_dword)
    code, lines = commands.fix(
        finding, args.ledger_dir, act.System(), do_apply=args.apply, now=args.now,
        elevated=is_elevated(), classify=protect.ProtectedList().classify)
    print("\n".join(lines))
    return code


def _rollback(args: argparse.Namespace) -> int:
    code, lines = commands.rollback(
        ledger.load_all(args.ledger_dir), args.entry, args.ledger_dir, act.System(),
        do_apply=args.apply, force=args.force, elevated=is_elevated())
    print("\n".join(lines))
    return code


def _status(args: argparse.Namespace) -> int:
    print("\n".join(commands.status(ledger.load_all(args.ledger_dir), act.System())))
    return 0


def _probe(args: argparse.Namespace) -> int:
    return probe.run(args.dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="writehawk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"writehawk {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    top = commands.add_parser("top", help="processes ranked by write rate over a short interval")
    top.add_argument("--seconds", type=float, default=5.0, help="sampling interval (default 5)")
    top.add_argument("--limit", type=int, default=15, help="rows to show (default 15)")
    top.set_defaults(run=_top)

    trace = commands.add_parser(
        "trace", help="files ranked by bytes written, with rewrite ratio (elevated)")
    trace.add_argument("--seconds", type=float, default=15.0, help="how long to watch (default 15)")
    trace.add_argument("--limit", type=int, default=20, help="rows to show (default 20)")
    trace.add_argument("--min-kb", type=int, default=64,
                       help="hide files with fewer KB written (default 64)")
    trace.set_defaults(run=_trace)

    context = commands.add_parser(
        "context", help="display adapters, volumes and whether the machine is in use")
    context.set_defaults(run=_context)

    scan = commands.add_parser(
        "scan", help="check this machine against the known causes of write loops")
    scan.add_argument("--seconds", type=float, default=20.0,
                      help="how long to watch for writes (default 20)")
    scan.set_defaults(run=_scan)

    def with_ledger(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--ledger-dir", default=ledger.default_folder(),
                         help="where the record of changes is kept")

    report_cmd = commands.add_parser(
        "report", help="scan and context as JSON, for a bug report or a script")
    report_cmd.add_argument("--seconds", type=float, default=20.0,
                            help="how long to watch for writes (default 20)")
    report_cmd.add_argument("--out", help="file to write (default: standard output)")
    with_ledger(report_cmd)
    report_cmd.set_defaults(run=_report)

    watch_cmd = commands.add_parser(
        "watch", help="a scheduled task that writes the report; it never changes anything")
    watch_cmd.add_argument("action", choices=("install", "remove", "status"))
    watch_cmd.add_argument("--hours", type=int, default=6, choices=range(1, 24),
                           metavar="1-23", help="hours between reports (default 6)")
    watch_cmd.add_argument("--out", default=watch.default_report_path(),
                           help="where the report is written")
    watch_cmd.set_defaults(run=_watch)

    fix = commands.add_parser(
        "fix", help="apply the workaround of a rule; a dry run unless --apply is given")
    fix.add_argument("rule", help="rule id, as printed by scan")
    fix.add_argument("--apply", action="store_true", help="make the change (elevated)")
    fix.add_argument("--now", action="store_true",
                     help="also stop or restart the affected service so it takes effect at once")
    with_ledger(fix)
    fix.set_defaults(run=_fix)

    rollback = commands.add_parser(
        "rollback", help="undo a change from its ledger entry; a dry run unless --apply")
    rollback.add_argument("entry", nargs="?", help="ledger entry id (default: the newest)")
    rollback.add_argument("--apply", action="store_true", help="make the change (elevated)")
    rollback.add_argument("--force", action="store_true",
                          help="also overwrite values that were changed since")
    with_ledger(rollback)
    rollback.set_defaults(run=_rollback)

    status = commands.add_parser("status", help="changes this tool has made and their state")
    with_ledger(status)
    status.set_defaults(run=_status)

    probe_cmd = commands.add_parser(
        "probe", help="compare what rewrite and append workloads cost on this machine")
    probe_cmd.add_argument("--dir", help="folder to write the test files in (default: temp)")
    probe_cmd.set_defaults(run=_probe)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.run(args)
