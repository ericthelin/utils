#!/usr/bin/env python3
"""git-go: switch to a branch, creating it if needed, with a naming prefix check."""

import os
import re
import subprocess
import sys
import tempfile

PREFIXES = ("rc/", "hotfix/", "feature/", "refactor/", "chore/", "spike/", "bugfix/")
HISTORY_LOOKBACK = 5


def has_known_prefix(name):
    return name.startswith(PREFIXES)


def prefixed_name(name, choice):
    """Return the branch name for a menu choice (1-based), or name if none."""
    if choice.isdigit() and 1 <= int(choice) <= len(PREFIXES):
        return PREFIXES[int(choice) - 1] + name
    return name


def rewrite_history_line(line, old, new):
    """Replace the branch argument of a `go <old>` command in one history line."""
    pattern = re.compile(r"(\bgo\s+)([\"']?)" + re.escape(old) + r"\2(?=\s|$)")
    return pattern.sub(lambda m: m.group(1) + m.group(2) + new + m.group(2), line, count=1)


def rewrite_history(lines, old, new, lookback=HISTORY_LOOKBACK):
    """Rewrite the most recent matching entry among the last `lookback` lines."""
    start = max(0, len(lines) - lookback)
    for i in range(len(lines) - 1, start - 1, -1):
        updated = rewrite_history_line(lines[i], old, new)
        if updated != lines[i]:
            lines = list(lines)
            lines[i] = updated
            return lines, True
    return lines, False


def default_histfile():
    hist = os.environ.get("HISTFILE")
    if hist:
        return hist
    for name in ("~/.zsh_history", "~/.bash_history"):
        path = os.path.expanduser(name)
        if os.path.exists(path):
            return path
    return None


def update_history(old, new, path=None):
    path = path or default_histfile()
    if not path or not os.path.isfile(path):
        return False
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        lines = f.read().splitlines(keepends=True)
    lines, changed = rewrite_history(lines, old, new)
    if not changed:
        return False
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.writelines(lines)
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def prompt_for_prefix(name):
    """Ask on the terminal; return the (possibly prefixed) name."""
    try:
        reader = open("/dev/tty", "r")
        tty = open("/dev/tty", "w")
    except OSError:
        return name
    with reader, tty:
        tty.write("Branch '%s' does not start with a standard prefix.\n" % name)
        for number, prefix in enumerate(PREFIXES, 1):
            tty.write("  %d) %s%s\n" % (number, prefix, name))
        tty.write("Choose 1-%d to add a prefix, or press Enter to keep '%s': "
                  % (len(PREFIXES), name))
        tty.flush()
        choice = reader.readline().strip()
    return prefixed_name(name, choice)


def git(*args, quiet=False):
    return subprocess.run(["git", *args],
                          stdout=subprocess.DEVNULL if quiet else None,
                          stderr=subprocess.DEVNULL if quiet else None).returncode


def banner(color, text, name):
    print("\n\033[1;97;%sm  %s: %s  \033[0m\n" % (color, text, name))


def main(argv):
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: git go BRANCH\n\n"
              "Switch to BRANCH, creating it if it does not exist. New branches that\n"
              "do not start with %s\n"
              "offer to add one first." % ", ".join(PREFIXES))
        return 0 if argv and argv[0] in ("-h", "--help") else 2

    name = argv[0]
    if git("show-ref", "--verify", "--quiet", "refs/heads/" + name, quiet=True) == 0:
        status = git("checkout", name)
        if status == 0:
            banner("44", "✔ REUSED EXISTING BRANCH", name)
        return status

    original = name
    if not has_known_prefix(name):
        name = prompt_for_prefix(name)
    status = git("checkout", "-b", name)
    if status != 0:
        return status
    banner("42", "★ CREATED NEW BRANCH", name)
    if name != original:
        update_history(original, name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
