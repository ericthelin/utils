"""The `server`, `worker`, `jobs`, `status`, `cancel` and `retry` commands."""

import logging
import logging.handlers
import os
import secrets
import socket
import sys
import time

from . import worker as worker_mod
from .client import Client, ServerError, Unreachable
from .config import TOOL_NAME, config_dir, load_config, save_config
from .daemon import pidfile_path, spawn_background, status as daemon_status, stop as daemon_stop
from .join import Join, InvalidJoinString, parse as parse_join

DEFAULT_PORT = 7878
ENTRY_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), f"{TOOL_NAME}.py")


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def local_ip():
    """The address this machine would use to reach the LAN; no packet is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.connect(("198.51.100.1", 80))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def advertised_hosts(choice, custom=None):
    if custom:
        return [custom]
    hostname = socket.gethostname()
    ip = local_ip()
    return {"hostname": [hostname], "ip": [ip], "both": [hostname, ip]}.get(choice, [hostname])


def setup_server(parser, advertise=None, ask=input, out=sys.stdout):
    """Fill in the [server] section, asking what is not already decided."""
    if not parser.has_section("server"):
        parser.add_section("server")
    section = parser["server"]
    section.setdefault("token", secrets.token_urlsafe(24))
    section.setdefault("port", str(free_port()))
    section.setdefault("host", "0.0.0.0")
    section.setdefault("server_id", secrets.token_hex(4))
    if advertise and advertise not in ("hostname", "ip", "both"):
        section["advertise"] = "custom"
        section["advertise_value"] = advertise
    elif advertise:
        section["advertise"] = advertise
        section.pop("advertise_value", None)
    elif "advertise" not in section:
        print("How should workers find this server?", file=out)
        print(f"  1) this machine's hostname ({socket.gethostname()})", file=out)
        print(f"  2) this machine's LAN address ({local_ip()})", file=out)
        print("  3) both", file=out)
        answer = ask("Choose 1, 2 or 3 [1]: ").strip() or "1"
        section["advertise"] = {"1": "hostname", "2": "ip", "3": "both"}.get(answer, "hostname")
    return parser


def join_string(section):
    hosts = advertised_hosts(section.get("advertise", "hostname"), section.get("advertise_value"))
    return Join(token=section["token"], hosts=hosts, port=int(section["port"]),
               server_id=section.get("server_id", ""))


def make_logger(log_choice, name, foreground):
    logger = logging.getLogger(f"to_media.{name}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    if log_choice == "console" or (foreground and not log_choice):
        handler = logging.StreamHandler(sys.stderr)
    elif log_choice == "syslog":
        try:
            handler = logging.handlers.SysLogHandler(address="/dev/log")
        except OSError:
            handler = logging.FileHandler(os.path.join(config_dir(), f"{name}.log"))
    elif log_choice:
        handler = logging.FileHandler(log_choice)
    else:
        handler = logging.FileHandler(os.path.join(config_dir(), f"{name}.log"))
    handler.setFormatter(logging.Formatter(f"%(asctime)s {name} %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def print_join_info(section, out):
    join = join_string(section)
    print(f"join string: {join}", file=out)
    print(f"status page: {join.url()}/status?token={section['token']}", file=out)
    if not has_openssl():
        print(f"{TOOL_NAME}: warning: openssl was not found; the connection is unencrypted.", file=out)


def has_openssl():
    import shutil
    return bool(shutil.which("openssl"))


# server ---------------------------------------------------------------------

def remember_locally(parser, section):
    """A machine running the server also has a working client config for
    it, so `jobs`/`status`/`--queue` work here with no extra setup."""
    join = str(join_string(section))
    if not parser.has_section("client"):
        parser.add_section("client")
    if parser["client"].get("server") != join:
        parser["client"]["server"] = join
        save_config(parser)


def cmd_server(args, out, err, ask=input):
    parser = load_config()
    pidfile = pidfile_path(config_dir(), "server")

    if args.stop:
        if daemon_stop(pidfile):
            print(f"{TOOL_NAME}: server stopped.", file=out)
            return 0
        print(f"{TOOL_NAME}: server did not stop in time.", file=err)
        return 1

    if args.status:
        pid = daemon_status(pidfile)
        if pid is None:
            print(f"{TOOL_NAME}: server is not running.", file=out)
            return 1
        print(f"{TOOL_NAME}: server running (pid {pid}).", file=out)
        if parser.has_section("server"):
            print_join_info(parser["server"], out)
        return 0

    first_run = not parser.has_section("server") or not parser["server"].get("token")
    if args.setup or first_run:
        setup_server(parser, advertise=args.advertise, ask=ask, out=out)
        save_config(parser)
    elif args.advertise:
        parser["server"]["advertise"] = "custom" if args.advertise not in ("hostname", "ip", "both") else args.advertise
        if parser["server"]["advertise"] == "custom":
            parser["server"]["advertise_value"] = args.advertise
        save_config(parser)
    if args.port:
        parser["server"]["port"] = str(args.port)
        save_config(parser)
    if args.new_token:
        parser["server"]["token"] = secrets.token_urlsafe(24)
        save_config(parser)
        print(f"{TOOL_NAME}: token rotated; old join strings no longer work. Restart the server to apply it.",
              file=out)

    if args.join_info:
        print_join_info(parser["server"], out)
        return 0

    section = parser["server"]
    remember_locally(parser, section)

    # A foregrounded run *is* the server (this is what the background command
    # below re-execs into); it must never consult the pidfile, since by the
    # time it runs, that pidfile already names this very process.
    if args.foreground:
        from .server import Server
        make_logger(args.log, "server", foreground=True)
        if not has_openssl():
            print(f"{TOOL_NAME}: warning: openssl was not found; the connection is unencrypted.", file=out)
        server = Server(os.path.join(config_dir(), "jobs.db"), host=section["host"],
                        port=int(section["port"]), token=section["token"])
        print_join_info(section, out)
        server.serve_forever()
        return 0

    running_pid = daemon_status(pidfile)
    if running_pid:
        print(f"{TOOL_NAME}: server already running here (pid {running_pid}).", file=out)
        print_join_info(section, out)
        return 0

    if not has_openssl():
        print(f"{TOOL_NAME}: warning: openssl was not found; the connection is unencrypted.", file=out)

    log_path = args.log if args.log not in (None, "", "console", "syslog") else os.path.join(
        config_dir(), "server.log")
    pid = spawn_background([sys.executable, ENTRY_SCRIPT, "server", "--foreground", "--log", args.log or "syslog"],
                           pidfile, log_path=log_path)
    for _ in range(50):
        time.sleep(0.1)
        try:
            Client(join_string(section).url(), token=section["token"], timeout=2).health()
            break
        except ServerError:
            continue
    else:
        print(f"{TOOL_NAME}: server did not come up in time; check its log.", file=err)
        return 1
    print(f"{TOOL_NAME}: server started in the background (pid {pid}).", file=out)
    print_join_info(section, out)
    return 0


# worker -----------------------------------------------------------------

def resolve_client(parser, join_arg=None):
    """The Client the worker or a queue command should use, or an error string."""
    if join_arg:
        try:
            join = parse_join(join_arg)
        except InvalidJoinString as error:
            return None, str(error)
        if not parser.has_section("client"):
            parser.add_section("client")
        parser["client"]["server"] = str(join)
        save_config(parser)
        return Client(join.url(), token=join.token), None
    if parser.has_section("client") and parser["client"].get("server"):
        join = parse_join(parser["client"]["server"])
        return Client(join.url(), token=join.token), None
    return None, "no server is remembered; run with a join string, e.g. `to_media worker tomedia://...`"


def cmd_worker(args, out, err):
    parser = load_config()
    pidfile = pidfile_path(config_dir(), "worker")

    if args.stop:
        if daemon_stop(pidfile):
            print(f"{TOOL_NAME}: worker stopped.", file=out)
            return 0
        print(f"{TOOL_NAME}: worker did not stop in time.", file=err)
        return 1
    if args.status:
        pid = daemon_status(pidfile)
        print(f"{TOOL_NAME}: worker {'running (pid ' + str(pid) + ').' if pid else 'is not running.'}", file=out)
        return 0 if pid else 1

    client, error = resolve_client(parser, args.join)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return 2
    try:
        client.health()
    except ServerError as error:
        print(f"{TOOL_NAME}: could not reach the server: {error}", file=err)
        return 1
    if not has_openssl():
        print(f"{TOOL_NAME}: warning: openssl was not found; the connection is unencrypted.", file=out)

    if args.foreground:
        make_logger(args.log, "worker", foreground=True)
        worker_mod.run_forever(client, capabilities=list(args.recipes) if args.recipes else None, slots=args.slots)
        return 0

    log_path = args.log if args.log not in (None, "", "console", "syslog") else os.path.join(
        config_dir(), "worker.log")
    argv = [sys.executable, ENTRY_SCRIPT, "worker", "--foreground", "--slots", str(args.slots),
           "--log", args.log or "syslog"]
    if args.recipes:
        argv += ["--recipes", ",".join(args.recipes)]
    pid = spawn_background(argv, pidfile, log_path=log_path)
    print(f"{TOOL_NAME}: worker started in the background (pid {pid}).", file=out)
    return 0


# jobs / status / cancel / retry ------------------------------------------

def format_duration(seconds):
    from .runner import format_duration as fmt
    return fmt(seconds)


def print_status(client, out):
    for batch in client.batches():
        counts = ", ".join(f"{k}={v}" for k, v in batch["counts"].items() if v)
        eta = "eta --:--" if batch["eta"] is None else f"eta {format_duration(batch['eta'])}"
        label = f" ({batch['label']})" if batch["label"] else ""
        print(f"batch {batch['id']}{label}: {batch['recipe']}  {batch['progress'] * 100:5.1f}%  "
              f"{counts}  {eta}", file=out)
    for worker in client.workers():
        job = f"job {worker['job']}" if worker["job"] else "idle"
        print(f"worker {worker['id']}: {job}, last seen {time.time() - worker['last_seen']:.0f}s ago", file=out)


def cmd_status(args, out, err):
    parser = load_config()
    client, error = resolve_client(parser, None)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return 2
    try:
        if args.watch:
            while True:
                print_status(client, out)
                time.sleep(args.watch)
                print(file=out)
        print_status(client, out)
    except Unreachable as error:
        print(f"{TOOL_NAME}: could not reach the server: {error}", file=err)
        return 1
    except KeyboardInterrupt:
        pass
    return 0


def cmd_jobs(args, out, err):
    parser = load_config()
    client, error = resolve_client(parser, None)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return 2
    try:
        jobs = client.jobs(states=[args.state] if args.state else None, batch_id=args.batch, limit=args.limit)
    except Unreachable as error:
        print(f"{TOOL_NAME}: could not reach the server: {error}", file=err)
        return 1
    for job in jobs:
        print(f"{job['id']:>6}  {job['state']:<10}{job['progress'] * 100:5.1f}%  batch {job['batch_id']:<4}"
              f"{os.path.basename(job['payload']['job']['output'])}", file=out)
    return 0


def cmd_cancel(args, out, err):
    return _cmd_job_or_batch(args, out, err, "cancel", "cancelled")


def cmd_retry(args, out, err):
    return _cmd_job_or_batch(args, out, err, "retry", "retried")


def _cmd_job_or_batch(args, out, err, action, verb):
    parser = load_config()
    client, error = resolve_client(parser, None)
    if error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return 2
    try:
        count = getattr(client, action)(job_id=args.job, batch_id=args.batch)
    except ServerError as error:
        print(f"{TOOL_NAME}: {error}", file=err)
        return 1
    print(f"{TOOL_NAME}: {verb} {count} job(s).", file=out)
    return 0
