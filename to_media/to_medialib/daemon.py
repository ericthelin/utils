"""Starting, stopping and checking on a background copy of this program."""

import os
import signal
import sys
import time


def pidfile_path(config_dir, name):
    return os.path.join(config_dir, f"{name}.pid")


def read_pid(path):
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def is_running(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def status(path):
    """The pid of the process this pidfile names, or None if it is not running."""
    pid = read_pid(path)
    return pid if is_running(pid) else None


def stop(path, timeout=10):
    """Ask the process to stop and wait for it to go; returns whether it did."""
    pid = status(path)
    if pid is None:
        return True
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(pid):
            try:
                os.unlink(path)
            except OSError:
                pass
            return True
        time.sleep(0.1)
    return False


def spawn_background(argv, pidfile, log_path=None):
    """Re-exec this program with `argv` detached from the terminal, writing its
    pid to `pidfile`. `argv[0]` should be sys.executable or the command itself."""
    import subprocess

    os.makedirs(os.path.dirname(pidfile) or ".", exist_ok=True)
    if log_path:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        out = open(log_path, "a")
    else:
        out = subprocess.DEVNULL
    kwargs = dict(stdin=subprocess.DEVNULL, stdout=out, stderr=out, close_fds=True)
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(argv, **kwargs)
    if log_path:
        out.close()
    with open(pidfile, "w") as handle:
        handle.write(str(process.pid))
    # Reap it in the background so it never sits as a zombie once it exits;
    # this process stays its parent since it was not double-forked.
    import threading
    threading.Thread(target=process.wait, daemon=True).start()
    return process.pid
