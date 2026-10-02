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
  HIST_SEARCH_MODE_STYLE           SGR code for the [FUZZY RECENT]-style label

Fuzzy mode also understands fzf-style extended search syntax:
  space-separated terms     AND (every term must match)
  term1|term2                OR, no spaces around '|'
  ^term                      match must start with term
  term$                      match must end with term
  ^term$                     match must equal term exactly
  'term                      match must contain term as an exact substring
  !term (and the ^/$/' forms above) negate the term
Matching is case-insensitive unless the query contains an uppercase
letter, in which case it becomes case-sensitive (smart case, like fzf).
The query box also accepts Unicode input (e.g. accented letters), not
just ASCII.

The query/match list supports a mouse: wheel up/down moves the
selection, and clicking a row selects it (click-to-select needs the
terminal to answer a cursor-position query, so it is silently
unavailable in environments that do not, e.g. some multiplexers).
Requires a terminal that understands SGR mouse reporting.

Key bindings can be rebound (actions: select, cancel, cycle_mode, up,
down, page_up, page_down, left, right, home, end, delete, kill_to_end,
kill_to_start, backspace) via a dotfile line (key_<action>=<spec>) or a
HIST_SEARCH_KEY_<ACTION> env var (env wins), using names like "tab",
"enter", "esc", "up", "ctrl-y". Example:
  key_cancel=ctrl-g

The terminal can be resized while the picker is open; the picker
reflows to the new width, but keeps its original height/scroll
position to avoid losing its place on screen.
"""

import os
import re
import select
import signal
import sys
import termios
import time
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


def fuzzy_score(query, text, case_sensitive=False):
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
    flags = 0 if case_sensitive else re.IGNORECASE
    m = re.search(pattern, text, flags)
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


def _is_special_term(term):
    """True if `term` uses fzf-style extended-search syntax (prefix
    '^', suffix '$', exact-substring "'", or negation '!') rather than
    being a plain fuzzy term."""
    return term.startswith(("^", "!", "'")) or term.endswith("$")


def parse_extended_query(query):
    """Split an fzf-style extended-search query into AND groups of OR
    alternatives.

    Top-level tokens are space-separated (AND). A token containing '|'
    is itself a set of OR alternatives (e.g. "foo|bar baz" means (foo OR
    bar) AND baz), matching fzf's extended-search mode.
    """
    return [token.split("|") for token in query.split()]


def _match_leaf(leaf, text, case_sensitive):
    """Evaluate one extended-syntax leaf term against text.

    Returns (matched, score): score is a (span, start) tuple used only
    to rank matches (lower ranks first); exact/anchor/negated leaves
    that match contribute (0, 0) since they have no useful span to rank
    by, only the plain-fuzzy case produces a real span.
    """
    negate = leaf.startswith("!")
    if negate:
        leaf = leaf[1:]
    if not leaf:
        return (not negate, (0, 0))

    if not (leaf.startswith("^") or leaf.startswith("'") or leaf.endswith("$")):
        score = fuzzy_score(leaf, text, case_sensitive)
        matched = score is not None
        if negate:
            return (not matched, (0, 0))
        return (matched, score if matched else (0, 0))

    haystack = text if case_sensitive else text.lower()
    needle = leaf if case_sensitive else leaf.lower()
    if needle.startswith("^") and needle.endswith("$") and len(needle) > 1:
        matched = haystack == needle[1:-1]
    elif needle.startswith("^"):
        matched = haystack.startswith(needle[1:])
    elif needle.endswith("$"):
        matched = haystack.endswith(needle[:-1])
    else:  # leading "'": exact substring
        matched = needle[1:] in haystack
    if negate:
        matched = not matched
    return (matched, (0, 0))


def extended_score(query, text):
    """fzf-style extended search on top of plain fuzzy matching.

    A query is split into space-separated AND groups, each of which may
    be a set of '|'-joined OR alternatives (see parse_extended_query).
    Each leaf term is a plain fuzzy term, or uses one of fzf's markers:
    '^prefix', 'suffix$', '^exact$', "'exact-substring", or a '!'-negated
    form of any of those. Smart-case applies to the whole query: any
    uppercase letter anywhere makes every term case-sensitive.

    Returns a combined score (lower ranks first) if every AND group has
    at least one matching alternative, else None. A single plain term
    (the common case) is forwarded straight to fuzzy_score.
    """
    if not query:
        return 0

    groups = parse_extended_query(query)
    case_sensitive = any(ch.isupper() for ch in query)
    if len(groups) == 1 and len(groups[0]) == 1 and not _is_special_term(groups[0][0]):
        return fuzzy_score(query, text, case_sensitive)

    total_span = 0
    total_start = 0
    for group in groups:
        best = None
        for leaf in group:
            matched, score = _match_leaf(leaf, text, case_sensitive)
            if matched and (best is None or score < best):
                best = score
        if best is None:
            return None
        total_span += best[0]
        total_start += best[1]
    return (total_span, total_start)


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


# Default key bindings, as the raw byte sequences _read_key() produces.
# Each action maps to a tuple of alternative sequences that trigger it.
DEFAULT_KEYMAP = {
    "select": (b"\r", b"\n"),
    "cancel": (b"\x1b", b"\x03"),
    "cycle_mode": (b"\t",),
    "up": (b"\x1b[A", b"\x10"),
    "down": (b"\x1b[B", b"\x0e"),
    "page_up": (b"\x1b[5~",),
    "page_down": (b"\x1b[6~",),
    "left": (b"\x1b[D", b"\x02"),
    "right": (b"\x1b[C", b"\x06"),
    "home": (b"\x1b[H", b"\x1b[1~", b"\x01"),
    "end": (b"\x1b[F", b"\x1b[4~", b"\x05"),
    "delete": (b"\x1b[3~",),
    "kill_to_end": (b"\x0b",),
    "kill_to_start": (b"\x15",),
    "backspace": (b"\x7f", b"\x08"),
}

# Named keys recognized by _parse_key_spec, for config/env key rebinding.
NAMED_KEYS = {
    "enter": b"\r",
    "tab": b"\t",
    "esc": b"\x1b",
    "escape": b"\x1b",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "left": b"\x1b[D",
    "right": b"\x1b[C",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "delete": b"\x1b[3~",
    "backspace": b"\x7f",
}

# Actions that can be rebound via a "key_<action>" dotfile line or a
# HIST_SEARCH_KEY_<ACTION> env var (env wins). Rebinding an action
# replaces its default bindings with the single given key.
KEY_BIND_ENV = {action: f"HIST_SEARCH_KEY_{action.upper()}" for action in DEFAULT_KEYMAP}


def _parse_key_spec(spec):
    """Parse a user-facing key name ("tab", "ctrl-y", ...) into the raw
    byte sequence _read_key() would produce for it, or None if `spec`
    isn't recognized."""
    spec = spec.strip().lower()
    if spec in NAMED_KEYS:
        return NAMED_KEYS[spec]
    m = re.match(r"^ctrl-([a-z])$", spec)
    if m:
        return bytes([ord(m.group(1)) - ord("a") + 1])
    return None


def build_keymap(config=None):
    """Resolve the active keymap: DEFAULT_KEYMAP, with any action
    overridden by a dotfile `key_<action>=<spec>` line or a
    HIST_SEARCH_KEY_<ACTION> env var (env wins; see KEY_BIND_ENV)."""
    config = config or {}
    keymap = dict(DEFAULT_KEYMAP)
    for action, env_name in KEY_BIND_ENV.items():
        spec = os.environ.get(env_name) or config.get(f"key_{action}")
        if not spec:
            continue
        parsed = _parse_key_spec(spec)
        if parsed:
            keymap[action] = (parsed,)
    return keymap


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


def filter_commands(commands, query, regex_mode, best_match=False):
    """Return matches for query, in either "best match" or "most recent"
    order.

    `best_match=True` ranks by score (span/position for fuzzy, match
    start for regex), same as before. `best_match=False` (the default)
    keeps matches in the order they were found while scanning
    `commands`, which is already most-recent-first (see read_history),
    so recency wins over match quality.

    Fuzzy mode supports fzf-style extended-search syntax (AND/OR terms,
    anchors, exact substrings, negation - see extended_score) and
    smart-case matching.
    """
    if not query:
        return list(enumerate(commands))
    scorer = regex_score if regex_mode else extended_score
    scored = []
    for idx, cmd in enumerate(commands):
        score = scorer(query, cmd)
        if score is not None:
            scored.append((score, idx, cmd))
    if best_match:
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


def _utf8_extra_bytes(lead_byte):
    """Number of continuation bytes following a UTF-8 lead byte, or 0 if
    `lead_byte` isn't a valid multi-byte lead byte (including plain
    ASCII, which needs none)."""
    if 0xC2 <= lead_byte <= 0xDF:
        return 1
    if 0xE0 <= lead_byte <= 0xEF:
        return 2
    if 0xF0 <= lead_byte <= 0xF4:
        return 3
    return 0


def _query_cursor_row(fd):
    """Ask the terminal where the cursor is now (DSR, "\x1b[6n") and
    return its 1-based absolute screen row, or None if the terminal
    doesn't answer within a short timeout (some terminals/multiplexers
    don't support it). Used to map mouse clicks to picker rows."""
    os.write(fd, b"\x1b[6n")
    buf = b""
    deadline = time.monotonic() + 0.2
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if not ready:
            continue
        buf += os.read(fd, 32)
        m = re.search(rb"\x1b\[(\d+);(\d+)R", buf)
        if m:
            return int(m.group(1))
    return None


def _parse_mouse_event(seq):
    """Parse an SGR mouse report ("\x1b[<Cb;Cx;CyM/m") into (button,
    column, row, pressed), or None if `seq` isn't one."""
    m = re.match(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])$", seq)
    if not m:
        return None
    button, col, row, final = m.groups()
    return int(button), int(col), int(row), final == b"M"


