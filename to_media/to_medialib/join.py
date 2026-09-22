"""The join string a worker or client uses to find a server:

    tomedia://TOKEN@host[,host2]:port?id=SERVERID

`id` is a short random id for the server instance itself (not the token), so a
worker can tell "the server is down" from "a different server now answers at
this address" after, say, a router hands the address to another machine.
"""

import dataclasses
from urllib.parse import parse_qs, urlsplit

SCHEME = "tomedia"


class InvalidJoinString(ValueError):
    pass


@dataclasses.dataclass
class Join:
    token: str
    hosts: list
    port: int
    server_id: str = ""

    def __str__(self):
        query = f"?id={self.server_id}" if self.server_id else ""
        return f"{SCHEME}://{self.token}@{','.join(self.hosts)}:{self.port}{query}"

    def url(self, host=None):
        return f"http://{host or self.hosts[0]}:{self.port}"


def parse(text):
    text = text.strip()
    parts = urlsplit(text)
    if parts.scheme != SCHEME or not parts.hostname or not parts.port:
        raise InvalidJoinString(f"not a valid {SCHEME}:// join string")
    if not parts.username:
        raise InvalidJoinString("join string has no token")
    hosts = parts.netloc.split("@", 1)[1].rsplit(":", 1)[0].split(",")
    server_id = parse_qs(parts.query).get("id", [""])[0]
    return Join(token=parts.username, hosts=hosts, port=parts.port, server_id=server_id)
