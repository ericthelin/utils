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

Usage: hist_search.py [initial-query]

If given, initial-query seeds the search box with whatever the user
had already typed on the command line, so the picker starts filtered
instead of showing the full history.

Appearance is controlled by a theme, selected via the HIST_SEARCH_THEME
env var ("default" or "fzf"; see THEMES). Settings are resolved with
this precedence (later wins): built-in theme -> dotfile -> env var.

Dotfile: ~/.hist_searchrc (or $HIST_SEARCH_CONFIG), simple `key=value`
lines, '#' starts a comment. Recognized keys: theme, layout,
selected_style, selected_indicator, unselected_indicator, info_style,
mode_style. Example:
  theme=fzf
  selected_style=1;36

Any individual field can also be overridden via env vars, regardless
of the chosen theme or dotfile:
  HIST_SEARCH_THEME                theme name
  HIST_SEARCH_CONFIG               dotfile path (default ~/.hist_searchrc)
  HIST_SEARCH_LAYOUT               "below" (default) or "above" (fzf-style)
  HIST_SEARCH_SELECTED_STYLE       SGR code, e.g. "1;36"
  HIST_SEARCH_SELECTED_INDICATOR   e.g. "> "
  HIST_SEARCH_UNSELECTED_INDICATOR e.g. "  "
  HIST_SEARCH_INFO_STYLE           SGR code for the footer/info line
  HIST_SEARCH_MODE_STYLE           SGR code for the [FUZZY]/[REGEX] label
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

RESET = "\x1b[0m"

# Built-in themes. "layout" is "below" (prompt on top, matches below it,
# growing downward - the original look) or "above" (fzf's default look:
# info line on top, matches above the prompt in reverse order so the
# best match sits right above the prompt). Style fields hold raw SGR
# codes (e.g. "1;36"), not full escape sequences; empty string means no
# styling.
THEMES = {
    "default": {
        "layout": "below",
        "selected_style": "1;36;7",  # bold cyan-on-highlight: strong, readable on any palette
        "selected_indicator": "> ",
        "unselected_indicator": "  ",
        "info_style": "90",  # bright black/gray
        "mode_style": "1;33",  # bold yellow
    },
    "fzf": {
        "layout": "above",
        "selected_style": "36",
        "selected_indicator": "> ",
        "unselected_indicator": "  ",
        "info_style": "32",
        "mode_style": "33",
    },
}

# Env vars that override individual theme fields regardless of which
# named theme was selected, so colors/indicators/layout can be tuned
# without defining a whole new theme.
THEME_ENV_OVERRIDES = {
    "layout": "HIST_SEARCH_LAYOUT",
    "selected_style": "HIST_SEARCH_SELECTED_STYLE",
    "selected_indicator": "HIST_SEARCH_SELECTED_INDICATOR",
    "unselected_indicator": "HIST_SEARCH_UNSELECTED_INDICATOR",
    "info_style": "HIST_SEARCH_INFO_STYLE",
    "mode_style": "HIST_SEARCH_MODE_STYLE",
}

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hist_searchrc")


def _sgr(code):
    return f"\x1b[{code}m" if code else ""


def read_config_file(path):
    """Parse a simple `key=value` dotfile (blank lines and lines
    starting with '#' are ignored). Returns {} if the file is absent.

    Recognized keys: "theme" plus every field in THEME_ENV_OVERRIDES
    (layout, selected_style, selected_indicator, unselected_indicator,
    info_style, mode_style). Unknown keys are ignored.
    """
    if not path or not os.path.exists(path):
        return {}
    config = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


def build_theme(name=None):
    """Resolve a theme, in increasing order of precedence:

    1. built-in THEMES[name]
    2. the dotfile (~/.hist_searchrc, or $HIST_SEARCH_CONFIG)
    3. per-field env var overrides (THEME_ENV_OVERRIDES)

    `name` (falling back to $HIST_SEARCH_THEME, then the dotfile's
    "theme" key, then "default") selects which built-in theme to start
    from.
    """
    config = read_config_file(os.environ.get("HIST_SEARCH_CONFIG", DEFAULT_CONFIG_PATH))

    name = name or os.environ.get("HIST_SEARCH_THEME") or config.get("theme") or "default"
    theme = dict(THEMES.get(name, THEMES["default"]))

    for field in THEME_ENV_OVERRIDES:
        if field in config:
            theme[field] = config[field]

    for field, env_name in THEME_ENV_OVERRIDES.items():
        if env_name in os.environ:
            theme[field] = os.environ[env_name]

    return theme


