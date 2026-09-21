"""Argument parsing and dispatch for to_media and its to_<format> aliases."""

import argparse
import os
import sys

from . import __version__, recipes, runner, sources
from .config import TOOL_NAME
from .runner import Policy

SERVER_COMMANDS = ("server", "worker", "jobs", "status", "cancel", "retry")


def alias_format(command_name):
    """'to_mp3' -> 'mp3' when that is a known format; None for to_media itself."""
    if command_name.startswith("to_") and command_name != TOOL_NAME:
        name = command_name[3:]
        if recipes.get(name):
            return name
    return None


def add_common_arguments(parser):
    parser.add_argument("paths", nargs="+", metavar="PATH", help="files or folders to convert")
    parser.add_argument("-o", "--out", metavar="DIR",
                        help="write results here (default: next to each source); folders keep their layout")
    parser.add_argument("-n", "--dry-run", action="store_true", help="show what would be done and stop")
    parser.add_argument("--force", action="store_true", help="overwrite outputs that already exist")
    parser.add_argument("--replace", action="store_true",
                        help="delete each source after its output is written (default: keep sources)")
    parser.add_argument("--no-preserve-times", action="store_true",
                        help="give outputs the current time (default: they keep their source's modification time)")
    parser.add_argument("-v", "--verbose", action="store_true", help="report every file, not just problems")
    parser.add_argument("--queue", action="store_true",
                        help="send to the job server instead of converting here (not available yet)")
    parser.add_argument("--follow", action="store_true",
                        help="with --queue, follow progress until the batch finishes (not available yet)")


def build_parser(prog):
    parser = argparse.ArgumentParser(prog=prog, description="Reshape files from one format to another.")
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="FORMAT")
    for recipe in recipes.RECIPES:
        sub = subparsers.add_parser(recipe.name, help=recipe.description, description=recipe.description,
                                    aliases=list(getattr(recipe, "aliases", ())))
        add_common_arguments(sub)
        recipe.add_arguments(sub)
    subparsers.add_parser("formats", help="list the formats available and what each needs")
    for name in SERVER_COMMANDS:
        subparsers.add_parser(name, help="job server commands (not available yet)")
    return parser


def print_formats(out):
    print(f"{'FORMAT':<8}{'KIND':<8}{'STATUS':<24}DESCRIPTION", file=out)
    for recipe in recipes.RECIPES:
        missing = recipe.missing()
        status = "ready" if not missing else "needs " + ", ".join(missing)
        print(f"{recipe.name:<8}{recipe.kind:<8}{status:<24}{recipe.description}", file=out)


def main(argv=None, prog=None, out=None):
    out = out or sys.stdout
    argv = list(sys.argv[1:] if argv is None else argv)
    command_name = os.path.splitext(os.path.basename(prog or sys.argv[0]))[0]
    alias = alias_format(command_name)
    parser = build_parser(command_name)
    if alias:
        argv = [alias] + argv
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help(out)
        return 2
    if args.command == "formats":
        print_formats(out)
        return 0
    if args.command in SERVER_COMMANDS:
        print(f"{TOOL_NAME} {args.command}: the job server is not available yet (see DESIGN.md).",
              file=sys.stderr)
        return 2
    if args.queue or args.follow:
        print(f"{TOOL_NAME}: --queue needs the job server, which is not available yet; "
              "run without --queue to convert here.", file=sys.stderr)
        return 2

    recipe = recipes.get(args.command)
    missing = recipe.missing()
    if missing:
        print(f"{TOOL_NAME}: {recipe.name} needs {', '.join(missing)}; install it and try again.", file=sys.stderr)
        return 2

    options = recipe.options_from_args(args)
    found, problems = sources.collect(args.paths, recipe.source_extensions(options))
    for problem in problems:
        print(f"{TOOL_NAME}: {problem}", file=sys.stderr)
    if not found:
        print(f"{TOOL_NAME}: no {recipe.name} source files found", file=sys.stderr)
        return 1

    try:
        jobs = recipe.plan(found, options, args.out)
    except Exception as error:
        print(f"{TOOL_NAME}: {error}", file=sys.stderr)
        return 1
    policy = Policy(dry_run=args.dry_run, force=args.force, replace=args.replace, verbose=args.verbose,
                    preserve_times=not args.no_preserve_times)
    counts = runner.run_jobs(recipe, jobs, policy, out)
    return 1 if counts["failed"] or problems else 0
