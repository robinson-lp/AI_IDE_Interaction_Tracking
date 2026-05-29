"""Command-line entry point for ai-tracker."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import DEFAULT_TOOL_PATHS, load_config
from .exporters.csv_exporter import CSVExporter
from .models import Message
from .parsers import PARSER_REGISTRY, get_parser


# ------------------------------------------------------------------
# Argument type helpers
# ------------------------------------------------------------------

def _date_arg(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid date: {value!r}. Expected YYYY-MM-DD."
    )


def _default_output() -> Path:
    return Path(f"ai_interactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")


# ------------------------------------------------------------------
# Command implementations
# ------------------------------------------------------------------

def _gather_messages(
    tool: str,
    file_override: Optional[Path],
    config: dict,
    start: Optional[datetime],
    end: Optional[datetime],
    include_sidechains: bool,
) -> List[Message]:
    tool_cfg = config.get("tools", {}).get(tool, {})
    path = file_override or Path(
        str(tool_cfg.get("path", DEFAULT_TOOL_PATHS.get(tool, "")))
    ).expanduser()

    kwargs: dict = {}
    if tool == "claudecode":
        kwargs["include_sidechains"] = include_sidechains or bool(
            tool_cfg.get("include_sidechains", False)
        )

    parser = get_parser(tool, path, **kwargs)
    sessions = parser.parse()

    if start or end:
        sessions = parser.filter_by_date(sessions, start, end)

    return [msg for session in sessions for msg in session.messages]


def cmd_parse(args: argparse.Namespace) -> int:
    config = load_config()
    tools = list(PARSER_REGISTRY) if args.tool == "all" else [args.tool]
    file_override = Path(args.file) if args.file else None

    all_messages: List[Message] = []
    had_error = False

    for tool in tools:
        try:
            msgs = _gather_messages(
                tool=tool,
                file_override=file_override,
                config=config,
                start=args.start_date,
                end=args.end_date,
                include_sidechains=getattr(args, "include_sidechains", False),
            )
            all_messages.extend(msgs)
            print(f"  [{tool}] {len(msgs)} message(s) parsed.")
        except FileNotFoundError as exc:
            print(f"  [{tool}] Skipped — {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  [{tool}] Error — {exc}", file=sys.stderr)
            had_error = True

    if not all_messages:
        print("No messages found. Nothing exported.", file=sys.stderr)
        return 1

    all_messages.sort(key=lambda m: m.timestamp.isoformat() if m.timestamp else "")

    output = Path(args.output) if args.output else _default_output()
    exporter = CSVExporter(output)
    count = exporter.export(all_messages)
    print(f"\nExported {count} message(s) -> {output}")
    return 1 if had_error else 0


def cmd_list_tools(_args: argparse.Namespace) -> int:
    config = load_config()
    print(f"{'Tool':<16} {'Status':<12} Path")
    print("-" * 70)
    for tool in PARSER_REGISTRY:
        cfg = config.get("tools", {}).get(tool, {})
        path = Path(str(cfg.get("path", DEFAULT_TOOL_PATHS.get(tool, "")))).expanduser()
        status = "found" if path.exists() else "not found"
        print(f"  {tool:<14} [{status:<9}]  {path}")
    return 0


# ------------------------------------------------------------------
# Argument parser construction
# ------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="ai-tracker",
        description="Parse AI IDE session files and export to structured CSV.",
    )
    sub = root.add_subparsers(dest="command", required=True)

    # ── parse ────────────────────────────────────────────────────────
    p = sub.add_parser("parse", help="Parse session files and export CSV.")
    p.add_argument(
        "--tool",
        choices=[*PARSER_REGISTRY, "all"],
        default="all",
        metavar="TOOL",
        help=(
            f"Which IDE tool to parse. One of: {', '.join(PARSER_REGISTRY)}, all. "
            "(default: all)"
        ),
    )
    p.add_argument(
        "--file", "-f",
        metavar="PATH",
        help="Override the default source file or directory for the chosen tool.",
    )
    p.add_argument(
        "--output", "-o",
        metavar="PATH",
        help="Output CSV path. Default: ai_interactions_<timestamp>.csv",
    )
    p.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        type=_date_arg,
        dest="start_date",
        help="Include only messages on or after this date.",
    )
    p.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        type=_date_arg,
        dest="end_date",
        help="Include only messages on or before this date.",
    )
    p.add_argument(
        "--include-sidechains",
        action="store_true",
        default=False,
        help="(claudecode) Include subagent / sidechain conversations.",
    )

    # ── list-tools ───────────────────────────────────────────────────
    sub.add_parser("list-tools", help="Show available tools and their data paths.")

    return root


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()
    handlers = {
        "parse": cmd_parse,
        "list-tools": cmd_list_tools,
    }
    handler = handlers.get(args.command)
    if handler:
        sys.exit(handler(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
