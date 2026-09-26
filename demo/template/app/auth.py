"""Password checks for the login service."""
import hashlib
import hmac

USERS = {"alice": hashlib.sha256(b"wonderland").hexdigest()}


def check_password(user: str, password: str) -> bool:
    expected = USERS.get(user)
    if expected is None:
        return False
    given = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(expected, given)