def _click_to_match_index(relative_row, layout, list_height, top):
    """Map a click's row (0-based, relative to the top of the picker's
    reserved screen strip) to a match index, or None if it fell outside
    the match list (e.g. on the prompt or footer line)."""
    body_row = relative_row - 1  # row 0 is the footer ("above") or prompt ("below")
    if not 0 <= body_row < list_height:
        return None
    if layout == "above":
        # The body is drawn reversed, topmost row = bottom-most match.
        return top + (list_height - 1 - body_row)
    return top + body_row


def _scrollbar_rows(list_height, total, top):
    """Return the set of body row indices (0-based) that should show
    the scrollbar thumb, mirroring fzf's thin right-edge scrollbar. The
    thumb's size and position are proportional to the visible window
    within the total match count; returns an empty set if every match
    already fits without scrolling."""
    if total <= list_height:
        return frozenset()
    thumb_size = max(1, min(list_height, round(list_height * list_height / total)))
    max_top = total - list_height
    track = list_height - thumb_size
    thumb_start = round(top * track / max_top) if max_top > 0 else 0
    return frozenset(range(thumb_start, thumb_start + thumb_size))


def _read_key(fd):
    """Read one logical keypress (handles arrow/page-key escape sequences
    and multi-byte UTF-8 characters).

    Arrow keys normally arrive as CSI sequences ("\x1b[A"), but terminals
    left in "application cursor keys" mode (DECCKM, e.g. after another
    program didn't clean up) send SS3 sequences ("\x1bOA") instead. Both
    forms are normalized to the CSI form so callers only match one shape.

    PageUp/PageDown, and SGR mouse reports, are longer CSI sequences with
    parameter bytes before the final byte (e.g. "\x1b[5~", "\x1b[<0;1;1M"),
    so the whole sequence is read up to its terminator instead of
    assuming a fixed length.
    """
    b = os.read(fd, 1)
    if b != b"\x1b":
        extra = _utf8_extra_bytes(b[0]) if b else 0
        for _ in range(extra):
            b += os.read(fd, 1)
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
        # (digits, ';', '<', etc.) fall below that and keep the sequence
        # going (this also covers the "<...M"/"<...m" tail of SGR mouse
        # reports, whose final byte is 'M' or 'm').
        if b3 and 0x40 <= b3[0] <= 0x7E:
            break
    return seq


