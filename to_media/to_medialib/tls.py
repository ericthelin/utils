"""A self-signed TLS certificate for the server, made with `openssl` when it
is installed. There is no certificate authority here: a worker or client
trusts the certificate because its fingerprint came from the join string, not
because anything signed it (see join.py)."""

import hashlib
import os
import shutil
import ssl
import subprocess

CERT_DAYS = 3650


def available():
    return bool(shutil.which("openssl"))


def ensure_cert(cert_path, key_path):
    """Create a self-signed certificate and key at these paths if they are not
    already there. Returns their SHA-256 fingerprint (hex, no colons)."""
    if not os.path.exists(cert_path):
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key_path,
             "-out", cert_path, "-days", str(CERT_DAYS), "-subj", "/CN=to_media"],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.chmod(key_path, 0o600)
    return fingerprint(cert_path)


def fingerprint(cert_path):
    with open(cert_path, "rb") as handle:
        der = ssl.PEM_cert_to_DER_cert(handle.read().decode("ascii"))
    return hashlib.sha256(der).hexdigest()


def server_context(cert_path, key_path):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    return context
