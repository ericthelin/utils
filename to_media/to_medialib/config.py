"""Where to_media keeps its configuration. The tool name lives only here."""

import configparser
import os
import sys

TOOL_NAME = "to_media"


def config_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, TOOL_NAME)


def config_path():
    return os.path.join(config_dir(), "config")


def load_config(path=None):
    parser = configparser.ConfigParser()
    parser.read(path or config_path())
    return parser


def save_config(parser, path=None):
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
        parser.write(handle)
