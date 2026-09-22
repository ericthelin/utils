"""Resolving a job-server connection for `--queue`, prompting when needed,
and submitting/following a batch."""

import sys
import time

from .client import ServerError, Unreachable
from .config import TOOL_NAME, load_config
from .join import InvalidJoinString, parse as parse_join
from .runner import format_duration
from .serverctl import cmd_server, resolve_client


class _Args:
    """A stand-in for argparse.Namespace, for calling cmd_server programmatically."""
    def __init__(self, **kwargs):
        self.__dict__.update(dict(stop=False, status=False, setup=False, foreground=False, advertise=None,
                                  port=None, new_token=False, join_info=False, log=None, **kwargs))


def _paste_join(parser, ask, out, err):
    text = ask("Paste the join string: ").strip()
    if not text:
        return None
    try:
        parse_join(text)
    except InvalidJoinString as error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return None
    client, error = resolve_client(parser, text)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return None
    return client


def _start_server_here(parser, ask, out, err):
    if cmd_server(_Args(), out, err, ask=ask) != 0:
        return None
    client, error = resolve_client(load_config(), None)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return None
    return client


def resolve_queue_client(ask=input, out=sys.stdout, err=sys.stderr):
    """A working Client for --queue, prompting to set one up if needed. None
    (with a message already printed) if the user gave up."""
    parser = load_config()
    client, error = resolve_client(parser, None)
    if client is None:
        print(f"{TOOL_NAME}: {error}", file=out)
        print("  1) start a server on this machine", file=out)
        print("  2) paste a join string for an existing server", file=out)
        print("  3) cancel", file=out)
        choice = ask("Choose 1, 2 or 3 [1]: ").strip() or "1"
        if choice == "1":
            return _start_server_here(parser, ask, out, err)
        if choice == "2":
            return _paste_join(parser, ask, out, err)
        return None

    try:
        client.health()
        return client
    except Unreachable as reason:
        print(f"{TOOL_NAME}: the remembered server could not be reached: {reason}", file=out)
        print("  1) start a new server on this machine", file=out)
        print("  2) paste a new join string", file=out)
        print("  3) cancel", file=out)
        choice = ask("Choose 1, 2 or 3 [3]: ").strip() or "3"
        if choice == "1":
            return _start_server_here(parser, ask, out, err)
        if choice == "2":
            return _paste_join(parser, ask, out, err)
        return None


def submit_batch(client, recipe_name, jobs, policy, label=None):
    payloads = [{"job": job.to_dict(), "policy": policy.to_dict()} for job in jobs]
    return client.submit(recipe_name, payloads, label=label)


def follow_batch(client, batch_id, out=sys.stdout, sleep=time.sleep):
    """Print progress until the batch finishes; Ctrl-C stops following only."""
    try:
        while True:
            batch = client.batch(batch_id)
            counts = ", ".join(f"{k}={v}" for k, v in batch["counts"].items() if v)
            eta = "ETA --:--" if batch["eta"] is None else f"ETA {format_duration(batch['eta'])}"
            print(f"\rbatch {batch_id}: {batch['progress'] * 100:5.1f}%  {counts}  {eta}" + " " * 8,
                  end="", file=out, flush=True)
            if batch["complete"]:
                print(file=out)
                return batch
            sleep(1)
    except KeyboardInterrupt:
        print(f"\n{TOOL_NAME}: no longer following; batch {batch_id} keeps running on the server.", file=out)
        return None
    except ServerError as error:
        print(f"\n{TOOL_NAME}: lost contact with the server: {error}", file=out)
        return None
