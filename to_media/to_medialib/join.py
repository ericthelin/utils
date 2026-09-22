"""The join string a worker or client uses to find a server:

    tomedia://TOKEN@host[,host2]:port?id=SERVERID&fp=CERT_SHA256

`id` is a short random id for the server instance itself (not the token), so a
worker can tell "the server is down" from "a different server now answers at
this address" after, say, a router hands the address to another machine.

`fp` is the SHA-256 fingerprint (hex, no colons) of the server's TLS
certificate, present only when the server has one (openssl was available when
it was set up). Its presence is what makes a join string ask for `https://`:
the certificate is self-signed, so this fingerprint - not a certificate
authority - is what a worker or client trusts.
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
    fingerprint: str = ""

    def __str__(self):
        params = [f"id={self.server_id}"] if self.server_id else []
        if self.fingerprint:
            params.append(f"fp={self.fingerprint}")
        query = "?" + "&".join(params) if params else ""
        return f"{SCHEME}://{self.token}@{','.join(self.hosts)}:{self.port}{query}"

    def url(self, host=None):
        scheme = "https" if self.fingerprint else "http"
        return f"{scheme}://{host or self.hosts[0]}:{self.port}"


def parse(text):
    text = text.strip()
    parts = urlsplit(text)
    if parts.scheme != SCHEME or not parts.hostname or not parts.port:
        raise InvalidJoinString(f"not a valid {SCHEME}:// join string")
    if not parts.username:
        raise InvalidJoinString("join string has no token")
    hosts = parts.netloc.split("@", 1)[1].rsplit(":", 1)[0].split(",")
    query = parse_qs(parts.query)
    return Join(token=parts.username, hosts=hosts, port=parts.port,
               server_id=query.get("id", [""])[0], fingerprint=query.get("fp", [""])[0])
