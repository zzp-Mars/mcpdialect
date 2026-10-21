"""Command line interface: ``mcpdialect check | fix | profiles | explain``.

Exit codes: 0 = nothing at or above ``--fail-on``; 1 = findings at or above it;
2 = usage or input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from . import __version__, check_tools
from .engine import SEVERITY_ORDER
from .loaders import LoadError, load_tools_file, load_tools_http, load_tools_stdio
from .profiles import ProfileError, find_rule, list_profiles, load_profile, resolve_profiles
from .report import FORMATS, render
from .transforms import portable

EXIT_OK, EXIT_FINDINGS, EXIT_USAGE = 0, 1, 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # argparse exits 2 already; keep message short
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _add_source_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="tools.json: a tools/list response, {'tools': [...]}, or a list ('-' = stdin)",
    )
    p.add_argument("--cmd", help="start an MCP server over stdio and read its tools/list (needs mcpdialect[live])")
    p.add_argument("--url", help="read tools/list from a Streamable HTTP MCP endpoint (needs mcpdialect[live])")
    p.add_argument("--timeout", type=float, default=30.0, help="seconds to wait for a live server (default 30)")
    p.add_argument("-p", "--profile", default="all", help="comma-separated profile ids, or 'all' (default)")
    p.add_argument("--no-unverified", action="store_true", help="skip rules marked unverified")


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="mcpdialect", description="Lint and fix MCP tool schemas for model-provider dialects.")
    parser.add_argument("--version", action="version", version=f"mcpdialect {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    c = sub.add_parser("check", help="report findings per tool and profile")
    _add_source_args(c)
    c.add_argument("-f", "--format", choices=FORMATS, default="text")
    c.add_argument(
        "--fail-on",
        choices=("breaks", "fixable", "warn", "never"),
        default="fixable",
        help="lowest severity that makes the exit code 1 (default: fixable)",
    )
    c.add_argument("-o", "--output", help="write the report to this file instead of stdout")

    f = sub.add_parser("fix", help="write portable schemas and a change report")
    _add_source_args(f)
    f.add_argument("-o", "--output", help="write fixed tools JSON here (default: stdout)")
    f.add_argument("--report", help="write the list of changes (JSON) here")
    f.add_argument("--no-describe", action="store_true", help="do not move dropped constraints into descriptions")

    sub.add_parser("profiles", help="list profiles, rule counts and verification dates")

    e = sub.add_parser("explain", help="show a rule's rationale and source")
    e.add_argument("rule", help="rule id, e.g. GEM001")
    return parser


def _load(args: argparse.Namespace) -> tuple[list[dict[str, Any]], str]:
    sources = sum(1 for x in (args.files, args.cmd, args.url) if x)
    if sources != 1:
        raise LoadError("give exactly one source: FILE..., --cmd, or --url")
    if args.files:
        tools: list[dict[str, Any]] = []
        for name in args.files:
            if name == "-":
                from .loaders import normalize_tools

                tools.extend(normalize_tools(json.load(sys.stdin)))
            else:
                tools.extend(load_tools_file(name))
        return tools, args.files[0] if args.files[0] != "-" else "stdin"
    if args.cmd:
        return load_tools_stdio(args.cmd, timeout=args.timeout), "tools.json"
    return load_tools_http(args.url, timeout=args.timeout), "tools.json"


def _write(text: str, path: str | None) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)


def _cmd_check(args: argparse.Namespace) -> int:
    tools, source = _load(args)
    report = check_tools(tools, args.profile, include_unverified=not args.no_unverified)
    _write(render(report, args.format, source_name=source), args.output)
    if args.fail_on == "never" or not report.findings:
        return EXIT_OK
    threshold = SEVERITY_ORDER[args.fail_on]
    return EXIT_FINDINGS if any(SEVERITY_ORDER[f.severity] >= threshold for f in report.findings) else EXIT_OK


def _cmd_fix(args: argparse.Namespace) -> int:
    tools, _source = _load(args)
    profiles = resolve_profiles(args.profile)
    fixed_tools = []
    change_report = []
    unresolved = 0
    for tool in tools:
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            change_report.append({"tool": tool["name"], "error": "inputSchema is not an object"})
            fixed_tools.append(tool)
            unresolved += 1
            continue
        res = portable(
            schema,
            profiles,
            tool_name=str(tool["name"]),
            describe_dropped=not args.no_describe,
            include_unverified=not args.no_unverified,
        )
        fixed_tools.append({**tool, "inputSchema": res.schema})
        unresolved += len(res.remaining)
        change_report.append(
            {
                "tool": tool["name"],
                "changes": [c.to_dict() for c in res.changes],
                "lossy": res.lossy,
                "remaining": [f.to_dict() for f in res.remaining],
            }
        )
    _write(json.dumps({"tools": fixed_tools}, indent=2, ensure_ascii=False) + "\n", args.output)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump({"profiles": [p.id for p in profiles], "tools": change_report}, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    n_changes = sum(len(t.get("changes", [])) for t in change_report)
    n_lossy = sum(1 for t in change_report for c in t.get("changes", []) if c["lossy"])
    print(f"mcpdialect: {n_changes} change(s), {n_lossy} lossy, {unresolved} unresolved finding(s)", file=sys.stderr)
    return EXIT_FINDINGS if unresolved else EXIT_OK


def _cmd_profiles(_args: argparse.Namespace) -> int:
    for pid in list_profiles():
        prof = load_profile(pid)
        unverified = sum(1 for r in prof.rules if r.status == "unverified")
        extra = f", {unverified} unverified" if unverified else ""
        print(f"{pid:<17} {len(prof.rules):>2} rules{extra:<15}  verified {prof.verified_on}  {prof.title}")
    return EXIT_OK


def _cmd_explain(args: argparse.Namespace) -> int:
    prof, rule = find_rule(args.rule)
    print(f"{rule.id}  {rule.title}")
    print(f"profile:     {prof.id} ({prof.applies_to})")
    print(f"severity:    {rule.severity}    status: {rule.status}    verified on: {rule.verified_on}")
    print(f"fix:         {rule.fix or 'none (report only)'}")
    print(f"source:      {rule.source}")
    for ev in rule.evidence:
        print(f"evidence:    {ev}")
    print()
    print(rule.rationale)
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handlers = {"check": _cmd_check, "fix": _cmd_fix, "profiles": _cmd_profiles, "explain": _cmd_explain}
    try:
        return handlers[args.command](args)
    except (LoadError, ProfileError) as exc:
        print(f"mcpdialect: error: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
