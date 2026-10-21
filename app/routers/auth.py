"""Login, troca de senha e administração de usuários."""
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.templating import Jinja2Templates

from ..database import get_db
from ..models import User
from ..security import hash_password, verify_password

router = APIRouter(tags=["autenticação"])
templates = Jinja2Templates(directory="app/templates")
LOGIN_ATTEMPTS: dict[str, deque[float]] = defaultdict(deque)
RATE_WINDOW_SECONDS = 15 * 60
MAX_ATTEMPTS = 5
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _limited(ip: str) -> bool:
    now = time.monotonic()
    attempts = LOGIN_ATTEMPTS[ip]
    while attempts and now - attempts[0] > RATE_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= MAX_ATTEMPTS


def _bad_attempt(ip: str) -> None:
    now = time.monotonic()
    attempts = LOGIN_ATTEMPTS[ip]
    while attempts and now - attempts[0] > RATE_WINDOW_SECONDS:
        attempts.popleft()
    attempts.append(now)


def _redirect_error(path: str, message: str):
    return RedirectResponse(f"{path}?{urlencode({'erro': message})}", status_code=303)


@router.get("/login")
def login_page(request: Request):
    current = getattr(request.state, "current_user", None)
    if current:
        if current["must_change_password"]:
            return RedirectResponse("/alterar-senha", status_code=303)
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "csrf_token": request.session.get("csrf_token", ""),
        "erro": request.query_params.get("erro"),
        "next_url": request.query_params.get("next", "/"),
    })


@router.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/"),
    db: Session = Depends(get_db),
):
    ip = _ip(request)
    if _limited(ip):
        return _redirect_error("/login", "Muitas tentativas. Aguarde 15 minutos antes de tentar novamente.")
    # Registra a tentativa antes do hash, limitando hashes Argon2 concorrentes.
    _bad_attempt(ip)
    user_key = username.strip().casefold()
    user = db.scalar(select(User).where(User.username_key == user_key, User.is_active.is_(True)))
    if not user or not verify_password(user.password_hash, password):
        return _redirect_error("/login", "Usuário ou senha inválidos.")

    LOGIN_ATTEMPTS.pop(ip, None)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_version"] = user.session_version
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    if user.must_change_password:
        return RedirectResponse("/alterar-senha?obrigatoria=1", status_code=303)
    # Aceita somente caminhos relativos locais; evita redirecionamento aberto.
    safe_next = next_url if next_url.startswith("/") and not next_url.startswith("//") else "/"
    return RedirectResponse(safe_next, status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login?ok=logout", status_code=303)


@router.get("/alterar-senha")
def change_password_page(request: Request):
    current = request.state.current_user
    return templates.TemplateResponse(request=request, name="change_password.html", context={
        "csrf_token": request.session.get("csrf_token", ""),
        "username": current["username"],
        "mandatory": current["must_change_password"],
        "erro": request.query_params.get("erro"),
        "ok": request.query_params.get("ok"),
    })


@router.post("/alterar-senha")
def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    current = request.state.current_user
    user = db.get(User, current["id"])
    if not user or not verify_password(user.password_hash, current_password):
        return _redirect_error("/alterar-senha", "A senha atual está incorreta.")
    if new_password != confirm_password:
        return _redirect_error("/alterar-senha", "A confirmação não corresponde à nova senha.")
    if len(new_password) < 12:
        return _redirect_error("/alterar-senha", "A nova senha deve ter pelo menos 12 caracteres.")
    if new_password == current_password:
        return _redirect_error("/alterar-senha", "Escolha uma senha diferente da atual.")
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.session_version += 1
    db.commit()
    request.session["auth_version"] = user.session_version
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/?ok=1", status_code=303)


@router.get("/usuarios")
def users_page(request: Request, db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).order_by(User.is_admin.desc(), User.username_key)).all())
    return templates.TemplateResponse(request=request, name="users.html", context={
        "csrf_token": request.session.get("csrf_token", ""),
        "current_user": request.state.current_user,
        "users": users,
        "erro": request.query_params.get("erro"),
        "ok": request.query_params.get("ok"),
    })


@router.post("/usuarios")
def create_user(
    username: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    clean_username = username.strip()
    if not USERNAME_PATTERN.fullmatch(clean_username):
        return _redirect_error("/usuarios", "O usuário deve ter 3 a 32 caracteres: letras, números, ponto, hífen ou sublinhado.")
    if len(password) < 12:
        return _redirect_error("/usuarios", "A senha inicial deve ter pelo menos 12 caracteres.")
    if password != confirm_password:
        return _redirect_error("/usuarios", "A confirmação da senha não corresponde.")
    key = clean_username.casefold()
    if db.scalar(select(User.id).where(User.username_key == key)):
        return _redirect_error("/usuarios", "Já existe um usuário com esse nome.")
    db.add(User(username=clean_username, username_key=key, password_hash=hash_password(password),
                is_admin=False, is_active=True, must_change_password=True))
    db.commit()
    return RedirectResponse("/usuarios?ok=1", status_code=303)
