from app.service import login


def test_login_ok():
    assert login("alice", "wonderland") == "ok"


def test_login_denied():
    assert login("alice", "nope") == "denied"
