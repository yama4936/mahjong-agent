"""Process-lifetime ownership of a CDP browser, shared across checkouts."""
import errno
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit


class OperatorAlreadyRunning(RuntimeError):
    pass


def endpoint_key(cdp):
    parsed = urlsplit(cdp)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        host = "loopback"
    return host, parsed.port or (443 if parsed.scheme in {"https", "wss"} else 80)


def lock_path(cdp):
    # No repository path: frozen copies must compete for the same browser.
    user = str(os.getuid()) if hasattr(os, "getuid") else os.environ.get("USERNAME", "")
    digest = hashlib.sha256(json.dumps([user, endpoint_key(cdp)]).encode()).hexdigest()[:24]
    # TMPDIR can differ across independently launched operators. Resolve the
    # Unix account home from the UID instead of environment variables, so all
    # new processes for this user and endpoint contend on the same inode.
    if os.name == "nt":
        directory = Path.home() / ".cache" / "jantama-auto" / "locks"
    else:
        import pwd
        directory = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "jantama-auto" / "locks"
    return directory / f"cdp-{digest}.lock"


@contextmanager
def operator_lease(cdp):
    path = lock_path(cdp)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "r+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise
            raise OperatorAlreadyRunning(f"Another operator owns CDP browser lock {path}") from error
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "endpoint": endpoint_key(cdp)}).encode())
        handle.flush()
        try:
            yield path
        finally:
            # Never unlink the file: another process could still be waiting
            # on its inode. Closing releases ownership even after a crash.
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

