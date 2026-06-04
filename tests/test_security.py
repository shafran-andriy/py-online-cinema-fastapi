import re

from security.passwords import hash_password, verify_password
from security.utils import generate_secure_token


def test_hash_and_verify_password():
    raw = "StrongP@ssw0rd"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed)
    assert not verify_password("wrongpass", hashed)


def test_generate_secure_token():
    t1 = generate_secure_token(16)
    t2 = generate_secure_token(16)
    assert isinstance(t1, str)
    assert isinstance(t2, str)
    assert t1 != t2
    # token_urlsafe length is variable; ensure base64/urlsafe characters only
    assert re.match(r'^[A-Za-z0-9_\-]+$', t1)
