"""Server-verified Google identity; opaque hashed sessions and synchronizer CSRF."""

import hashlib
import secrets
import time
from contextvars import ContextVar
from uuid import uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field

from . import database as db
from .errors import AppError

actor_id = ContextVar("authenticated_actor_id", default=None)


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def csrf_for(token):
    return hashed("youtube-session-csrf-v1:" + token)


class GoogleLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: str = Field(min_length=1, max_length=8192)
    csrf_token: str = Field(min_length=32, max_length=128)


def verify_google(credential, audience):
    from google.auth.transport.requests import Request
    from google.oauth2.id_token import verify_oauth2_token

    class BoundedRequest(Request):
        def __call__(self, *args, **kwargs):
            kwargs["timeout"] = 5
            return super().__call__(*args, **kwargs)

    transport = BoundedRequest()
    try:
        return verify_oauth2_token(credential, transport, audience=audience)
    finally:
        transport.session.close()


def public_user(user):
    return {key: user[key] for key in ("user_id", "email", "name", "picture", "role", "status")}


class AuthService:
    def __init__(self, database, settings):
        self.db, self.settings = database, settings
        self.verifier = verify_google
        self.cookie = "__Host-yk_session" if settings.session_cookie_secure else "yk_session"
        self.login_cookie = "__Host-yk_login" if settings.session_cookie_secure else "yk_login"

    def origin(self, request):
        if request.headers.get("origin") not in (
            self.settings.auth_trusted_origins or [self.settings.web_origin]
        ):
            raise AppError("csrf_invalid", "Untrusted request origin", 403)

    def cookie_options(self):
        return dict(
            httponly=True, secure=self.settings.session_cookie_secure, samesite="lax", path="/"
        )

    def challenge(self, request, response):
        if not self.settings.google_client_id:
            raise AppError("auth_not_configured", "Configure GOOGLE_CLIENT_ID on the server", 503)
        token, csrf, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        now = time.time()
        ip = hashed(request.client.host if request.client else "unknown")
        with self.db.write() as c:
            c.execute(db.login_challenges.delete().where(db.login_challenges.c.expires_at < now))
            count = c.scalar(
                sa.select(sa.func.count())
                .select_from(db.login_challenges)
                .where(db.login_challenges.c.ip_hash == ip)
            )
            if count >= 30:
                raise AppError("login_rate_limit", "Try login again later", 429)
            c.execute(
                db.login_challenges.insert().values(
                    token_hash=hashed(token),
                    csrf_hash=hashed(csrf),
                    nonce_hash=hashed(nonce),
                    ip_hash=ip,
                    created_at=now,
                    expires_at=now + 300,
                    consumed=False,
                )
            )
        response.set_cookie(self.login_cookie, token, max_age=300, **self.cookie_options())
        response.headers["Cache-Control"] = "no-store"
        return dict(nonce=nonce, csrf_token=csrf, client_id=self.settings.google_client_id)

    def login(self, request, response, body):
        self.origin(request)
        challenge_token = request.cookies.get(self.login_cookie, "")
        now = time.time()
        with self.db.write() as c:
            challenge = (
                c.execute(
                    sa.select(db.login_challenges).where(
                        db.login_challenges.c.token_hash == hashed(challenge_token)
                    )
                )
                .mappings()
                .first()
            )
            if (
                not challenge
                or challenge["consumed"]
                or challenge["expires_at"] <= now
                or not secrets.compare_digest(challenge["csrf_hash"], hashed(body.csrf_token))
            ):
                raise AppError("csrf_invalid", "Login challenge is missing or invalid", 403)
            c.execute(
                db.login_challenges.update()
                .where(db.login_challenges.c.token_hash == hashed(challenge_token))
                .values(consumed=True)
            )
        try:
            if not self.settings.google_client_id:
                raise ValueError
            claims = self.verifier(body.credential, self.settings.google_client_id)
            if (
                claims.get("aud") != self.settings.google_client_id
                or claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}
                or float(claims.get("exp", 0)) <= now
                or float(claims.get("iat", now)) > now + 60
                or not isinstance(claims.get("sub"), str)
                or not 1 <= len(claims["sub"]) <= 255
                or not secrets.compare_digest(
                    hashed(claims.get("nonce", "")), challenge["nonce_hash"]
                )
            ):
                raise ValueError
        except Exception:
            raise AppError(
                "invalid_google_token", "Google credential could not be verified", 401
            ) from None
        session_token = secrets.token_urlsafe(32)
        csrf = csrf_for(session_token)
        with self.db.write() as c:
            user = (
                c.execute(sa.select(db.users).where(db.users.c.google_sub == claims["sub"]))
                .mappings()
                .first()
            )
            if user and user["status"] != "active":
                raise AppError("account_suspended", "Account is suspended", 403)
            profile = dict(
                email=str(claims.get("email", ""))[:320] or None,
                name=str(claims.get("name", ""))[:200] or None,
                picture=str(claims.get("picture", ""))[:2048] or None,
                updated_at=now,
            )
            user_id = user["user_id"] if user else str(uuid4())
            if user:
                c.execute(db.users.update().where(db.users.c.user_id == user_id).values(**profile))
            else:
                c.execute(
                    db.users.insert().values(
                        user_id=user_id,
                        google_sub=claims["sub"],
                        role="user",
                        status="active",
                        created_at=now,
                        **profile,
                    )
                )
            old = request.cookies.get(self.cookie)
            if old:
                c.execute(
                    db.sessions.update()
                    .where(db.sessions.c.token_hash == hashed(old))
                    .values(revoked=True)
                )
            c.execute(db.sessions.delete().where(db.sessions.c.expires_at < now))
            c.execute(
                db.sessions.insert().values(
                    token_hash=hashed(session_token),
                    user_id=user_id,
                    csrf_hash=hashed(csrf),
                    expires_at=now + self.settings.session_ttl_seconds,
                    revoked=False,
                    created_at=now,
                )
            )
            user = (
                c.execute(sa.select(db.users).where(db.users.c.user_id == user_id)).mappings().one()
            )
        response.set_cookie(
            self.cookie,
            session_token,
            max_age=self.settings.session_ttl_seconds,
            **self.cookie_options(),
        )
        response.delete_cookie(self.login_cookie, **self.cookie_options())
        response.headers["Cache-Control"] = "no-store"
        return dict(user=public_user(user), csrf_token=csrf)

    def current(self, request, *, mutate=False):
        token = request.cookies.get(self.cookie, "")
        with self.db.read() as c:
            session = (
                c.execute(
                    sa.select(db.sessions).where(
                        db.sessions.c.token_hash == hashed(token),
                        db.sessions.c.revoked.is_(False),
                        db.sessions.c.expires_at > time.time(),
                    )
                )
                .mappings()
                .first()
            )
            user = (
                None
                if not session
                else c.execute(
                    sa.select(db.users).where(
                        db.users.c.user_id == session["user_id"], db.users.c.status == "active"
                    )
                )
                .mappings()
                .first()
            )
        if not user:
            raise AppError("authentication_required", "Sign in with Google first", 401)
        if mutate:
            self.origin(request)
            header = request.headers.get("x-csrf-token", "")
            if not secrets.compare_digest(hashed(header), session["csrf_hash"]):
                raise AppError("csrf_invalid", "CSRF header is missing or invalid", 403)
        return user, csrf_for(token)

    def logout(self, request, response):
        self.current(request, mutate=True)
        with self.db.write() as c:
            c.execute(
                db.sessions.update()
                .where(db.sessions.c.token_hash == hashed(request.cookies.get(self.cookie, "")))
                .values(revoked=True)
            )
        response.delete_cookie(self.cookie, **self.cookie_options())
        return dict(logged_out=True)