def arrange_rows(prompt_line, body_lines, footer_line, layout):
    """Order the prompt/list/footer rows for the given layout.

    Returns (lines, prompt_row): lines is the full set of rows to draw
    top-to-bottom; prompt_row is the index within lines holding the
    prompt, so the cursor can be parked there after drawing.
    """
    if layout == "above":
        lines = [footer_line] + list(reversed(body_lines)) + [prompt_line]
        return lines, len(lines) - 1
    return [prompt_line] + body_lines + [footer_line], 0


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
    """Read one logical keypress (handles arrow/page-key escape sequences).

    Arrow keys normally arrive as CSI sequences ("\x1b[A"), but terminals
    left in "application cursor keys" mode (DECCKM, e.g. after another
    program didn't clean up) send SS3 sequences ("\x1bOA") instead. Both
    forms are normalized to the CSI form so callers only match one shape.

    PageUp/PageDown are longer CSI sequences with parameter bytes before
    the final byte (e.g. "\x1b[5~"), so the whole sequence is read up to
    its terminator instead of assuming a fixed length.
    """
    b = os.read(fd, 1)
    if b != b"\x1b":
        return b
    # A lone Esc has nothing pending; an arrow/page key sends more bytes
    # immediately after, so a short poll tells them apart.
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        return b"\x1b"
    b2 = os.read(fd, 1)
    if b2 == b"O":
        b3 = os.read(fd, 1)
        return b"\x1b[" + b3
    if b2 != b"[":
        return b"\x1b" + b2
    seq = b"\x1b["
    while True:
        b3 = os.read(fd, 1)
        seq += b3
        # CSI final bytes are 0x40-0x7E; parameter/intermediate bytes
        # (digits, ';', etc.) fall below that and keep the sequence going.
        if b3 and 0x40 <= b3[0] <= 0x7E:
            break
    return seq


