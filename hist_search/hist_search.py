#!/usr/bin/env python3
"""Fuzzy/regex interactive shell history search (fzf Ctrl-R replacement).

Reads zsh (or bash) history, shows an inline picker (drawn in a small
reserved strip at the cursor, like fzf's default mode) with live fuzzy
or regex filtering, and prints the selected command line to stdout so
a shell widget can drop it onto the command line buffer for editing.

The picker never clears or takes over the whole screen: existing
terminal content is pushed up (scrolled) to make room, and that same
room is handed back (cleared) when the picker exits.

Draws the UI on /dev/tty so stdout can still be captured with $(...)
by the calling shell widget (see zsh_hist_search_widget.zsh).
"""

import os
import re
import select
import sys
import termios
import tty


def default_histfile():
    hist = os.environ.get("HISTFILE")
    if hist:
        return hist
    for name in ("~/.zsh_history", "~/.bash_history"):
        path = os.path.expanduser(name)
        if os.path.exists(path):
            return path
    return os.path.expanduser("~/.zsh_history")


def read_history(path):
    """Return commands, most recent first, de-duplicated."""
    if not os.path.exists(path):
        return []

    with open(path, "rb") as f:
        raw = f.read().decode("utf-8", errors="replace")

    lines = raw.split("\n")
    commands = []
    buf = None
    for line in lines:
        # zsh extended history: ": <epoch>:<duration>;command"
        m = re.match(r"^: \d+:\d+;(.*)$", line) if buf is None else None
        if buf is not None:
            # continuation of a backslash-continued command
            if line.endswith("\\"):
                buf += "\n" + line[:-1]
                continue
            buf += "\n" + line
            commands.append(buf)
            buf = None
            continue
        if m:
            cmd = m.group(1)
        else:
            cmd = line
        if cmd.endswith("\\"):
            buf = cmd[:-1]
            continue
        if cmd != "" and not re.match(r"^#\d{9,}$", cmd):
            commands.append(cmd)
    if buf is not None:
        commands.append(buf)

    seen = set()
    deduped = []
    for cmd in reversed(commands):
        if cmd not in seen:
            seen.add(cmd)
            deduped.append(cmd)
    return deduped


def fuzzy_score(query, text):
    """Return score (lower is better) or None if no match.

    Builds a real regex out of the query characters (each character
    separated by a non-greedy "anything in between"), so matching is
    driven by the re module rather than manual string scanning. The
    match with the smallest span (most compact) and earliest start
    wins, which naturally favors contiguous substrings over scattered
    subsequence matches.
    """
    if not query:
        return 0
    pattern = ".*?".join(re.escape(ch) for ch in query)
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    span = m.end() - m.start()
    return (span, m.start())


def regex_score(query, text):
    if not query:
        return 0
    try:
        m = re.search(query, text)
    except re.error:
        return None
    if not m:
        return None
    return m.start()


MAX_VISIBLE_ROWS = 10


def filter_commands(commands, query, regex_mode):
    if not query:
        return list(enumerate(commands))
    scorer = regex_score if regex_mode else fuzzy_score
    scored = []
    for idx, cmd in enumerate(commands):
        score = scorer(query, cmd)
        if score is not None:
            scored.append((score, idx, cmd))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [(idx, cmd) for _score, idx, cmd in scored]


