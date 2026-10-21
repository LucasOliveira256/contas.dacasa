"""Autenticação obrigatória, CSRF e cabeçalhos básicos de segurança."""
import os
import secrets
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import select

from .database import SessionLocal
from .models import User

PUBLIC_PATHS = {"/login", "/healthz"}
PASSWORD_PATHS = {"/alterar-senha", "/logout"}


class AuthSecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path
        session = scope.setdefault("session", {})
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        user_state = None

        # Revalida a conta em cada requisição para respeitar usuários inativados.
        user_id = session.get("user_id")
        if user_id:
            db = SessionLocal()
            try:
                user = db.scalar(select(User).where(User.id == int(user_id), User.is_active.is_(True)))
                session_version = int(session.get("auth_version", -1))
                if user and session_version == user.session_version:
                    user_state = {
                        "id": user.id,
                        "username": user.username,
                        "is_admin": user.is_admin,
                        "must_change_password": user.must_change_password,
                    }
                else:
                    session.clear()
                    session["csrf_token"] = secrets.token_urlsafe(32)
            except (ValueError, TypeError):
                session.clear()
                session["csrf_token"] = secrets.token_urlsafe(32)
            finally:
                db.close()
        scope.setdefault("state", {})["current_user"] = user_state

        is_static = path == "/static" or path.startswith("/static/")
        is_public = path in PUBLIC_PATHS or is_static or path == "/favicon.ico"

        if not is_public and not user_state:
            query = scope.get("query_string", b"").decode("latin-1")
            destination = path + (f"?{query}" if query else "")
            response = RedirectResponse("/login?next=" + quote(destination, safe="/?=&"), status_code=303)
            await self._send_secure(response, scope, receive, send)
            return

        if user_state and user_state["must_change_password"] and path not in PASSWORD_PATHS and not is_static:
            response = RedirectResponse("/alterar-senha?obrigatoria=1", status_code=303)
            await self._send_secure(response, scope, receive, send)
            return

        if path.startswith("/usuarios") and user_state and not user_state["is_admin"]:
            response = RedirectResponse("/?erro=Acesso+restrito+ao+Admin", status_code=303)
            await self._send_secure(response, scope, receive, send)
            return

        # Todas as operações POST usam formulários HTML com token anti-CSRF.
        downstream_receive = receive
        if request.method.upper() == "POST":
            try:
                body = await request.body()
                form = await request.form()
            except Exception:
                response = PlainTextResponse("Formulário inválido.", status_code=400)
                await self._send_secure(response, scope, receive, send)
                return
            supplied = str(form.get("_csrf", ""))
            expected = str(session.get("csrf_token", ""))
            if not supplied or not expected or not secrets.compare_digest(supplied, expected):
                response = PlainTextResponse("Token de segurança inválido. Recarregue a página e tente novamente.", status_code=403)
                await self._send_secure(response, scope, receive, send)
                return
            sent = False

            async def replay_receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}

            downstream_receive = replay_receive

        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                secure_headers = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"permissions-policy": b"camera=(), microphone=(), geolocation=()",
                    b"content-security-policy": b"default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
                    b"cache-control": b"no-store",
                }
                current = {key.lower() for key, _ in headers}
                for key, value in secure_headers.items():
                    if key not in current:
                        headers.append((key, value))
                if os.getenv("COOKIE_SECURE", "true").lower() in ("1", "true", "yes", "on") and b"strict-transport-security" not in current:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, downstream_receive, secure_send)

    async def _send_secure(self, response, scope, receive, send):
        async def secure_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                security_headers = {
                    b"x-content-type-options": b"nosniff",
                    b"x-frame-options": b"DENY",
                    b"referrer-policy": b"strict-origin-when-cross-origin",
                    b"content-security-policy": b"default-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
                    b"cache-control": b"no-store",
                }
                existing = {key.lower() for key, _ in headers}
                for key, value in security_headers.items():
                    if key not in existing:
                        headers.append((key, value))
                message["headers"] = headers
            await send(message)
        await response(scope, receive, secure_send)