def run_ui(tty_fd, commands, width, list_height, theme, initial_query=""):
    """Draw and drive the inline picker; return the selected command or None."""
    total_rows = list_height + 2  # prompt line + matches + footer line
    query = initial_query
    cursor = len(query)  # edit position within query, for Left/Right
    regex_mode = False
    selected = 0
    top = 0
    # Which row (0 = top of the reserved strip) the terminal cursor is
    # currently resting on. Needed because the prompt (where the cursor
    # should visually sit) isn't always the top row - in "above" layout
    # it's the bottom one - so each redraw must first hop back up to the
    # top before repainting, instead of assuming it's already there.
    cursor_row = 0
    reversed_nav = theme["layout"] == "above"

    def move_selection(screen_rows_up):
        """Move the highlight by N rows up the screen (negative moves
        down), independent of layout: in "above" layout the match list
        is visually reversed, so moving up the screen means increasing
        the underlying match index rather than decreasing it."""
        nonlocal selected
        if reversed_nav:
            selected = max(0, selected + screen_rows_up)
        else:
            selected = max(0, selected - screen_rows_up)

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
        nonlocal selected, top, cursor_row
        if selected >= len(matches):
            selected = max(0, len(matches) - 1)
        if selected < top:
            top = selected
        if selected >= top + list_height:
            top = selected - list_height + 1

        mode = "REGEX" if regex_mode else "FUZZY"
        mode_style = _sgr(theme["mode_style"])
        mode_label = f"[{mode}]"
        if mode_style:
            mode_label = f"{mode_style}{mode_label}{RESET}"
        plain_prefix = f"[{mode}] > "
        prompt_line = f"{mode_label} > {query}"

        body_lines = []
        for row in range(list_height):
            i = top + row
            if i >= len(matches):
                body_lines.append("")
                continue
            _idx, cmd = matches[i]
            text = cmd.replace("\n", " ⏎ ")
            is_selected = i == selected
            indicator = theme["selected_indicator"] if is_selected else theme["unselected_indicator"]
            line = (indicator + text)[: width - 1]
            if is_selected:
                sel_style = _sgr(theme["selected_style"])
                if sel_style:
                    line = f"{sel_style}{line}{RESET}"
            body_lines.append(line)

        position = selected + 1 if matches else 0
        footer = f"{position}/{len(matches)}  Enter:select  Tab:toggle-regex  Ctrl-C/Esc:cancel"
        footer_line = footer[: width - 1]
        info_style = _sgr(theme["info_style"])
        if info_style:
            footer_line = f"{info_style}{footer_line}{RESET}"

        lines, prompt_row = arrange_rows(prompt_line, body_lines, footer_line, theme["layout"])

        out = []
        # Always return to column 0 before repainting: the previous
        # frame may have left the cursor mid-line (parked at the query
        # edit position), and "up"/"down" row moves don't touch column.
        out.append("\r")
        if cursor_row:
            out.append(f"\x1b[{cursor_row}A")
        for i, line in enumerate(lines):
            out.append("\x1b[2K" + line)
            if i < len(lines) - 1:
                out.append("\r\n")
        out.append("\r")
        up = len(lines) - 1
        if up:
            out.append(f"\x1b[{up}A")
        if prompt_row:
            out.append(f"\x1b[{prompt_row}B")
        # Column 0 was already reached above; move right to park the
        # real cursor at the edit position within the query text.
        target_col = len(plain_prefix) + cursor
        if target_col:
            out.append(f"\x1b[{target_col}C")
        cursor_row = prompt_row
        write("".join(out))
        return matches

    def clear_and_home():
        nonlocal cursor_row
        out = ["\r"]
        if cursor_row:
            out.append(f"\x1b[{cursor_row}A")
            cursor_row = 0
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
                move_selection(1)
            elif key in (b"\x1b[B", b"\x0e"):  # Down / Ctrl-N
                move_selection(-1)
            elif key == b"\x1b[5~":  # Page Up
                move_selection(list_height)
            elif key == b"\x1b[6~":  # Page Down
                move_selection(-list_height)
            elif key in (b"\x1b[D", b"\x02"):  # Left / Ctrl-B
                cursor = max(0, cursor - 1)
            elif key in (b"\x1b[C", b"\x06"):  # Right / Ctrl-F
                cursor = min(len(query), cursor + 1)
            elif key in (b"\x1b[H", b"\x1b[1~", b"\x01"):  # Home / Ctrl-A
                cursor = 0
            elif key in (b"\x1b[F", b"\x1b[4~", b"\x05"):  # End / Ctrl-E
                cursor = len(query)
            elif key == b"\x1b[3~":  # Delete (forward)
                if cursor < len(query):
                    query = query[:cursor] + query[cursor + 1 :]
                    selected = 0
                    top = 0
            elif key == b"\x0b":  # Ctrl-K: kill to end of line
                if cursor < len(query):
                    query = query[:cursor]
                    selected = 0
                    top = 0
            elif key == b"\x15":  # Ctrl-U: kill to start of line
                if cursor > 0:
                    query = query[cursor:]
                    cursor = 0
                    selected = 0
                    top = 0
            elif key in (b"\x7f", b"\x08"):
                if cursor > 0:
                    query = query[: cursor - 1] + query[cursor:]
                    cursor -= 1
                    selected = 0
                    top = 0
            else:
                if len(key) == 1 and 0x20 <= key[0] < 0x7F:
                    query = query[:cursor] + key.decode() + query[cursor:]
                    cursor += 1
                    selected = 0
                    top = 0
    except BaseException:
        clear_and_home()
        raise


def main():
    commands = read_history(default_histfile())
    if not commands:
        return 0

    theme = build_theme()
    initial_query = sys.argv[1] if len(sys.argv) > 1 else ""

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    old_attrs = termios.tcgetattr(tty_fd)
    try:
        tty.setraw(tty_fd)
        rows, cols = _term_size(tty_fd)
        list_height = max(1, min(MAX_VISIBLE_ROWS, rows - 4))
        result = run_ui(tty_fd, commands, cols, list_height, theme, initial_query)
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_attrs)
        os.close(tty_fd)

    if result:
        sys.stdout.write(result)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