def run_ui(tty_fd, commands, width, list_height, theme, initial_query="", keymap=None):
    """Draw and drive the inline picker; return the selected command or None."""
    keymap = keymap or DEFAULT_KEYMAP
    total_rows = list_height + 2  # prompt line + matches + footer line
    query = initial_query
    cursor = len(query)  # edit position within query, for Left/Right
    regex_mode = False
    best_match = False
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
    # Enable SGR mouse reporting (clicks to select, wheel to scroll) now
    # that the cursor is parked at the top of our reserved strip, then
    # ask the terminal where that row actually is on screen so clicks
    # can be mapped back to a match; None (no answer) just disables
    # click-to-select while leaving wheel scrolling, which needs no
    # absolute position, working.
    write("\x1b[?1000h\x1b[?1006h")
    base_row = _query_cursor_row(tty_fd)

    # A resize mid-session only reflows line width; reflowing the
    # reserved strip's height would require re-scrolling the terminal,
    # which risks losing track of `base_row` and nearby content.
    resized = {"flag": False}

    def _on_winch(signum, frame):
        resized["flag"] = True

    old_winch_handler = signal.signal(signal.SIGWINCH, _on_winch)

    def render():
        matches = filter_commands(commands, query, regex_mode, best_match)
        nonlocal selected, top, cursor_row
        if selected >= len(matches):
            selected = max(0, len(matches) - 1)
        if selected < top:
            top = selected
        if selected >= top + list_height:
            top = selected - list_height + 1

        mode = "REGEX" if regex_mode else "FUZZY"
        sort = "BEST" if best_match else "RECENT"
        mode_style = _sgr(theme["mode_style"])
        mode_label = f"[{mode} {sort}]"
        if mode_style:
            mode_label = f"{mode_style}{mode_label}{RESET}"
        plain_prefix = f"[{mode} {sort}] > "
        prompt_line = f"{mode_label} > {query}"

        thumb_rows = _scrollbar_rows(list_height, len(matches), top)
        body_lines = []
        for row in range(list_height):
            i = top + row
            scrollbar_char = "\u2503" if row in thumb_rows else " "
            if i >= len(matches):
                body_lines.append("" if not thumb_rows else (" " * (width - 2) + scrollbar_char)[: width - 1])
                continue
            _idx, cmd = matches[i]
            text = cmd.replace("\n", " ⏎ ")
            is_selected = i == selected
            indicator = theme["selected_indicator"] if is_selected else theme["unselected_indicator"]
            budget = width - 1 - (1 if thumb_rows else 0)
            line = (indicator + text)[:budget]
            if is_selected:
                sel_style = _sgr(theme["selected_style"])
                if sel_style:
                    line = f"{sel_style}{line}{RESET}"
            if thumb_rows:
                line = line.ljust(budget) + scrollbar_char
            body_lines.append(line)

        position = selected + 1 if matches else 0
        footer = f"{position}/{len(matches)}  Enter:select  Tab:cycle-mode  Ctrl-C/Esc:cancel"
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
        write("\x1b[?1000l\x1b[?1006l")
        signal.signal(signal.SIGWINCH, old_winch_handler)
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
            if resized["flag"]:
                resized["flag"] = False
                width = _term_size(tty_fd)[1]
            matches = render()
            key = _read_key(tty_fd)
            if key in keymap["select"]:
                clear_and_home()
                return matches[selected][1] if matches else None
            elif key in keymap["cancel"]:
                clear_and_home()
                return None
            elif key.startswith(b"\x1b[<"):
                event = _parse_mouse_event(key)
                if event is None:
                    continue
                button, _col, row, pressed = event
                if button in (64, 96):  # wheel up
                    move_selection(1)
                elif button in (65, 97):  # wheel down
                    move_selection(-1)
                elif button == 0 and pressed and base_row is not None:
                    index = _click_to_match_index(row - base_row, theme["layout"], list_height, top)
                    if index is not None and index < len(matches):
                        selected = index
            elif key in keymap["cycle_mode"]:
                # Cycle through the four mode/sort combinations:
                # FUZZY RECENT -> FUZZY BEST -> REGEX RECENT -> REGEX BEST -> ...
                if best_match:
                    regex_mode = not regex_mode
                best_match = not best_match
                selected = 0
                top = 0
            elif key in keymap["up"]:
                move_selection(1)
            elif key in keymap["down"]:
                move_selection(-1)
            elif key in keymap["page_up"]:
                move_selection(list_height)
            elif key in keymap["page_down"]:
                move_selection(-list_height)
            elif key in keymap["left"]:
                cursor = max(0, cursor - 1)
            elif key in keymap["right"]:
                cursor = min(len(query), cursor + 1)
            elif key in keymap["home"]:
                cursor = 0
            elif key in keymap["end"]:
                cursor = len(query)
            elif key in keymap["delete"]:
                if cursor < len(query):
                    query = query[:cursor] + query[cursor + 1 :]
                    selected = 0
                    top = 0
            elif key in keymap["kill_to_end"]:
                if cursor < len(query):
                    query = query[:cursor]
                    selected = 0
                    top = 0
            elif key in keymap["kill_to_start"]:
                if cursor > 0:
                    query = query[cursor:]
                    cursor = 0
                    selected = 0
                    top = 0
            elif key in keymap["backspace"]:
                if cursor > 0:
                    query = query[: cursor - 1] + query[cursor:]
                    cursor -= 1
                    selected = 0
                    top = 0
            else:
                char = None
                if len(key) == 1 and 0x20 <= key[0] < 0x7F:
                    char = key.decode()
                elif len(key) > 1 and key[0] >= 0xC2:  # multi-byte UTF-8
                    char = key.decode("utf-8", errors="replace")
                if char:
                    query = query[:cursor] + char + query[cursor:]
                    cursor += len(char)
                    selected = 0
                    top = 0
    except BaseException:
        clear_and_home()
        raise


def main():
    commands = read_history(default_histfile())
    if not commands:
        return 0

    config = read_config_file(os.environ.get("HIST_SEARCH_CONFIG", DEFAULT_CONFIG_PATH))
    theme = build_theme()
    keymap = build_keymap(config)
    initial_query = sys.argv[1] if len(sys.argv) > 1 else ""

    tty_fd = os.open("/dev/tty", os.O_RDWR)
    old_attrs = termios.tcgetattr(tty_fd)
    try:
        tty.setraw(tty_fd)
        rows, cols = _term_size(tty_fd)
        list_height = max(1, min(MAX_VISIBLE_ROWS, rows - 4))
        result = run_ui(tty_fd, commands, cols, list_height, theme, initial_query, keymap)
    finally:
        termios.tcsetattr(tty_fd, termios.TCSADRAIN, old_attrs)
        os.close(tty_fd)

    if result:
        sys.stdout.write(result)
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
