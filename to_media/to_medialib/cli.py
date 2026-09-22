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
                        help="send to the job server instead of converting here")
    parser.add_argument("--follow", action="store_true",
                        help="with --queue, follow progress until the batch finishes")


def add_server_arguments(parser):
    parser.add_argument("--setup", action="store_true", help="ask the setup questions again")
    parser.add_argument("--foreground", action="store_true", help="stay attached instead of running in the background")
    parser.add_argument("--stop", action="store_true", help="stop a background server")
    parser.add_argument("--status", action="store_true", help="report whether it is running")
    parser.add_argument("--new-token", action="store_true", help="rotate the token; old join strings stop working")
    parser.add_argument("--join-info", action="store_true", help="print only the join string")
    parser.add_argument("--advertise", metavar="hostname|ip|both|VALUE",
                        help="how workers should find this server")
    parser.add_argument("--port", type=int, help="listen on this port instead of the configured one")
    parser.add_argument("--log", metavar="console|syslog|PATH", default=None,
                        help="where to log (default: syslog, falling back to a file)")


def add_worker_arguments(parser):
    parser.add_argument("join", nargs="?", metavar="JOIN", help="a join string; remembered for next time")
    parser.add_argument("--slots", type=int, default=1, help="how many jobs to run at once (default: 1)")
    parser.add_argument("--foreground", action="store_true", help="stay attached instead of running in the background")
    parser.add_argument("--stop", action="store_true", help="stop a background worker")
    parser.add_argument("--status", action="store_true", help="report whether it is running")
    parser.add_argument("--recipes", metavar="FORMAT,...",
                        help="only claim these formats (default: everything installed here)")
    parser.add_argument("--log", metavar="console|syslog|PATH", default=None, help="where to log")


def add_jobs_arguments(parser):
    parser.add_argument("--state", choices=("queued", "running", "done", "skipped", "failed", "cancelled"))
    parser.add_argument("--batch", type=int, metavar="ID")
    parser.add_argument("--limit", type=int, default=50)


def add_status_arguments(parser):
    parser.add_argument("--watch", type=int, nargs="?", const=5, metavar="SECONDS",
                        help="keep refreshing (every 5s, or SECONDS)")


def add_job_or_batch_arguments(parser):
    parser.add_argument("job", nargs="?", type=int, metavar="JOB_ID")
    parser.add_argument("--batch", type=int, metavar="ID")


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
    add_server_arguments(subparsers.add_parser("server", help="start, configure or check the job server"))
    add_worker_arguments(subparsers.add_parser("worker", help="run a worker for the remembered or given server"))
    add_jobs_arguments(subparsers.add_parser("jobs", help="list queued and recent jobs"))
    add_status_arguments(subparsers.add_parser("status", help="show batches and workers on the server"))
    add_job_or_batch_arguments(subparsers.add_parser("cancel", help="cancel a job or a whole batch"))
    add_job_or_batch_arguments(subparsers.add_parser("retry", help="requeue a failed or cancelled job or batch"))
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
        from . import serverctl
        if args.command == "server":
            args.recipes = None
            return serverctl.cmd_server(args, out, sys.stderr)
        if args.command == "worker":
            args.recipes = args.recipes.split(",") if args.recipes else None
            return serverctl.cmd_worker(args, out, sys.stderr)
        if args.command == "jobs":
            return serverctl.cmd_jobs(args, out, sys.stderr)
        if args.command == "status":
            return serverctl.cmd_status(args, out, sys.stderr)
        if args.command == "cancel":
            return serverctl.cmd_cancel(args, out, sys.stderr)
        if args.command == "retry":
            return serverctl.cmd_retry(args, out, sys.stderr)

    if args.follow and not args.queue:
        print(f"{TOOL_NAME}: --follow only makes sense with --queue", file=sys.stderr)
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
    if args.queue:
        from . import queueclient
        client = queueclient.resolve_queue_client(out=out, err=sys.stderr)
        if client is None:
            return 2
        batch = queueclient.submit_batch(client, recipe.name, jobs, policy)
        print(f"{TOOL_NAME}: queued as batch {batch} ({len(jobs)} job(s)).", file=out)
        if args.follow:
            queueclient.follow_batch(client, batch, out)
        return 0
    counts = runner.run_jobs(recipe, jobs, policy, out)
    return 1 if counts["failed"] or problems else 0
