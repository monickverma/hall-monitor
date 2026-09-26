"""Login endpoint logic."""
from app.auth import check_password


def login(user: str, password: str) -> str:
    if not check_password(user, password):
        return "denied"
    return "ok"
