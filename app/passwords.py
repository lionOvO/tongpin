"""Salted, memory-hard password hashes; never store or truncate a password."""
import hashlib
import hmac
import secrets
import threading

from .errors import DomainError

# OWASP scrypt profile: 32 MiB, r=8, p=3. Bound simultaneous allocations.
_slots = threading.BoundedSemaphore(2)
_N, _R, _P = 32768, 8, 3


def _derive(password, salt):
    if not _slots.acquire(timeout=2):
        raise DomainError("AUTH_BUSY", "登录请求较多，请稍后重试。", 429)
    try:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P,
                              maxmem=64 * 1024 * 1024, dklen=32)
    finally:
        _slots.release()


def hash_password(password):
    salt = secrets.token_bytes(16)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${_derive(password, salt).hex()}"


_dummy = hash_password(secrets.token_urlsafe(32))


def verify_password(password, encoded):
    # Unknown accounts and legacy accounts still incur the same hash work.
    try:
        algorithm, n, r, p, salt, expected = (encoded or _dummy).split("$")
        if (algorithm, int(n), int(r), int(p)) != ("scrypt", _N, _R, _P):
            raise ValueError("Unsupported hash")
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            raise ValueError("Invalid hash")
    except (ValueError, TypeError):
        verify_password(password, None)
        return False
    actual = _derive(password, salt)
    return bool(encoded) and hmac.compare_digest(actual, expected)
