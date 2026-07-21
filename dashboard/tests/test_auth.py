from __future__ import annotations

from nexora.dashboard.auth import AuthService, BruteForceProtector, SessionManager, hash_password, verify_password


PASSWORD = "Correct-Dashboard-Password-2026!"


def test_password_hash_and_successful_login_logout() -> None:
    events = []
    encoded = hash_password(PASSWORD, salt=b"0123456789abcdef")
    assert PASSWORD not in encoded
    assert verify_password(PASSWORD, encoded)
    assert not verify_password("wrong-password-value", encoded)
    sessions = SessionManager(b"s" * 32, audit=lambda event, **fields: events.append(event))
    auth = AuthService(encoded, sessions, BruteForceProtector(), lambda event, **fields: events.append(event))
    result = auth.login("admin", PASSWORD, "local")
    assert result.ok and result.session is not None and result.cookie is not None
    assert sessions.validate(result.cookie) is not None
    assert auth.logout(result.cookie) is True
    assert sessions.validate(result.cookie) is None
    assert {"LOGIN_SUCCESS", "SESSION_CREATED", "LOGOUT"}.issubset(events)


def test_wrong_password_rate_limit_and_session_expiration() -> None:
    now = [1000.0]
    events = []
    clock = lambda: now[0]
    encoded = hash_password(PASSWORD, salt=b"fedcba9876543210")
    brute = BruteForceProtector(max_attempts=2, clock=clock)
    sessions = SessionManager(b"k" * 32, ttl_seconds=30, clock=clock, audit=lambda event, **fields: events.append(event))
    auth = AuthService(encoded, sessions, brute, lambda event, **fields: events.append(event))
    assert auth.login("admin", "wrong-password-value", "source").code == "AUTH_INVALID"
    assert auth.login("admin", "wrong-password-again", "source").code == "AUTH_INVALID"
    assert auth.login("admin", PASSWORD, "source").code == "AUTH_RATE_LIMITED"
    successful = auth.login("admin", PASSWORD, "other-source")
    assert successful.ok and successful.cookie
    now[0] += 31
    assert sessions.validate(successful.cookie) is None
    assert "SESSION_EXPIRED" in events
