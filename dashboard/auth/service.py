from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .passwords import verify_password


AuditCallback = Callable[..., None]


@dataclass(frozen=True)
class Session:
    session_id: str
    csrf_token: str
    role: str
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    code: str
    session: Session | None = None
    cookie: str | None = None


class BruteForceProtector:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: int = 900,
        lock_seconds: int = 900,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lock_seconds = lock_seconds
        self.clock = clock
        self._attempts: dict[str, list[float]] = {}
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def allowed(self, key: str) -> bool:
        now = self.clock()
        with self._lock:
            return self._locked_until.get(key, 0) <= now

    def failure(self, key: str) -> None:
        now = self.clock()
        cutoff = now - self.window_seconds
        with self._lock:
            attempts = [value for value in self._attempts.get(key, []) if value >= cutoff]
            attempts.append(now)
            self._attempts[key] = attempts
            if len(attempts) >= self.max_attempts:
                self._locked_until[key] = now + self.lock_seconds

    def success(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)
            self._locked_until.pop(key, None)


class SessionManager:
    def __init__(
        self,
        signing_key: bytes,
        *,
        ttl_seconds: int = 1800,
        max_sessions: int = 20,
        clock: Callable[[], float] = time.time,
        audit: AuditCallback | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("session signing key is too short")
        self.signing_key = signing_key
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.clock = clock
        self.audit = audit or (lambda *args, **kwargs: None)
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self) -> tuple[Session, str]:
        now = self.clock()
        session = Session(
            session_id=secrets.token_urlsafe(32),
            csrf_token=secrets.token_urlsafe(32),
            role="admin",
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        with self._lock:
            self._purge_locked(now)
            if len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(), key=lambda item: item.created_at)
                self._sessions.pop(oldest.session_id, None)
            self._sessions[session.session_id] = session
        self.audit("SESSION_CREATED", source="dashboard_auth", action_result="SUCCESS")
        return session, self._encode_cookie(session.session_id)

    def validate(self, cookie: str | None) -> Session | None:
        session_id = self._decode_cookie(cookie)
        if session_id is None:
            return None
        now = self.clock()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if session.expires_at <= now:
                self._sessions.pop(session_id, None)
                expired = True
            else:
                expired = False
        if expired:
            self.audit("SESSION_EXPIRED", source="dashboard_auth", action_result="EXPIRED")
            return None
        return session

    def revoke(self, cookie: str | None) -> bool:
        session_id = self._decode_cookie(cookie)
        if session_id is None:
            return False
        with self._lock:
            removed = self._sessions.pop(session_id, None) is not None
        return removed

    def _encode_cookie(self, session_id: str) -> str:
        signature = hmac.new(self.signing_key, session_id.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{session_id}.{signature}"

    def _decode_cookie(self, cookie: str | None) -> str | None:
        try:
            session_id, signature = str(cookie or "").split(".", 1)
            expected = hmac.new(self.signing_key, session_id.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                return None
            return session_id
        except (ValueError, UnicodeError):
            return None

    def _purge_locked(self, now: float) -> None:
        expired = [key for key, value in self._sessions.items() if value.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)


class AuthService:
    def __init__(
        self,
        password_hash: str,
        sessions: SessionManager,
        brute_force: BruteForceProtector,
        audit: AuditCallback,
    ) -> None:
        self.password_hash = password_hash
        self.sessions = sessions
        self.brute_force = brute_force
        self.audit = audit

    def login(self, username: str, password: str, source_key: str) -> AuthResult:
        if not self.brute_force.allowed(source_key):
            self.audit("LOGIN_FAILED", severity="SECURITY", source="dashboard_auth", action_result="RATE_LIMITED")
            return AuthResult(False, "AUTH_RATE_LIMITED")
        valid = username == "admin" and verify_password(password, self.password_hash)
        if not valid:
            self.brute_force.failure(source_key)
            self.audit("LOGIN_FAILED", severity="SECURITY", source="dashboard_auth", action_result="DENIED")
            return AuthResult(False, "AUTH_INVALID")
        self.brute_force.success(source_key)
        session, cookie = self.sessions.create()
        self.audit("LOGIN_SUCCESS", source="dashboard_auth", action_result="SUCCESS")
        return AuthResult(True, "OK", session, cookie)

    def logout(self, cookie: str | None) -> bool:
        removed = self.sessions.revoke(cookie)
        self.audit("LOGOUT", source="dashboard_auth", action_result="SUCCESS" if removed else "NO_SESSION")
        return removed
