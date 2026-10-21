"""Funções de segurança: hash de senha e segredo persistente de sessão."""
import os
import secrets
from pathlib import Path
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, TypeError):
        return False


def _default_secret_path() -> Path:
    configured = os.getenv("SESSION_SECRET_FILE")
    if configured:
        return Path(configured)
    database_url = os.getenv("DATABASE_URL", "sqlite:///./financas.db")
    if database_url.startswith("sqlite:////"):
        db_path = Path(database_url.replace("sqlite:////", "/", 1))
        return db_path.parent / "session_secret.key"
    return Path(".session_secret.key")


def session_secret() -> str:
    """Cria um segredo criptograficamente aleatório e persiste no volume."""
    env_secret = os.getenv("SESSION_SECRET")
    if env_secret:
        if len(env_secret) < 32:
            raise RuntimeError("SESSION_SECRET precisa ter pelo menos 32 caracteres.")
        return env_secret
    path = _default_secret_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(48))
        path.chmod(0o600)
    except FileExistsError:
        pass
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 32:
        raise RuntimeError(f"Segredo de sessão inválido em {path}; apague-o com a aplicação parada para gerar outro.")
    return value