def _term_size(fd):
    import fcntl
    import struct

    try:
        rows, cols = struct.unpack("hh", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0\0\0\0"))
        if rows > 0 and cols > 0:
            return rows, cols
    except OSError:
        pass
    return 24, 80


def _read_key(fd):
    """Read one logical keypress (handles arrow-key escape sequences).

    Arrow keys normally arrive as CSI sequences ("\x1b[A"), but terminals
    left in "application cursor keys" mode (DECCKM, e.g. after another
    program didn't clean up) send SS3 sequences ("\x1bOA") instead. Both
    forms are normalized to the CSI form so callers only match one shape.
    """
    b = os.read(fd, 1)
    if b != b"\x1b":
        return b
    # A lone Esc has nothing pending; an arrow key sends more bytes
    # immediately after, so a short poll tells them apart.
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return b"\x1b"
    b2 = os.read(fd, 1)
    if b2 not in (b"[", b"O"):
        return b"\x1b" + b2
    b3 = os.read(fd, 1)
    return b"\x1b[" + b3


def run_ui(tty_fd, commands, width, list_height):
    """Draw and drive the inline picker; return the selected command or None."""
    total_rows = list_height + 2  # prompt line + matches + footer line
    query = ""
    regex_mode = False
    selected = 0
    top = 0

    def write(s):
        os.write(tty_fd, s.encode())

    # Make sure arrow keys arrive as normal CSI sequences even if a
    # previous program left the terminal in application cursor-key mode.
    write("\x1b[?1l")
    # Reserve room by scrolling existing content up, then move back to
    # the top-left of that freshly reserved strip.
    write("\n" * total_rows)
    write(f"\x1b[{total_rows}A\r")

    def render():
        matches = filter_commands(commands, query, regex_mode)
        nonlocal selected, top
        if selected >= len(matches):
            selected = max(0, len(matches) - 1)
        if selected < top:
            top = selected
        if selected >= top + list_height:
            top = selected - list_height + 1

        mode = "REGEX" if regex_mode else "FUZZY"
        lines = [f"[{mode}] > {query}"]
        for row in range(list_height):
            i = top + row
            if i >= len(matches):
                lines.append("")
                continue
            _idx, cmd = matches[i]
            text = cmd.replace("\n", " \u23ce ")
            marker = "> " if i == selected else "  "
            lines.append((marker + text)[: width - 1])
        footer = f"{len(matches)}/{len(commands)}  Enter:select  Tab:toggle-regex  Ctrl-C/Esc:cancel"
        lines.append(footer[: width - 1])

        out = []
        for i, line in enumerate(lines):
            out.append("\x1b[2K" + line[: width - 1])
            if i < len(lines) - 1:
                out.append("\r\n")
        out.append("\r")
        out.append(f"\x1b[{total_rows - 1}A")
        write("".join(out))
        return matches

    def clear_and_home():
        out = []
        for i in range(total_rows):
            out.append("\x1b[2K")
            if i < total_rows - 1:
                out.append("\r\n")
        out.append("\r")
        out.append(f"\x1b[{total_rows - 1}A")
        write("".join(out))

    try:
        while True:
            matches = render()
            key = _read_key(tty_fd)
            if key in (b"\r", b"\n"):
                clear_and_home()
                return matches[selected][1] if matches else None
            elif key in (b"\x1b", b"\x03"):  # Esc / Ctrl-C
                clear_and_home()
                return None
            elif key == b"\t":
                regex_mode = not regex_mode
                selected = 0
                top = 0
            elif key in (b"\x1b[A", b"\x10"):  # Up / Ctrl-P
                selected = max(0, selected - 1)
            elif key in (b"\x1b[B", b"\x0e"):  # Down / Ctrl-N
                selected += 1
            elif key in (b"\x7f", b"\x08"):
                query = query[:-1]
                selected = 0
                top = 0
            else:
                if len(key) == 1 and 0x20 <= key[0] < 0x7F:
                    query += key.decode()
                    selected = 0
                    top = 0
    except BaseException:
        clear_and_home()
        raise


def main():
    commands = read_history(default_histfile())
    if not commands:
        return 0

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    old_attrs = termios.tcgetattr(tty_fd)
    try:
        tty.setraw(tty_fd)
        rows, cols = _term_size(tty_fd)
        list_height = max(1, min(MAX_VISIBLE_ROWS, rows - 4))
        result = run_ui(tty_fd, commands, cols, list_height)
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_attrs)
        os.close(tty_fd)

    if result:
        sys.stdout.write(result)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
