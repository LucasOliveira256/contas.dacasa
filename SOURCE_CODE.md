# Casa em Ordem — Código-fonte completo
Este documento contém os arquivos do projeto integralmente, sem omitir trechos. O projeto executável também está disponível no ZIP.

## `.dockerignore`

```text
__pycache__/
*.py[cod]
*.db
*.sqlite3
.venv/
.git/
tests/

.env
.session_secret.key
```

## `.env.example`

```text
# Use true em produção, com o sistema acessado por HTTPS.
COOKIE_SECURE=true

# Se o proxy reverso estiver em outro IP, indique o IP exato dele.
# Exemplo: FORWARDED_ALLOW_IPS=10.0.0.20
FORWARDED_ALLOW_IPS=127.0.0.1
```

## `.gitignore`

```text
__pycache__/
*.py[cod]
*.db
*.db-wal
*.db-shm
*.sqlite3
.venv/
.env
.session_secret.key
.pytest_cache/
```

## `Dockerfile`

```dockerfile
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Cuiaba DATABASE_URL=sqlite:////data/financas.db
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY start.sh /usr/local/bin/start.sh
RUN chmod 755 /usr/local/bin/start.sh && mkdir -p /data && chown app:app /data
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/start.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
```

## `README.md`

```markdown
# Casa em Ordem — Finanças da Família

Aplicação web para controlar receitas, despesas, cartões, orçamento e poupanças familiares. Executa em um container Docker, com SQLite persistente e interface responsiva em português. Interface inspirada em dashboards administrativos modernos, com tema Dark e alternativa Material Light.

## Funcionalidades

- Dashboard mensal com gráfico de linhas de entradas x saídas, histórico e projeção de 12 meses.
- Menu lateral expansível por hover no desktop e recolhível no celular; tema Dark e Material Light.
- Cartões visuais com cores por emissor e exibição opcional dos quatro últimos dígitos (o número completo não é armazenado).
- Receitas, despesas fixas/variáveis/planejadas e parcelamento no crédito.
- Cartões de crédito, débito e Vale Alimentação.
- Pessoas, categorias, contas, orçamentos e relatórios.
- Poupança por pessoa, com depósitos, retiradas e juros.
- Gráficos offline, exportação CSV e backup do banco.
- Login, gestão de usuários, troca obrigatória de senhas iniciais e proteção CSRF.

## Executar

Requer Docker Engine e Docker Compose.

```bash
git clone <URL-DO-REPOSITORIO>
cd familia-financas
cp .env.example .env
# Mantenha COOKIE_SECURE=true em produção e configure FORWARDED_ALLOW_IPS para o IP confiável do proxy.
docker compose up -d --build
```

A aplicação escuta a porta `8080`. Para acesso público, configure um proxy reverso com HTTPS e acesse pelo domínio HTTPS. **Não encaminhe a porta 8080 diretamente à internet.**

Se ainda não houver proxy HTTPS e for necessário configurar a senha inicial em rede local usando HTTP simples, defina temporariamente `COOKIE_SECURE=false` em `.env`, inicie a aplicação e acesse `http://localhost:8080`. Troque a senha antes de liberar o acesso público; configure HTTPS no proxy, volte `COOKIE_SECURE=true` e reinicie:

```bash
docker compose up -d --build
docker compose logs -f familia-financas
```

## Primeiro acesso e usuários

- Usuário inicial: `Admin`
- Senha provisória: `admin`
- O primeiro login exige uma nova senha com pelo menos 12 caracteres. Faça essa troca antes de liberar o acesso público.
- O Admin pode criar usuários na página **Usuários**. Cada novo usuário precisa trocar sua senha inicial no primeiro login.
- Todos os usuários podem alterar a própria senha.

## Segurança e persistência

- Senhas protegidas por hash Argon2; sessões assinadas com validade de 8 horas; formulários protegidos contra CSRF; limite de tentativas de login.
- O processo web roda sem privilégios de root. Banco SQLite e segredo de sessão ficam no volume Docker `familia_financas_data`, com permissões restritas. O segredo é gerado automaticamente e persiste entre reinicializações; trocar a senha invalida sessões anteriores.
- Se o proxy reverso estiver em outro IP, defina `FORWARDED_ALLOW_IPS` em `.env` com o IP exato e confiável do proxy — nunca use `*`.
- No MikroTik, encaminhe as portas públicas HTTPS somente para o proxy reverso; não crie DST-NAT público para a porta `8080`.
- `docker compose down` preserva os dados. **Não use `docker compose down -v`**, pois isso remove o volume.
- O SQLite não é criptografado em repouso: restrinja o acesso ao host e proteja backups. Para risco de acesso físico ao disco, use criptografia de disco/volume no sistema operacional. Mantenha backups em local seguro.

## Comandos úteis

```bash
docker compose logs -f familia-financas
docker compose down
docker compose up -d
```

## Licença

Defina a licença desejada antes de publicar o repositório (por exemplo, MIT).
```

## `app/__init__.py`

```python
"""Gestão financeira familiar."""
```

## `app/auth_middleware.py`

```python
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
```

## `app/database.py`

```python
import os
from pathlib import Path
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./financas.db")
if DATABASE_URL.startswith("sqlite:////"):
    Path(DATABASE_URL.replace("sqlite:////", "/", 1)).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    future=True,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def migrate_database() -> None:
    """Migra de forma aditiva bancos locais criados por versões anteriores."""
    if not DATABASE_URL.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "credit_cards" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("credit_cards")}
        with engine.begin() as connection:
            if "kind" not in columns:
                connection.execute(text("ALTER TABLE credit_cards ADD COLUMN kind VARCHAR(30) NOT NULL DEFAULT 'credito'"))
            if "last_four_digits" not in columns:
                connection.execute(text("ALTER TABLE credit_cards ADD COLUMN last_four_digits VARCHAR(4) NOT NULL DEFAULT ''"))
    # Permite invalidar sessões antigas ao trocar a senha.
    if "users" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "session_version" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"))
    # create_all adiciona tabelas novas sem alterar os dados financeiros antigos.
    Base.metadata.create_all(bind=engine)
```

## `app/main.py`

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
import os
from .database import Base, engine, SessionLocal, migrate_database
from . import models  # registra os mapeamentos antes do create_all
from .seed import seed_database
from .services.recurring import ensure_fixed_transactions
from .routers import dashboard, transactions, registrations, incomes, cards, budgets, reports, savings, auth
from .auth_middleware import AuthSecurityMiddleware
from .security import session_secret

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_database()
    db = SessionLocal()
    try:
        seed_database(db)
        ensure_fixed_transactions(db)
    finally:
        db.close()
    yield

app = FastAPI(title="Casa em Ordem", description="Gestão financeira familiar", version="1.2.0", lifespan=lifespan)
# SessionMiddleware fica por fora do middleware de autenticação para validar cookies assinados.
app.add_middleware(AuthSecurityMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret(),
    session_cookie="casa_em_ordem_session",
    max_age=8 * 60 * 60,
    same_site="lax",
    https_only=os.getenv("COOKIE_SECURE", "true").strip().lower() in ("1", "true", "yes", "on"),
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(registrations.router)
app.include_router(incomes.router)
app.include_router(cards.router)
app.include_router(budgets.router)
app.include_router(reports.router)
app.include_router(savings.router)
app.include_router(auth.router)

@app.get("/healthz", include_in_schema=False)
def healthz():
    return JSONResponse({"status": "ok"})
```

## `app/models.py`

```python
from datetime import date, datetime
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False)
    username_key: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    session_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("name", "parent_id", name="uq_category_sibling"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="RESTRICT"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    parent: Mapped["Category | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Category"]] = relationship(back_populates="parent", cascade="save-update, merge")

class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="corrente", nullable=False)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    initial_balance_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    person: Mapped[Person | None] = relationship()

class CreditCard(Base):
    __tablename__ = "credit_cards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), default="credito", nullable=False)  # credito, debito ou vale_alimentacao
    # Cartões de débito usam 0 nos dias de ciclo; a interface não exibe fechamento/vencimento.
    closing_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limit_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_four_digits: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    payment_account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    owner: Mapped[Person] = relationship()
    payment_account: Mapped[Account | None] = relationship()

class Income(Base):
    __tablename__ = "incomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # salary, extra, payroll_* 
    happened_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    included_in_cashflow: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    person: Mapped[Person] = relationship()
    __table_args__ = (CheckConstraint("amount_cents >= 0", name="ck_income_nonnegative"),)

class FixedExpense(Base):
    __tablename__ = "fixed_expenses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("credit_cards.id"))
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    category: Mapped[Category] = relationship()
    person: Mapped[Person] = relationship()
    account: Mapped[Account | None] = relationship()
    card: Mapped[CreditCard | None] = relationship()

class FinancialTransaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint("amount_cents >= 0", name="ck_transaction_nonnegative"),
        UniqueConstraint("fixed_expense_id", "occurrence_month", name="uq_fixed_occurrence"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(String(240), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    cashflow_date: Mapped[date] = mapped_column(Date, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"))
    card_id: Mapped[int | None] = mapped_column(ForeignKey("credit_cards.id"))
    status: Mapped[str] = mapped_column(String(20), default="realizado", nullable=False)  # previsto, realizado, cancelado
    fixed_expense_id: Mapped[int | None] = mapped_column(ForeignKey("fixed_expenses.id", ondelete="SET NULL"))
    occurrence_month: Mapped[date | None] = mapped_column(Date)
    fixed_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    installment_group: Mapped[str | None] = mapped_column(String(40))
    installment_number: Mapped[int | None] = mapped_column(Integer)
    installment_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    category: Mapped[Category] = relationship()
    person: Mapped[Person] = relationship()
    account: Mapped[Account | None] = relationship()
    card: Mapped[CreditCard | None] = relationship()
    fixed_expense: Mapped[FixedExpense | None] = relationship()

class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("year", "month", "category_id", name="uq_budget_period_category"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    category: Mapped[Category] = relationship()


class SavingsAccount(Base):
    __tablename__ = "savings_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    initial_balance_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    person: Mapped[Person] = relationship()
    category: Mapped[Category] = relationship()
    movements: Mapped[list["SavingsMovement"]] = relationship(back_populates="account", cascade="all, delete-orphan")
    __table_args__ = (CheckConstraint("initial_balance_cents >= 0", name="ck_savings_initial_nonnegative"),)


class SavingsMovement(Base):
    __tablename__ = "savings_movements"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("savings_accounts.id", ondelete="CASCADE"), nullable=False)
    happened_on: Mapped[date] = mapped_column(Date, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # deposito, retirada, juros
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    account: Mapped[SavingsAccount] = relationship(back_populates="movements")
    __table_args__ = (
        CheckConstraint("amount_cents > 0", name="ck_savings_movement_positive"),
        CheckConstraint("kind IN ('deposito', 'retirada', 'juros')", name="ck_savings_movement_kind"),
    )
```

## `app/routers/__init__.py`

```python
"""Rotas HTTP da aplicação."""
```

## `app/routers/auth.py`

```python
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
```

## `app/routers/budgets.py`

```python
from datetime import date
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Budget, Category, FinancialTransaction
from ..services.finance import parse_brl_to_cents, parse_month, month_start, month_end, category_name
from .common import page

router = APIRouter(tags=["orçamento"])

@router.get("/orcamento")
def budgets_page(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    budgets = list(db.scalars(select(Budget).where(Budget.year == year, Budget.month == month).order_by(Budget.category_id)).all())
    spent_by_category = {}
    transactions = db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= month_start(year, month),
        FinancialTransaction.purchase_date <= month_end(year, month),
        FinancialTransaction.status == "realizado")).all()
    for transaction in transactions:
        spent_by_category[transaction.category_id] = spent_by_category.get(transaction.category_id, 0) + transaction.amount_cents
    def category_spent(category_id: int) -> int:
        category = db.get(Category, category_id)
        child_ids = list(db.scalars(select(Category.id).where(Category.parent_id == category_id)).all()) if category and category.parent_id is None else []
        return spent_by_category.get(category_id, 0) + sum(spent_by_category.get(child_id, 0) for child_id in child_ids)
    rows = [{"budget": b, "label": category_name(db, b.category_id), "spent": category_spent(b.category_id),
             "percent": category_spent(b.category_id) * 100 // b.amount_cents if b.amount_cents else 0,
             "over": category_spent(b.category_id) > b.amount_cents} for b in budgets]
    return page(request, db, "budgets.html", active_nav="orcamento", rows=rows, mes=f"{year:04d}-{month:02d}")

@router.post("/orcamento")
def save_budget(mes: str = Form(...), category_id: int = Form(...), amount: str = Form(...), db: Session = Depends(get_db)):
    try:
        year, month = parse_month(mes)
        if not db.get(Category, category_id):
            raise ValueError("Categoria inválida")
        cents = parse_brl_to_cents(amount)
        budget = db.scalar(select(Budget).where(Budget.year == year, Budget.month == month, Budget.category_id == category_id))
        if budget:
            budget.amount_cents = cents
        else:
            db.add(Budget(year=year, month=month, category_id=category_id, amount_cents=cents))
        db.commit()
    except ValueError:
        db.rollback()
    return RedirectResponse(f"/orcamento?mes={mes}", status_code=303)

@router.post("/orcamento/{budget_id}/excluir")
def delete_budget(budget_id: int, db: Session = Depends(get_db)):
    budget = db.get(Budget, budget_id)
    if budget:
        db.delete(budget)
        db.commit()
    return RedirectResponse("/orcamento", status_code=303)

@router.get("/projecao")
def projection(request: Request, db: Session = Depends(get_db)):
    from ..services.recurring import ensure_fixed_transactions
    from ..services.finance import add_months, month_key, incomes_for_month, active_transactions_for_month
    today = date.today()
    ensure_fixed_transactions(db, today)
    months = []
    for offset in range(12):
        current = add_months(today.replace(day=1), offset, 1)
        income = sum(i.amount_cents for i in incomes_for_month(db, current.year, current.month) if i.included_in_cashflow)
        expenses = sum(t.amount_cents for t in active_transactions_for_month(db, current.year, current.month, True))
        months.append({"key": month_key(current), "name": current.strftime("%m/%Y"), "income": income,
                       "expenses": expenses, "balance": income-expenses})
    return page(request, db, "projection.html", active_nav="projecao", months=months)
```

## `app/routers/cards.py`

```python
from collections import defaultdict
from datetime import date
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import CreditCard, FinancialTransaction
from ..services.finance import parse_month, month_start, month_end, category_name
from .common import page

router = APIRouter(prefix="/cartoes", tags=["cartões"])

@router.get("")
def card_invoices(request: Request, mes: str | None = None, cartao: int | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    cards = list(db.scalars(select(CreditCard).where(CreditCard.active.is_(True)).order_by(CreditCard.name)).all())
    credit_cards = [card for card in cards if card.kind == "credito"]
    selected_card = next((c for c in credit_cards if c.id == cartao), credit_cards[0] if credit_cards else None)
    start, end = month_start(year, month), month_end(year, month)
    items = []
    if selected_card:
        items = list(db.scalars(select(FinancialTransaction).where(
            FinancialTransaction.card_id == selected_card.id,
            FinancialTransaction.cashflow_date >= start,
            FinancialTransaction.cashflow_date <= end,
            FinancialTransaction.status != "cancelado",
        ).order_by(FinancialTransaction.cashflow_date, FinancialTransaction.id)).all())
    total = sum(t.amount_cents for t in items)
    card_totals = []
    for card in credit_cards:
        amount = sum(t.amount_cents for t in items if t.card_id == card.id) if selected_card and card.id == selected_card.id else 0
        card_totals.append({"card": card, "amount": amount})
    return page(request, db, "cards.html", active_nav="cartoes", mes=f"{year:04d}-{month:02d}", all_cards=cards,
                credit_cards=credit_cards, selected_card=selected_card, items=items, total=total, card_totals=card_totals)
```

## `app/routers/common.py`

```python
from datetime import date
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import Person, Category, Account, CreditCard
from ..services.finance import brl, date_br, category_name
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.filters["brl"] = brl
templates.env.filters["date_br"] = date_br

def base_context(request: Request, db: Session, **extra):
    people = list(db.scalars(select(Person).where(Person.active.is_(True)).order_by(Person.id)).all())
    categories = list(db.scalars(select(Category).where(Category.active.is_(True)).order_by(Category.parent_id, Category.name)).all())
    accounts = list(db.scalars(select(Account).where(Account.active.is_(True)).order_by(Account.name)).all())
    cards = list(db.scalars(select(CreditCard).where(CreditCard.active.is_(True)).order_by(CreditCard.name)).all())
    category_options = [{"id": c.id, "label": category_name(db, c.id), "name": c.name} for c in categories]
    context = {"request": request, "today": date.today(), "current_user": getattr(request.state, "current_user", None), "csrf_token": request.session.get("csrf_token", ""), "erro": request.query_params.get("erro"), "ok": request.query_params.get("ok"), "people": people,
               "categories": categories, "category_options": category_options,
               "accounts": accounts, "cards": cards, "active_nav": "", **extra}
    return context

def page(request: Request, db: Session, template: str, **extra):
    return templates.TemplateResponse(request=request, name=template, context=base_context(request, db, **extra))
```

## `app/routers/dashboard.py`

```python
from collections import defaultdict
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Income, FinancialTransaction, Budget, Category, CreditCard
from ..services.finance import active_transactions_for_month, incomes_for_month, month_start, month_end, add_months, parse_month, month_key, category_name
from ..services.recurring import ensure_fixed_transactions
from .common import page

router = APIRouter()

@router.get("/")
def dashboard(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    today = date.today()
    year, month = parse_month(mes, today)
    selected = month_start(year, month)
    ensure_fixed_transactions(db, today)
    incomes = incomes_for_month(db, year, month)
    cash_incomes = [i for i in incomes if i.included_in_cashflow]
    transactions = active_transactions_for_month(db, year, month, by_cashflow=True)
    income_total = sum(i.amount_cents for i in cash_incomes)
    expense_total = sum(t.amount_cents for t in transactions)
    previous_date = add_months(selected, -1, 1)
    prev_income = sum(i.amount_cents for i in incomes_for_month(db, previous_date.year, previous_date.month) if i.included_in_cashflow)
    prev_expense = sum(t.amount_cents for t in active_transactions_for_month(db, previous_date.year, previous_date.month, True))
    actual_purchase = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= month_start(year, month),
        FinancialTransaction.purchase_date <= month_end(year, month),
        FinancialTransaction.status == "realizado",
    )).all())
    category_actual = defaultdict(int)
    category_actual_ids = defaultdict(int)
    for transaction in actual_purchase:
        category_actual[category_name(db, transaction.category_id)] += transaction.amount_cents
        category_actual_ids[transaction.category_id] += transaction.amount_cents
    def budget_spend(category_id: int) -> int:
        category = db.get(Category, category_id)
        child_ids = list(db.scalars(select(Category.id).where(Category.parent_id == category_id)).all()) if category and category.parent_id is None else []
        return category_actual_ids[category_id] + sum(category_actual_ids[child_id] for child_id in child_ids)
    budgets = list(db.scalars(select(Budget).where(Budget.year == year, Budget.month == month)).all())
    budget_total = sum(b.amount_cents for b in budgets)
    actual_budgeted = sum(budget_spend(b.category_id) for b in budgets)
    budget_rows = []
    for budget in budgets:
        spent = budget_spend(budget.category_id)
        budget_rows.append({"name": category_name(db, budget.category_id), "amount": budget.amount_cents, "spent": spent,
                            "percent": min(999, (spent * 100 // budget.amount_cents) if budget.amount_cents else 0),
                            "over": spent > budget.amount_cents})
    # Tendência de 12 meses: a linha mostra o saldo acumulado do período selecionado.
    labels, incomes_data, expenses_data, balance_data = [], [], [], []
    running_balance = 0
    for offset in range(-11, 1):
        current = add_months(selected, offset, 1)
        label = f"{current.month:02d}/{str(current.year)[2:]}"
        monthly_income = sum(i.amount_cents for i in incomes_for_month(db, current.year, current.month) if i.included_in_cashflow)
        monthly_expense = sum(t.amount_cents for t in active_transactions_for_month(db, current.year, current.month, True))
        labels.append(label)
        incomes_data.append(monthly_income)
        expenses_data.append(monthly_expense)
        running_balance += monthly_income - monthly_expense
        balance_data.append(running_balance)
    pie_totals = defaultdict(int)
    for transaction in actual_purchase:
        pie_totals[category_name(db, transaction.category_id)] += transaction.amount_cents
    # Gráfico empilhado por cartão nos 6 meses mais recentes.
    card_months = [add_months(selected, offset, 1) for offset in range(-5, 1)]
    card_labels = [f"{d.month:02d}/{str(d.year)[2:]}" for d in card_months]
    all_cards = list(db.scalars(select(CreditCard).where(CreditCard.active.is_(True)).order_by(CreditCard.name)).all())
    card_datasets = []
    for card in all_cards:
        vals = []
        for cm in card_months:
            vals.append(sum(t.amount_cents for t in active_transactions_for_month(db, cm.year, cm.month, True) if t.card_id == card.id))
        if any(vals):
            card_datasets.append({"label": card.name, "data": vals})
    # Ranking e variação por data da compra, não pelo vencimento da fatura.
    current_cat, previous_cat = defaultdict(int), defaultdict(int)
    previous_purchase = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= month_start(previous_date.year, previous_date.month),
        FinancialTransaction.purchase_date <= month_end(previous_date.year, previous_date.month),
        FinancialTransaction.status != "cancelado")).all())
    for t in actual_purchase:
        current_cat[category_name(db, t.category_id)] += t.amount_cents
    for t in previous_purchase:
        previous_cat[category_name(db, t.category_id)] += t.amount_cents
    ranking = []
    for name, amount in sorted(current_cat.items(), key=lambda pair: pair[1], reverse=True)[:8]:
        old = previous_cat.get(name, 0)
        delta_pct = ((amount - old) * 100 // old) if old else (100 if amount else 0)
        ranking.append({"name": name, "amount": amount, "previous": old, "delta": delta_pct})
    upcoming = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.cashflow_date >= today,
        FinancialTransaction.cashflow_date <= today + timedelta(days=45),
        FinancialTransaction.status != "cancelado").order_by(FinancialTransaction.cashflow_date).limit(10)).all())
    chart_payload = {
        "pie": {"labels": list(pie_totals.keys()), "data": list(pie_totals.values())},
        "bars": {"labels": labels, "income": incomes_data, "expense": expenses_data},
        "line": {"labels": labels, "data": balance_data},
        "cards": {"labels": card_labels, "datasets": card_datasets},
    }
    return page(request, db, "dashboard.html", active_nav="dashboard", mes=month_key(selected), year=year, month=month,
                income_total=income_total, expense_total=expense_total, balance=income_total-expense_total,
                prev_income=prev_income, prev_expense=prev_expense, prev_balance=prev_income-prev_expense,
                income_count=len(cash_incomes), expense_count=len(transactions), budget_total=budget_total,
                actual_budgeted=actual_budgeted, budget_rows=budget_rows, ranking=ranking, upcoming=upcoming,
                chart_payload=chart_payload, previous_month=month_key(previous_date), actual_spend=sum(t.amount_cents for t in actual_purchase))

@router.get("/partials/proximos")
def upcoming_partial(request: Request, db: Session = Depends(get_db)):
    from datetime import timedelta
    from .common import templates
    from .common import base_context
    today = date.today()
    rows = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.cashflow_date >= today,
        FinancialTransaction.cashflow_date <= today + timedelta(days=45),
        FinancialTransaction.status != "cancelado").order_by(FinancialTransaction.cashflow_date).limit(10)).all())
    return templates.TemplateResponse(request=request, name="partials/upcoming_rows.html",
                                      context=base_context(request, db, rows=rows))
```

## `app/routers/incomes.py`

```python
from datetime import date
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Income, Person
from ..services.finance import parse_brl_to_cents, parse_month, month_start, month_end
from .common import page

router = APIRouter(prefix="/receitas", tags=["receitas"])

KINDS = {"salario": "Salário", "extra": "Renda extra", "plano_saude": "Plano de saúde (desconto em folha)",
         "inss": "INSS (desconto em folha)", "ir": "IR (desconto em folha)",
         "vale": "Vale (desconto em folha)", "outros_desconto": "Outros (desconto em folha)"}

@router.get("")
def incomes_page(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    rows = list(db.scalars(select(Income).where(Income.happened_on >= month_start(year, month),
                                       Income.happened_on <= month_end(year, month)).order_by(Income.happened_on.desc())).all())
    cash_total = sum(r.amount_cents for r in rows if r.included_in_cashflow)
    deductions = sum(r.amount_cents for r in rows if not r.included_in_cashflow)
    return page(request, db, "incomes.html", active_nav="receitas", rows=rows, mes=f"{year:04d}-{month:02d}",
                cash_total=cash_total, deductions=deductions, kinds=KINDS)

@router.post("")
def create_income(happened_on: date = Form(...), person_id: int = Form(...), kind: str = Form(...), amount: str = Form(...),
                  description: str = Form(""), db: Session = Depends(get_db)):
    try:
        if kind not in KINDS or not db.get(Person, person_id):
            raise ValueError("Seleção inválida")
        informational = kind in ("plano_saude", "inss", "ir", "vale", "outros_desconto")
        db.add(Income(person_id=person_id, kind=kind, happened_on=happened_on, amount_cents=parse_brl_to_cents(amount),
                      description=description.strip(), included_in_cashflow=not informational))
        db.commit()
    except ValueError:
        db.rollback()
    return RedirectResponse(f"/receitas?mes={happened_on.year:04d}-{happened_on.month:02d}", status_code=303)

@router.post("/{income_id}/excluir")
def delete_income(income_id: int, db: Session = Depends(get_db)):
    income = db.get(Income, income_id)
    if income:
        db.delete(income)
        db.commit()
    return RedirectResponse("/receitas", status_code=303)
```

## `app/routers/registrations.py`

```python
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import (
    Person, Category, Account, CreditCard, Income, FixedExpense,
    FinancialTransaction, Budget, SavingsAccount,
)
from ..services.finance import parse_brl_to_cents
from .common import page

router = APIRouter(prefix="/cadastros", tags=["cadastros"])
CARD_KINDS = {"credito", "debito", "vale_alimentacao"}


@router.get("")
def registrations(request: Request, db: Session = Depends(get_db)):
    people = list(db.scalars(select(Person).order_by(Person.id)).all())
    categories = list(db.scalars(select(Category).order_by(Category.parent_id, Category.name)).all())
    accounts = list(db.scalars(select(Account).order_by(Account.name)).all())
    cards = list(db.scalars(select(CreditCard).order_by(CreditCard.name)).all())
    return page(request, db, "registrations.html", active_nav="cadastros", all_people=people,
                all_categories=categories, all_accounts=accounts, all_cards=cards)


@router.post("/pessoas")
def create_person(name: str = Form(...), db: Session = Depends(get_db)):
    clean = name.strip()
    if clean:
        existing = db.scalar(select(Person).where(Person.name == clean))
        if existing:
            if not existing.active:
                existing.active = True
                db.commit()
        else:
            db.add(Person(name=clean))
            db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)


@router.post("/pessoas/{person_id}/editar")
def update_person(person_id: int, name: str = Form(...), active: str = Form("sim"), db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    clean = name.strip()
    if person and clean:
        duplicate = db.scalar(select(Person.id).where(Person.name == clean, Person.id != person_id))
        if duplicate:
            return RedirectResponse("/cadastros?erro=Já+existe+uma+pessoa+com+esse+nome", status_code=303)
        person.name = clean
        person.active = active == "sim"
        db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)


def _person_has_history(db: Session, person_id: int) -> bool:
    references = (
        (Income, Income.person_id), (Account, Account.person_id),
        (CreditCard, CreditCard.owner_id), (FixedExpense, FixedExpense.person_id),
        (FinancialTransaction, FinancialTransaction.person_id),
        (SavingsAccount, SavingsAccount.person_id),
    )
    return any(db.scalar(select(model.id).where(column == person_id).limit(1)) is not None
               for model, column in references)


@router.post("/pessoas/{person_id}/excluir")
def delete_person(person_id: int, db: Session = Depends(get_db)):
    person = db.get(Person, person_id)
    if person:
        # Pessoas padrão e pessoas referenciadas são inativadas para não sumirem do histórico nem voltarem no seed.
        if person.name in ("Marido", "Esposa", "Família") or _person_has_history(db, person_id):
            person.active = False
        else:
            db.delete(person)
        db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)


@router.post("/categorias")
def create_category(name: str = Form(...), parent_id: str = Form(""), db: Session = Depends(get_db)):
    clean = name.strip()
    parent = int(parent_id) if parent_id else None
    if clean and (parent is None or (db.get(Category, parent) and db.get(Category, parent).active)):
        existing = db.scalar(select(Category).where(Category.name == clean, Category.parent_id == parent))
        if existing:
            if not existing.active:
                existing.active = True
                db.commit()
        else:
            db.add(Category(name=clean, parent_id=parent))
            db.commit()
    return RedirectResponse("/cadastros", status_code=303)


def _category_has_history(db: Session, category_id: int) -> bool:
    references = (
        (FinancialTransaction, FinancialTransaction.category_id),
        (FixedExpense, FixedExpense.category_id),
        (Budget, Budget.category_id),
        (SavingsAccount, SavingsAccount.category_id),
    )
    return any(db.scalar(select(model.id).where(column == category_id).limit(1)) is not None
               for model, column in references)


@router.post("/categorias/{category_id}/excluir")
def delete_category(category_id: int, db: Session = Depends(get_db)):
    category = db.get(Category, category_id)
    if category:
        # Categorias são desativadas para permanecer fora dos formulários sem quebrar relatórios antigos.
        category.active = False
        children = list(db.scalars(select(Category).where(Category.parent_id == category_id)).all())
        for child in children:
            child.active = False
        db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)


@router.post("/contas")
def create_account(name: str = Form(...), kind: str = Form("corrente"), person_id: str = Form(""),
                   initial_balance: str = Form("0,00"), db: Session = Depends(get_db)):
    clean = name.strip()
    if clean and not db.scalar(select(Account.id).where(Account.name == clean)):
        try:
            db.add(Account(name=clean, kind=kind if kind in ("corrente", "poupanca", "dinheiro", "outro") else "corrente",
                           person_id=int(person_id) if person_id else None,
                           initial_balance_cents=parse_brl_to_cents(initial_balance)))
            db.commit()
        except (ValueError, IntegrityError):
            db.rollback()
    return RedirectResponse("/cadastros", status_code=303)


@router.post("/cartoes")
def create_card(
    name: str = Form(...), owner_id: int = Form(...), kind: str = Form("credito"),
    closing_day: int | None = Form(None), due_day: int | None = Form(None),
    limit: str = Form("0,00"), payment_account_id: str = Form(""),
    last_four_digits: str = Form(""), db: Session = Depends(get_db),
):
    clean = name.strip()
    last_four_digits = last_four_digits.strip()
    if last_four_digits and (len(last_four_digits) != 4 or not last_four_digits.isascii() or not last_four_digits.isdigit()):
        return RedirectResponse("/cadastros?erro=Informe+somente+os+4+ultimos+digitos+do+cartao", status_code=303)
    if not clean or not db.get(Person, owner_id) or kind not in CARD_KINDS:
        return RedirectResponse("/cadastros?erro=Dados+do+cartão+inválidos", status_code=303)
    try:
        if kind == "credito":
            if closing_day is None or due_day is None or not 1 <= closing_day <= 31 or not 1 <= due_day <= 31:
                raise ValueError("Informe os dias de fechamento e vencimento do cartão de crédito.")
        else:
            # Cartões de débito não têm ciclo de fatura.
            closing_day, due_day = 0, 0
        db.add(CreditCard(
            name=clean, owner_id=owner_id, kind=kind, closing_day=closing_day or 0, due_day=due_day or 0,
            limit_cents=parse_brl_to_cents(limit), last_four_digits=last_four_digits,
            payment_account_id=int(payment_account_id) if payment_account_id else None,
        ))
        db.commit()
    except (ValueError, TypeError, IntegrityError) as exc:
        db.rollback()
        msg = str(exc) if isinstance(exc, ValueError) else "Não foi possível salvar o cartão"
        return RedirectResponse(f"/cadastros?erro={msg.replace(' ', '+')}", status_code=303)
    return RedirectResponse("/cadastros?ok=1", status_code=303)


@router.post("/cartoes/{card_id}/editar")
def update_card(card_id: int, last_four_digits: str = Form(""), db: Session = Depends(get_db)):
    card = db.get(CreditCard, card_id)
    digits = last_four_digits.strip()
    if not card:
        return RedirectResponse("/cadastros?erro=Cartao+nao+encontrado", status_code=303)
    if digits and (len(digits) != 4 or not digits.isascii() or not digits.isdigit()):
        return RedirectResponse("/cadastros?erro=Informe+zero+ou+quatro+digitos", status_code=303)
    card.last_four_digits = digits
    db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)
```

## `app/routers/reports.py`

```python
import csv
import io
import os
import sqlite3
import tempfile
from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db, engine, DATABASE_URL
from ..models import FinancialTransaction, Income
from ..services.finance import parse_month, month_start, month_end, category_name
from .common import page

router = APIRouter(tags=["relatórios"])

@router.get("/planejados")
def planned_page(request: Request, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(FinancialTransaction).where(FinancialTransaction.status == "previsto")
                           .order_by(FinancialTransaction.cashflow_date, FinancialTransaction.id)).all())
    return page(request, db, "planned.html", active_nav="planejados", rows=rows)

@router.get("/historico")
def history_page(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    start, end = month_start(year, month), month_end(year, month)
    txs = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= start, FinancialTransaction.purchase_date <= end,
        FinancialTransaction.status == "realizado")).all())
    incomes = list(db.scalars(select(Income).where(Income.happened_on >= start, Income.happened_on <= end)).all())
    category_totals, person_totals, card_totals = {}, {}, {}
    for t in txs:
        label = category_name(db, t.category_id)
        category_totals[label] = category_totals.get(label, 0) + t.amount_cents
        person_totals[t.person.name] = person_totals.get(t.person.name, 0) + t.amount_cents
        if t.card:
            card_totals[t.card.name] = card_totals.get(t.card.name, 0) + t.amount_cents
    summary = lambda mapping: sorted([{"name": k, "amount": v} for k, v in mapping.items()], key=lambda item: item["amount"], reverse=True)
    top_expenses = sorted(txs, key=lambda t: t.amount_cents, reverse=True)[:10]
    return page(request, db, "history.html", active_nav="historico", mes=f"{year:04d}-{month:02d}",
                category_totals=summary(category_totals), person_totals=summary(person_totals), card_totals=summary(card_totals),
                top_expenses=top_expenses, income_total=sum(i.amount_cents for i in incomes if i.included_in_cashflow),
                expense_total=sum(t.amount_cents for t in txs))

@router.get("/relatorios")
def reports_page(request: Request, db: Session = Depends(get_db)):
    return page(request, db, "reports.html", active_nav="relatorios", default_start=date.today().replace(day=1).isoformat(), default_end=date.today().isoformat())

@router.get("/exportar.csv")
def export_csv(inicio: date, fim: date, db: Session = Depends(get_db)):
    if fim < inicio:
        return RedirectResponse("/relatorios?erro=Período+inválido", status_code=303)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["tipo", "data_compra_ou_receita", "data_fluxo_caixa", "descrição", "valor_centavos", "valor_brl", "categoria", "pessoa", "conta", "cartão", "status", "parcela"])
    txs = db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= inicio, FinancialTransaction.purchase_date <= fim,
    ).order_by(FinancialTransaction.purchase_date, FinancialTransaction.id)).all()
    for t in txs:
        writer.writerow(["despesa", t.purchase_date.isoformat(), t.cashflow_date.isoformat(), t.description, t.amount_cents,
                         f"{t.amount_cents // 100},{t.amount_cents % 100:02d}", category_name(db, t.category_id), t.person.name,
                         t.account.name if t.account else "", t.card.name if t.card else "", t.status,
                         f"{t.installment_number}/{t.installment_count}" if t.installment_number else ""])
    incomes = db.scalars(select(Income).where(Income.happened_on >= inicio, Income.happened_on <= fim).order_by(Income.happened_on)).all()
    kind_names = {"salario": "Salário", "extra": "Renda extra", "plano_saude": "Plano de saúde (desconto em folha)", "inss": "INSS (desconto em folha)", "ir": "IR (desconto em folha)", "vale": "Vale (desconto em folha)",
                  "outros_desconto": "Outros (desconto em folha)"}
    for income in incomes:
        writer.writerow(["receita" if income.included_in_cashflow else "desconto_informativo", income.happened_on.isoformat(), income.happened_on.isoformat(),
                         f"{kind_names.get(income.kind, income.kind)} — {income.description}", income.amount_cents,
                         f"{income.amount_cents // 100},{income.amount_cents % 100:02d}", "", income.person.name, "", "",
                         "incluído_no_fluxo" if income.included_in_cashflow else "informativo", ""])
    content = "\ufeff" + output.getvalue()
    filename = f"financeiro_{inicio.isoformat()}_{fim.isoformat()}.csv"
    return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.get("/backup.db")
def backup_database():
    if not DATABASE_URL.startswith("sqlite"):
        return RedirectResponse("/relatorios?erro=Backup+disponível+para+SQLite", status_code=303)
    fd, temp_path = tempfile.mkstemp(prefix="familia-financas-", suffix=".db")
    os.close(fd)
    source = engine.raw_connection()
    target = sqlite3.connect(temp_path)
    try:
        source.driver_connection.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return FileResponse(temp_path, media_type="application/x-sqlite3", filename=f"backup-financas-{date.today().isoformat()}.db",
                        background=BackgroundTask(lambda: os.path.exists(temp_path) and os.remove(temp_path)))
```

## `app/routers/savings.py`

```python
from datetime import date
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Person, Category, SavingsAccount, SavingsMovement
from ..services.finance import parse_brl_to_cents
from ..services.savings import savings_balance
from .common import page

router = APIRouter(prefix="/poupanca", tags=["poupança"])


@router.get("")
def savings_page(request: Request, db: Session = Depends(get_db)):
    accounts = list(db.scalars(select(SavingsAccount).where(SavingsAccount.active.is_(True)).order_by(SavingsAccount.person_id, SavingsAccount.name)).all())
    balances = [{"account": account, "balance": savings_balance(db, account)} for account in accounts]
    movements = list(db.scalars(
        select(SavingsMovement).join(SavingsAccount).where(SavingsAccount.active.is_(True))
        .order_by(SavingsMovement.happened_on.desc(), SavingsMovement.id.desc()).limit(100)
    ).all())
    total = sum(row["balance"] for row in balances)
    return page(request, db, "savings.html", active_nav="poupanca", savings_accounts=accounts,
                balances=balances, movements=movements, total_capital=total)


@router.post("/contas")
def create_savings_account(
    name: str = Form(...), person_id: int = Form(...), initial_balance: str = Form("0,00"),
    db: Session = Depends(get_db),
):
    clean = name.strip()
    person = db.get(Person, person_id)
    if not clean or not person or not person.active:
        return RedirectResponse("/poupanca?erro=Informe+um+nome+e+uma+pessoa+ativa", status_code=303)
    try:
        initial = parse_brl_to_cents(initial_balance)
        category = db.scalar(select(Category).where(Category.parent_id.is_(None), Category.name == "Poupança"))
        if category is None:
            category = Category(name="Poupança", active=True)
            db.add(category)
            db.flush()
        elif not category.active:
            category.active = True
        db.add(SavingsAccount(name=clean, person_id=person_id, category_id=category.id, initial_balance_cents=initial))
        db.commit()
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/poupanca?erro={str(exc).replace(' ', '+')}", status_code=303)
    return RedirectResponse("/poupanca?ok=1", status_code=303)


@router.post("/movimentos")
def create_movement(
    account_id: int = Form(...), happened_on: date = Form(...), kind: str = Form(...), amount: str = Form(...),
    description: str = Form(""), db: Session = Depends(get_db),
):
    account = db.get(SavingsAccount, account_id)
    if not account or not account.active or kind not in ("deposito", "retirada", "juros"):
        return RedirectResponse("/poupanca?erro=Movimentação+inválida", status_code=303)
    try:
        cents = parse_brl_to_cents(amount)
        if cents <= 0:
            raise ValueError("O valor deve ser maior que zero.")
        if kind == "retirada" and cents > savings_balance(db, account):
            raise ValueError("A retirada é maior que o capital disponível nesta poupança.")
        descriptions = {"deposito": "Depósito", "retirada": "Retirada", "juros": "Juros de aplicação"}
        db.add(SavingsMovement(account_id=account.id, happened_on=happened_on, kind=kind,
                               amount_cents=cents, description=description.strip() or descriptions[kind]))
        db.commit()
    except ValueError as exc:
        db.rollback()
        message = str(exc).replace(" ", "+")
        return RedirectResponse(f"/poupanca?erro={message}", status_code=303)
    return RedirectResponse("/poupanca?ok=1", status_code=303)
```

## `app/routers/transactions.py`

```python
from datetime import date
from uuid import uuid4
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import FinancialTransaction, Category, Person, Account, CreditCard
from ..services.finance import parse_brl_to_cents, cashflow_date_for, invoice_due_date, add_months, month_start, month_end, parse_month, month_key
from ..services.recurring import ensure_fixed_transactions
from .common import page

router = APIRouter(prefix="/transacoes", tags=["transações"])


def _optional_id(value: str | None) -> int | None:
    return int(value) if value and value.strip() else None

@router.get("")
def list_transactions(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    start, end = month_start(year, month), month_end(year, month)
    rows = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= start, FinancialTransaction.purchase_date <= end,
    ).order_by(FinancialTransaction.purchase_date.desc(), FinancialTransaction.id.desc())).all())
    return page(request, db, "transactions.html", active_nav="transacoes", rows=rows, mes=f"{year:04d}-{month:02d}")

@router.get("/nova")
def new_transaction(request: Request, tipo: str = "realizado", db: Session = Depends(get_db)):
    return page(request, db, "transaction_form.html", active_nav="transacoes", transaction=None,
                default_status="previsto" if tipo == "previsto" else "realizado", form_action="/transacoes/nova", title="Novo gasto")

@router.post("/nova")
def create_transaction(
    request: Request,
    description: str = Form(...), amount: str = Form(...), purchase_date: date = Form(...),
    category_id: int = Form(...), person_id: int = Form(...), account_id: str = Form(""), card_id: str = Form(""),
    status: str = Form("realizado"), installments: int = Form(1), db: Session = Depends(get_db),
):
    try:
        cents = parse_brl_to_cents(amount)
        account = _optional_id(account_id)
        card = _optional_id(card_id)
        if card and account:
            account = None
        category = db.get(Category, category_id)
        person = db.get(Person, person_id)
        if not category or not person:
            raise ValueError("Selecione categoria e responsável válidos.")
        if not 1 <= installments <= 60:
            raise ValueError("O parcelamento deve ter entre 1 e 60 parcelas.")
        if installments > 1 and not card:
            raise ValueError("Parcelamento só pode ser usado com cartão de crédito.")
        selected_card = db.get(CreditCard, card) if card else None
        if card and not selected_card:
            raise ValueError("Cartão não encontrado.")
        if installments > 1 and selected_card and selected_card.kind != "credito":
            raise ValueError("Parcelamento só está disponível em cartão de crédito.")
        if account and not db.get(Account, account):
            raise ValueError("Conta não encontrada.")
        if status not in ("previsto", "realizado"):
            status = "realizado"
        group = uuid4().hex[:16] if installments > 1 else None
        base, remainder = divmod(cents, installments)
        for index in range(installments):
            part_cents = base + (1 if index < remainder else 0)
            description_part = description.strip() if installments == 1 else f"{description.strip()} ({index + 1}/{installments})"
            if selected_card and selected_card.kind == "credito":
                due = invoice_due_date(selected_card, purchase_date)
                cashflow_date = add_months(due, index, due.day)
            else:
                # Débito e Vale Alimentação afetam o caixa na data da compra.
                cashflow_date = purchase_date
            db.add(FinancialTransaction(
                description=description_part, amount_cents=part_cents, purchase_date=purchase_date,
                cashflow_date=cashflow_date, category_id=category_id, person_id=person_id,
                account_id=account, card_id=card, status=status, installment_group=group,
                installment_number=index + 1 if installments > 1 else None,
                installment_count=installments if installments > 1 else None,
            ))
        db.commit()
        return RedirectResponse(url=f"/transacoes?mes={purchase_date.year:04d}-{purchase_date.month:02d}&ok=1", status_code=303)
    except (ValueError, TypeError) as exc:
        return RedirectResponse(url=f"/transacoes/nova?erro={str(exc)}", status_code=303)

@router.get("/{transaction_id}/editar")
def edit_transaction_form(transaction_id: int, request: Request, db: Session = Depends(get_db)):
    transaction = db.get(FinancialTransaction, transaction_id)
    if not transaction:
        return RedirectResponse("/transacoes", status_code=303)
    return page(request, db, "transaction_form.html", active_nav="transacoes", transaction=transaction,
                default_status=transaction.status, form_action=f"/transacoes/{transaction.id}/editar", title="Editar gasto")

@router.post("/{transaction_id}/editar")
def update_transaction(
    transaction_id: int, description: str = Form(...), amount: str = Form(...), purchase_date: date = Form(...),
    category_id: int = Form(...), person_id: int = Form(...), account_id: str = Form(""), card_id: str = Form(""),
    status: str = Form("realizado"), db: Session = Depends(get_db),
):
    transaction = db.get(FinancialTransaction, transaction_id)
    if not transaction:
        return RedirectResponse("/transacoes", status_code=303)
    try:
        transaction.description = description.strip()
        transaction.amount_cents = parse_brl_to_cents(amount)
        transaction.purchase_date = purchase_date
        transaction.category_id = category_id
        transaction.person_id = person_id
        transaction.account_id = _optional_id(account_id)
        transaction.card_id = _optional_id(card_id)
        if transaction.card_id and transaction.account_id:
            transaction.account_id = None
        transaction.cashflow_date = cashflow_date_for(db, transaction.card_id, purchase_date)
        transaction.status = status if status in ("previsto", "realizado", "cancelado") else "realizado"
        if transaction.fixed_expense_id:
            transaction.fixed_override = True
        db.commit()
    except ValueError:
        db.rollback()
        return RedirectResponse(f"/transacoes/{transaction_id}/editar?erro=Valor+inválido", status_code=303)
    return RedirectResponse(f"/transacoes?mes={purchase_date.year:04d}-{purchase_date.month:02d}&ok=1", status_code=303)

@router.post("/{transaction_id}/status")
def set_status(transaction_id: int, status: str = Form(...), db: Session = Depends(get_db)):
    transaction = db.get(FinancialTransaction, transaction_id)
    if transaction and status in ("previsto", "realizado", "cancelado"):
        transaction.status = status
        if transaction.fixed_expense_id and status == "cancelado":
            transaction.fixed_override = True
        db.commit()
    return RedirectResponse("/planejados" if status in ("realizado", "cancelado") else "/transacoes", status_code=303)

@router.post("/{transaction_id}/cancelar")
def cancel_transaction(transaction_id: int, db: Session = Depends(get_db)):
    transaction = db.get(FinancialTransaction, transaction_id)
    if transaction:
        transaction.status = "cancelado"
        if transaction.fixed_expense_id:
            transaction.fixed_override = True
        db.commit()
    return RedirectResponse("/planejados", status_code=303)

@router.get("/fixos")
def fixed_expenses(request: Request, db: Session = Depends(get_db)):
    from ..models import FixedExpense
    ensure_fixed_transactions(db)
    fixed = list(db.scalars(select(FixedExpense).order_by(FixedExpense.active.desc(), FixedExpense.name)).all())
    return page(request, db, "fixed.html", active_nav="fixos", fixed_items=fixed)

@router.post("/fixos")
def create_fixed(
    name: str = Form(...), amount: str = Form(...), day_of_month: int = Form(...), category_id: int = Form(...),
    person_id: int = Form(...), start_date: date = Form(...), end_date: str = Form(""),
    account_id: str = Form(""), card_id: str = Form(""), db: Session = Depends(get_db),
):
    from ..models import FixedExpense
    try:
        cents = parse_brl_to_cents(amount)
        if not 1 <= day_of_month <= 31:
            raise ValueError("O dia deve ficar entre 1 e 31.")
        end = date.fromisoformat(end_date) if end_date else None
        card = _optional_id(card_id)
        account = _optional_id(account_id) if not card else None
        db.add(FixedExpense(name=name.strip(), amount_cents=cents, day_of_month=day_of_month,
                            category_id=category_id, person_id=person_id, start_date=start_date,
                            end_date=end, account_id=account, card_id=card, active=True))
        db.commit()
        ensure_fixed_transactions(db)
    except (ValueError, TypeError):
        db.rollback()
    return RedirectResponse("/transacoes/fixos", status_code=303)

@router.post("/fixos/{fixed_id}/editar")
def update_fixed(
    fixed_id: int, name: str = Form(...), amount: str = Form(...), day_of_month: int = Form(...),
    category_id: int = Form(...), person_id: int = Form(...), start_date: date = Form(...), end_date: str = Form(""),
    active: str = Form("sim"), account_id: str = Form(""), card_id: str = Form(""), db: Session = Depends(get_db),
):
    from ..models import FixedExpense
    fixed = db.get(FixedExpense, fixed_id)
    if fixed:
        try:
            fixed.name = name.strip()
            fixed.amount_cents = parse_brl_to_cents(amount)
            fixed.day_of_month = max(1, min(31, day_of_month))
            fixed.category_id, fixed.person_id = category_id, person_id
            fixed.start_date = start_date
            fixed.end_date = date.fromisoformat(end_date) if end_date else None
            was_active = fixed.active
            fixed.active = active == "sim"
            fixed.card_id = _optional_id(card_id)
            fixed.account_id = _optional_id(account_id) if not fixed.card_id else None
            future_occurrences = db.scalars(select(FinancialTransaction).where(
                FinancialTransaction.fixed_expense_id == fixed.id,
                FinancialTransaction.occurrence_month >= month_start(date.today().year, date.today().month),
            )).all()
            for occurrence in future_occurrences:
                in_vigency = occurrence.occurrence_month >= month_start(fixed.start_date.year, fixed.start_date.month)
                if fixed.end_date:
                    in_vigency = in_vigency and occurrence.occurrence_month <= month_start(fixed.end_date.year, fixed.end_date.month)
                if not fixed.active or not in_vigency:
                    if occurrence.status == "previsto":
                        occurrence.status = "cancelado"
                    continue
                if occurrence.status == "cancelado" and not occurrence.fixed_override:
                    occurrence.status = "previsto"
                if occurrence.status != "previsto" or occurrence.fixed_override:
                    continue
                occurrence.purchase_date = add_months(occurrence.occurrence_month, 0, fixed.day_of_month)
                if occurrence.occurrence_month.year == fixed.start_date.year and occurrence.occurrence_month.month == fixed.start_date.month and occurrence.purchase_date < fixed.start_date:
                    occurrence.purchase_date = fixed.start_date
                if fixed.end_date and occurrence.purchase_date > fixed.end_date:
                    occurrence.status = "cancelado"
                    continue
                occurrence.description = fixed.name
                occurrence.amount_cents = fixed.amount_cents
                occurrence.category_id = fixed.category_id
                occurrence.person_id = fixed.person_id
                occurrence.account_id = fixed.account_id
                occurrence.card_id = fixed.card_id
                occurrence.cashflow_date = cashflow_date_for(db, fixed.card_id, occurrence.purchase_date)
            db.commit()
            ensure_fixed_transactions(db)
        except (ValueError, TypeError):
            db.rollback()
    return RedirectResponse("/transacoes/fixos", status_code=303)
```

## `app/schemas.py`

```python
from datetime import date
from pydantic import BaseModel, Field, ConfigDict, model_validator

class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class IncomeCreate(BaseModel):
    person_id: int
    kind: str = Field(pattern="^(salario|extra|plano_saude|inss|ir)$")
    happened_on: date
    amount_cents: int = Field(ge=0)
    description: str = ""

class TransactionCreate(BaseModel):
    description: str = Field(min_length=1, max_length=240)
    amount_cents: int = Field(ge=0)
    purchase_date: date
    category_id: int
    person_id: int
    account_id: int | None = None
    card_id: int | None = None
    status: str = Field(default="realizado", pattern="^(previsto|realizado)$")
    installments: int = Field(default=1, ge=1, le=60)
    @model_validator(mode="after")
    def payment_method(self):
        if self.card_id and self.account_id:
            raise ValueError("Escolha cartão ou conta, não ambos.")
        return self

class FixedExpenseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    amount_cents: int = Field(ge=0)
    day_of_month: int = Field(ge=1, le=31)
    category_id: int
    person_id: int
    start_date: date
    end_date: date | None = None
    account_id: int | None = None
    card_id: int | None = None
```

## `app/security.py`

```python
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
```

## `app/seed.py`

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Person, Category, User
from .security import hash_password

PEOPLE = ["Marido", "Esposa", "Família"]
CATEGORIES = {
    "Moradia": ["Aluguel/Financiamento", "Condomínio", "Energia elétrica", "Água", "Internet", "Gás", "Reparos"],
    "Alimentação": ["Supermercado", "Feira", "Restaurante/Delivery", "Lanches"],
    "Educação/Colégio": ["Mensalidade", "Material escolar", "Uniforme", "Eventos/Passeios", "Transporte escolar"],
    "Saúde": ["Farmácia", "Consultas/Exames", "Odontologia", "Plano de saúde (informativo)"],
    "Transporte/Onix": ["Combustível", "Seguro", "IPVA/Licenciamento", "Manutenção", "Estacionamento/Pedágio", "Lavagem"],
    # Lazer fica sem subcategorias para que a descrição livre informe o tipo de gasto.
    "Lazer": [],
    "Filha": ["Roupas/Calçados", "Brinquedos", "Atividades", "Festas/Presentes"],
    "Assinaturas": ["Streaming", "Software/Apps", "Telefonia"],
    "Impostos": ["IR (informativo)", "INSS (informativo)", "Taxas e tributos"],
    "Poupança": [],
    "Outros": ["Presentes", "Serviços", "Animais de estimação", "Diversos"],
}


def _migrate_lazer_categories(db: Session) -> None:
    """Desativa a taxonomia antiga de moto sem apagar referências históricas."""
    old_root = db.scalar(select(Category).where(Category.name == "Lazer/Moto", Category.parent_id.is_(None)))
    lazer_root = db.scalar(select(Category).where(Category.name == "Lazer", Category.parent_id.is_(None)))
    if old_root:
        if not lazer_root:
            old_root.name = "Lazer"
            lazer_root = old_root
        else:
            old_root.active = False
        for child in db.scalars(select(Category).where(Category.parent_id == old_root.id)).all():
            child.active = False
    for category in db.scalars(select(Category).where(Category.name.ilike("%moto%"))).all():
        category.active = False


def seed_database(db: Session) -> None:
    # Pessoas padrão são inseridas só em banco vazio; renomeações/exclusões não são desfeitas no próximo boot.
    if not db.scalar(select(Person.id).limit(1)):
        for name in PEOPLE:
            db.add(Person(name=name))
        db.flush()
    # Cria Admin/admin apenas no primeiro boot; o primeiro login exige troca imediata.
    if not db.scalar(select(User.id).limit(1)):
        admin_name = "Admin"
        admin_password = "admin"
        db.add(User(username=admin_name, username_key=admin_name.casefold(),
                    password_hash=hash_password(admin_password), is_admin=True,
                    is_active=True, must_change_password=True))
        db.flush()
    _migrate_lazer_categories(db)
    roots = {c.name: c for c in db.scalars(select(Category).where(Category.parent_id.is_(None))).all()}
    for root_name, children in CATEGORIES.items():
        root = roots.get(root_name)
        if root is None:
            root = Category(name=root_name)
            db.add(root)
            db.flush()
        existing_children = set(db.scalars(select(Category.name).where(Category.parent_id == root.id)).all())
        for child_name in children:
            if child_name not in existing_children:
                db.add(Category(name=child_name, parent_id=root.id))
    db.commit()
```

## `app/services/__init__.py`

```python
"""Regras de negócio."""
```

## `app/services/finance.py`

```python
import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import CreditCard, Category, FinancialTransaction, Income


def parse_brl_to_cents(value: str | int | None) -> int:
    """Converte entrada BR/decimal para centavos sem aritmética monetária em float."""
    if value is None or str(value).strip() == "":
        return 0
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Informe um valor válido, por exemplo 123,45.") from exc
    if amount < 0:
        raise ValueError("O valor não pode ser negativo.")
    return int(amount * 100)


def brl(cents: int | None) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    integer, decimal = divmod(cents, 100)
    whole = f"{integer:,}".replace(",", ".")
    return f"{sign}R$ {whole},{decimal:02d}"


def date_br(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(value: date, count: int, day: int | None = None) -> date:
    zero_based = value.month - 1 + count
    year = value.year + zero_based // 12
    month = zero_based % 12 + 1
    target_day = day if day is not None else value.day
    return date(year, month, min(target_day, calendar.monthrange(year, month)[1]))


def parse_month(value: str | None, default: date | None = None) -> tuple[int, int]:
    fallback = default or date.today()
    if not value:
        return fallback.year, fallback.month
    try:
        year, month = (int(part) for part in value.split("-", 1))
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except (ValueError, TypeError):
        return fallback.year, fallback.month


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def invoice_due_date(card: CreditCard, purchase_date: date) -> date:
    """Calcula vencimento apenas para cartão de crédito."""
    if card.kind != "credito":
        return purchase_date
    close_date = date(purchase_date.year, purchase_date.month,
                      min(card.closing_day, calendar.monthrange(purchase_date.year, purchase_date.month)[1]))
    closing_month = purchase_date if purchase_date <= close_date else add_months(purchase_date, 1, card.closing_day)
    # Se o vencimento ocorre antes/no dia do fechamento, a fatura vence no mês seguinte.
    due_month_offset = 0 if card.due_day > card.closing_day else 1
    return add_months(closing_month, due_month_offset, card.due_day)


def category_name(db: Session, category_id: int | None) -> str:
    if not category_id:
        return "Sem categoria"
    category = db.get(Category, category_id)
    if not category:
        return "Sem categoria"
    return f"{category.parent.name} / {category.name}" if category.parent else category.name


def cashflow_date_for(db: Session, card_id: int | None, purchase_date: date) -> date:
    if card_id:
        card = db.get(CreditCard, card_id)
        if not card:
            raise ValueError("Cartão não encontrado.")
        return invoice_due_date(card, purchase_date) if card.kind == "credito" else purchase_date
    return purchase_date


def incomes_for_month(db: Session, year: int, month: int) -> list[Income]:
    start, end = month_start(year, month), month_end(year, month)
    return list(db.scalars(select(Income).where(Income.happened_on >= start, Income.happened_on <= end).order_by(Income.happened_on.desc())).all())


def active_transactions_for_month(db: Session, year: int, month: int, by_cashflow: bool = True) -> list[FinancialTransaction]:
    start, end = month_start(year, month), month_end(year, month)
    column = FinancialTransaction.cashflow_date if by_cashflow else FinancialTransaction.purchase_date
    return list(db.scalars(select(FinancialTransaction).where(
        column >= start, column <= end, FinancialTransaction.status != "cancelado"
    ).order_by(column.desc(), FinancialTransaction.id.desc())).all())
```

## `app/services/recurring.py`

```python
from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import FixedExpense, FinancialTransaction
from .finance import add_months, cashflow_date_for, month_start


def ensure_fixed_transactions(db: Session, today: date | None = None, months_ahead: int = 12) -> int:
    """Gera ocorrências ausentes até o horizonte, sem duplicar ajustes existentes."""
    today = today or date.today()
    horizon = month_start(add_months(today, months_ahead).year, add_months(today, months_ahead).month)
    created = 0
    fixed_items = db.scalars(select(FixedExpense).where(FixedExpense.active.is_(True))).all()
    for fixed in fixed_items:
        occurrence = month_start(fixed.start_date.year, fixed.start_date.month)
        last = horizon
        if fixed.end_date:
            last = min(last, month_start(fixed.end_date.year, fixed.end_date.month))
        while occurrence <= last:
            exists = db.scalar(select(FinancialTransaction.id).where(
                FinancialTransaction.fixed_expense_id == fixed.id,
                FinancialTransaction.occurrence_month == occurrence,
            ))
            if not exists and (not fixed.end_date or occurrence <= month_start(fixed.end_date.year, fixed.end_date.month)):
                purchase_date = add_months(occurrence, 0, fixed.day_of_month)
                if occurrence.year == fixed.start_date.year and occurrence.month == fixed.start_date.month and purchase_date < fixed.start_date:
                    purchase_date = fixed.start_date
                if fixed.end_date and purchase_date > fixed.end_date:
                    occurrence = add_months(occurrence, 1, 1)
                    continue
                db.add(FinancialTransaction(
                    description=fixed.name, amount_cents=fixed.amount_cents,
                    purchase_date=purchase_date,
                    cashflow_date=cashflow_date_for(db, fixed.card_id, purchase_date),
                    category_id=fixed.category_id, person_id=fixed.person_id,
                    account_id=fixed.account_id, card_id=fixed.card_id,
                    status="previsto", fixed_expense_id=fixed.id,
                    occurrence_month=occurrence,
                ))
                created += 1
            occurrence = add_months(occurrence, 1, 1)
    if created:
        db.commit()
    return created
```

## `app/services/savings.py`

```python
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import SavingsAccount, SavingsMovement


def savings_balance(db: Session, account: SavingsAccount) -> int:
    """Saldo sempre em centavos: depósitos/juros somam e retiradas subtraem."""
    movements = db.scalars(select(SavingsMovement).where(SavingsMovement.account_id == account.id)).all()
    balance = account.initial_balance_cents
    for movement in movements:
        if movement.kind in ("deposito", "juros"):
            balance += movement.amount_cents
        elif movement.kind == "retirada":
            balance -= movement.amount_cents
    return balance
```

## `app/static/css/app.css`

```css
:root {
  --ink: #183b30; --green: #236b56; --green-dark: #174b3b; --green-soft: #e8f3ed;
  --paper: #f5f7f4; --surface: #fff; --muted: #6c7b73; --line: #e0e7e1;
  --amber: #e2a348; --red: #b8473d; --red-soft: #fff0ed; --shadow: 0 8px 28px rgba(31, 63, 48, .055);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink); background: var(--paper); font-synthesis: none; text-rendering: optimizeLegibility;
}
* { box-sizing: border-box; }
html { min-width: 320px; width: 100%; overflow-x: hidden; }
body { margin: 0; width: 100%; min-height: 100vh; overflow-x: hidden; background: var(--paper); font-size: 14px; line-height: 1.45; }
a { color: var(--green); text-decoration: none; }
a:hover { color: var(--green-dark); }
button, input, select, textarea { font: inherit; }
button, .button { cursor: pointer; }
.topbar { min-height: 72px; padding: 14px max(18px, calc((100vw - 1240px) / 2)); display: flex; align-items: center; justify-content: space-between; background: #12352d; color: #fff; gap: 16px; }
.brand { display: inline-flex; align-items: center; gap: 11px; color: #fff; font-weight: 750; font-size: 17px; letter-spacing: -.3px; }
.brand:hover { color: #fff; }
.brand small { display: block; color: #b7cec2; font-size: 11px; font-weight: 500; letter-spacing: .04em; }
.brand-mark { background: #d7e8d9; color: #153e31; border-radius: 12px; width: 42px; height: 42px; display: inline-grid; place-items: center; font-size: 13px; font-weight: 850; }
.top-date { font-size: 12px; color: #c2d4ca; white-space: nowrap; }
.nav-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 4px; padding: 8px max(12px, calc((100vw - 1240px) / 2)); background: #fff; border-bottom: 1px solid var(--line); }
.nav-item { min-height: 37px; display: flex; align-items: center; justify-content: center; text-align: center; padding: 7px 6px; border-radius: 8px; font-size: 11px; font-weight: 650; color: #5a6a61; white-space: nowrap; }
.nav-item:hover { background: #f1f6f2; color: var(--ink); }
.nav-item.active { color: #fff; background: var(--green); }
.container { max-width: 1240px; width: 100%; margin: 0 auto; padding: 26px 18px 38px; min-height: calc(100vh - 180px); }
.footer { color: #87948d; text-align: center; padding: 20px 12px 28px; font-size: 11px; }
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: clamp(25px, 3.3vw, 32px); line-height: 1.15; margin-bottom: 7px; letter-spacing: -.8px; color: #14382d; }
h2 { font-size: 17px; letter-spacing: -.28px; margin-bottom: 13px; }
h3 { font-size: 15px; margin-bottom: 5px; }
.eyebrow { color: #468269; font-size: 10px; font-weight: 800; letter-spacing: .15em; margin-bottom: 7px; }
.muted { color: var(--muted); }
.page-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 22px; }
.page-head p { margin-bottom: 0; }
.month-form, .filter-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.month-form { background: #fff; border: 1px solid var(--line); padding: 9px; border-radius: 12px; box-shadow: var(--shadow); }
.month-form label, .filter-bar label { font-size: 12px; color: var(--muted); font-weight: 650; }
input, select, textarea { min-width: 0; max-width: 100%; color: var(--ink); background: #fff; border: 1px solid #d6e0d8; border-radius: 9px; padding: 10px 11px; width: 100%; outline: none; }
input:focus, select:focus, textarea:focus { border-color: #559a7e; box-shadow: 0 0 0 3px rgba(35, 107, 86, .10); }
.month-form input, .filter-bar input, .filter-bar select { width: auto; min-width: 130px; }
.button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; border: 1px solid var(--green); background: var(--green); color: #fff; border-radius: 9px; padding: 10px 15px; font-weight: 700; font-size: 12px; line-height: 1.2; min-height: 38px; text-align: center; white-space: nowrap; }
.button:hover { color: #fff; background: var(--green-dark); border-color: var(--green-dark); }
.button-light { color: var(--green); border-color: #d7e3d9; background: #fff; }
.button-light:hover { background: var(--green-soft); color: var(--green-dark); border-color: #c3d8c9; }
.button-danger { background: #fff5f2; color: var(--red); border-color: #f0d4cd; }
.button-danger:hover { background: var(--red); border-color: var(--red); color: #fff; }
.button-small { min-height: 30px; padding: 7px 9px; font-size: 11px; border-radius: 7px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; margin-bottom: 25px; }
.metric-grid-two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.metric { min-width: 0; padding: 19px 18px 16px; border: 1px solid var(--line); border-radius: 14px; background: #fff; box-shadow: var(--shadow); }
.metric > span { color: #6a7b71; display: block; font-size: 12px; font-weight: 650; margin-bottom: 9px; }
.metric strong { display: block; font-size: clamp(19px, 2vw, 25px); letter-spacing: -.7px; color: #1b3d31; overflow-wrap: anywhere; }
.metric small { display: block; margin-top: 8px; font-size: 11px; line-height: 1.4; color: #7e8c84; }
.metric-good { border-top: 3px solid #4c9674; }
.metric-danger { border-top: 3px solid var(--red); }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; margin: 26px 0 13px; }
.section-heading h2 { margin-bottom: 3px; }
.section-heading p { font-size: 12px; margin-bottom: 0; }
.compare-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 13px; margin-bottom: 25px; }
.compare-card { border: 1px solid var(--line); border-radius: 12px; background: #fff; padding: 15px 17px; min-width: 0; }
.compare-card span, .compare-card small { display: block; font-size: 11px; color: var(--muted); }
.compare-card b { display: block; margin: 6px 0; font-size: 20px; }
.chart-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.panel { min-width: 0; background: var(--surface); border: 1px solid var(--line); border-radius: 14px; padding: 19px; box-shadow: var(--shadow); }
.chart-panel { min-width: 0; }
.chart-panel .muted { font-size: 11px; margin-bottom: 12px; }
.chart-wrap { position: relative; width: 100%; min-width: 0; height: 255px; }
.chart-wrap canvas { display: block; width: 100%; height: 100%; }
.content-grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, .85fr); gap: 14px; }
.section-gap { margin-top: 22px; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-heading h2 { margin-bottom: 3px; }
.panel-heading p { margin-bottom: 0; font-size: 11px; }
.text-link { font-size: 12px; font-weight: 750; white-space: nowrap; }
.budget-list { display: grid; gap: 14px; }
.budget-row { min-width: 0; }
.row-between { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; font-size: 11px; margin-bottom: 7px; }
.row-between span { overflow-wrap: anywhere; }
.row-between strong { text-align: right; font-size: 11px; white-space: nowrap; }
.progress { height: 7px; background: #e8eee9; border-radius: 99px; overflow: hidden; }
.progress span { display: block; height: 100%; background: #3e8c68; border-radius: 99px; max-width: 100%; }
.progress span.over { background: var(--red); }
.budget-row small { display: block; font-size: 10px; margin-top: 5px; }
.danger-text { color: var(--red) !important; }
.good-text { color: #2e805c !important; }
.change { display: inline-block; font-size: 11px; font-weight: 750; }
.table-wrap { width: 100%; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 12px; text-align: left; }
th { color: #66766d; font-size: 10px; font-weight: 750; letter-spacing: .025em; text-transform: uppercase; background: #f7f9f7; }
th, td { padding: 12px 10px; border-bottom: 1px solid #edf0ed; vertical-align: middle; }
td { color: #31483c; }
tbody tr:last-child td { border-bottom: 0; }
td.money, th.money { text-align: right; white-space: nowrap; font-weight: 750; }
tfoot th { text-transform: none; font-size: 12px; color: var(--ink); }
.subline { display: block; margin-top: 3px; color: #7e8b83; font-size: 10px; line-height: 1.25; }
.empty-cell { text-align: center; padding: 30px 12px; color: #829087; }
.empty-state { border: 1px dashed #d9e2db; padding: 20px; border-radius: 10px; font-size: 12px; line-height: 1.6; color: var(--muted); background: #fbfcfb; }
.empty-state a { font-weight: 750; }
.empty-hint { color: #7e8b83; font-size: 12px; text-align: center; }
.upcoming-list { display: grid; }
.upcoming-item { display: grid; grid-template-columns: 43px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 11px 0; border-bottom: 1px solid #edf1ed; }
.upcoming-item:last-child { border-bottom: 0; }
.upcoming-date { background: #edf5ef; border-radius: 9px; padding: 7px 4px; text-align: center; color: #27664e; }
.upcoming-date b { font-size: 17px; display: block; line-height: 1.1; }
.upcoming-date small { font-size: 9px; }
.upcoming-detail { min-width: 0; }
.upcoming-detail b { display: block; font-size: 12px; overflow-wrap: anywhere; }
.upcoming-detail small { display: block; margin-top: 3px; color: var(--muted); font-size: 10px; overflow-wrap: anywhere; }
.upcoming-value { display: flex; align-items: flex-end; flex-direction: column; gap: 4px; white-space: nowrap; }
.upcoming-value b { font-size: 11px; }
.status { display: inline-block; padding: 4px 6px; border-radius: 100px; font-size: 9px; font-weight: 800; line-height: 1.1; text-transform: uppercase; white-space: nowrap; }
.status-realizado { color: #26734f; background: #e7f4eb; }
.status-previsto { color: #976514; background: #fff4da; }
.status-cancelado { color: #9e4b43; background: #ffebe7; }
.notice { border-radius: 9px; padding: 12px 14px; margin-bottom: 16px; font-size: 12px; }
.notice.error { background: #fff0ed; color: #963a30; border: 1px solid #f4d1ca; }
.notice.success { background: #e8f5ec; color: #216a4b; border: 1px solid #cde6d4; }
.notice.info { background: #edf5f2; color: #315b4c; border: 1px solid #d8e8df; margin-top: 16px; }
.filter-bar { background: #fff; border: 1px solid var(--line); border-radius: 11px; padding: 10px 12px; margin-bottom: 16px; }
.filter-bar label:not(:first-child) { margin-left: 8px; }
.form-panel { margin-bottom: 20px; }
.form-panel h2 { margin-bottom: 17px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.field { display: flex; flex-direction: column; min-width: 0; gap: 6px; font-size: 11px; font-weight: 750; color: #526459; }
.field small { font-weight: 450; }
.field-wide { grid-column: 1 / -1; }
.form-actions { grid-column: 1 / -1; display: flex; flex-wrap: wrap; gap: 8px; margin-top: 7px; }
.form-actions a { display: inline-flex; align-items: center; }
.helper-text { margin: 13px 0 0; font-size: 11px; }
.floating-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; }
.stack-list { display: grid; gap: 10px; }
.fixed-item { padding: 0; overflow: hidden; }
.fixed-item summary { list-style: none; cursor: pointer; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 17px; }
.fixed-item summary::-webkit-details-marker { display: none; }
.fixed-item summary > span:first-child b, .fixed-item summary small { display: block; }
.fixed-item summary small { color: var(--muted); font-size: 10px; margin-top: 4px; }
.summary-end { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; white-space: nowrap; }
.compact-form { padding: 2px 17px 17px; }
.action-stack { display: flex; flex-wrap: wrap; gap: 4px; min-width: 135px; }
.action-stack form { margin: 0; }
.text-button { border: 0; background: transparent; padding: 5px; cursor: pointer; font-size: 11px; font-weight: 750; }
.registration-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; }
.registration-grid .panel h2 { margin-bottom: 15px; }
.inline-form { display: flex; gap: 7px; align-items: center; }
.inline-form input { flex: 1; min-width: 0; }
.form-stack { display: grid; gap: 11px; }
.simple-list { display: grid; margin-top: 15px; }
.simple-list > div { padding: 9px 0; border-bottom: 1px solid #edf1ed; display: flex; gap: 10px; justify-content: space-between; align-items: center; font-size: 11px; }
.simple-list > div:last-child { border-bottom: 0; }
.simple-list span { overflow-wrap: anywhere; }
.simple-list small { display: block; font-size: 10px; color: var(--muted); margin-top: 3px; }
.simple-list b { white-space: nowrap; font-size: 11px; }
.summary-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 16px 0; }
.summary-grid .panel { min-width: 0; }
.backup-panel { margin-top: 15px; display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.backup-panel p { font-size: 12px; margin-bottom: 0; max-width: 660px; }
.backup-panel h2 { margin-bottom: 5px; }
.budget-cell { min-width: 95px; }
.budget-cell small { display: block; margin-top: 4px; }
.floating-actions .button { min-width: 120px; }
@media (max-width: 1020px) {
  .nav-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); padding: 8px 12px; }
  .nav-item { white-space: normal; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .content-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 680px) {
  .topbar { min-height: 65px; padding: 11px 14px; }
  .brand { font-size: 15px; }
  .brand-mark { width: 38px; height: 38px; }
  .nav-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 3px; padding: 7px 8px; }
  .nav-item { font-size: 10px; padding: 8px 2px; min-height: 34px; }
  .container { padding: 21px 12px 28px; }
  .page-head { flex-direction: column; align-items: stretch; gap: 13px; margin-bottom: 18px; }
  .page-head > .button { align-self: flex-start; }
  .month-form { align-self: stretch; box-shadow: none; flex-wrap: nowrap; }
  .month-form input { flex: 1; width: 100px; min-width: 0; }
  .month-form .button { padding: 9px 10px; }
  .metric-grid { gap: 9px; margin-bottom: 19px; }
  .metric { padding: 14px 12px 12px; border-radius: 11px; }
  .metric strong { font-size: 19px; }
  .metric > span { font-size: 10px; margin-bottom: 7px; }
  .metric small { font-size: 10px; }
  .metric-grid-two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .compare-grid, .chart-grid, .registration-grid, .summary-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .compare-card { padding: 13px; }
  .compare-card b { font-size: 18px; }
  .panel { padding: 14px; border-radius: 12px; }
  .chart-grid { gap: 10px; }
  .chart-wrap { height: 245px; }
  .panel-heading { align-items: flex-start; }
  .panel-heading h2 { font-size: 15px; }
  .section-heading { margin: 22px 0 11px; }
  .filter-bar { gap: 7px; }
  .filter-bar label:not(:first-child) { margin-left: 0; }
  .filter-bar input, .filter-bar select { flex: 1; min-width: 115px; }
  .form-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .field-wide { grid-column: auto; }
  .form-actions { grid-column: auto; }
  .fixed-item summary { padding: 13px; }
  .compact-form { padding: 0 13px 13px; }
  .upcoming-item { grid-template-columns: 38px minmax(0, 1fr) auto; gap: 7px; }
  .upcoming-detail b { font-size: 11px; }
  .upcoming-value b { font-size: 10px; }
  .status { font-size: 8px; padding: 4px 5px; }
  .backup-panel { flex-direction: column; align-items: flex-start; }
  .backup-panel .button { align-self: stretch; }
  .floating-actions { justify-content: stretch; }
  .floating-actions .button { flex: 1; min-width: 0; white-space: normal; }
  .table-wrap { margin-right: -3px; }
  table { min-width: 640px; }
  .summary-grid .panel { padding: 14px; }
}
@media (max-width: 380px) {
  .container { padding-left: 9px; padding-right: 9px; }
  .nav-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .top-date { font-size: 10px; }
  .metric { padding: 12px 9px; }
  .metric strong { font-size: 17px; }
  .metric small { overflow-wrap: anywhere; }
  .month-form { gap: 5px; padding: 7px; }
  .month-form label { display: none; }
  .month-form input { min-width: 0; }
  .upcoming-item { grid-template-columns: 34px minmax(0, 1fr); }
  .upcoming-value { grid-column: 2; flex-direction: row; align-items: center; justify-content: space-between; }
}

/* Cadastros editáveis e controle de poupança */
[hidden] { display: none !important; }
.registration-row { min-width: 0; }
.registration-edit-form { display: grid; grid-template-columns: minmax(0, 1fr) 84px auto; align-items: center; gap: 5px; min-width: 0; flex: 1; }
.registration-edit-form input, .registration-edit-form select { min-width: 0; width: 100%; padding: 7px 6px; font-size: 11px; }
.registration-row > form:not(.registration-edit-form) { flex: 0 0 auto; }
.category-row > span { min-width: 0; flex: 1; }
.compact-copy { margin: 10px 0 0; font-size: 10px; line-height: 1.5; }
.savings-account-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.savings-account-card { min-width: 0; }
.savings-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.savings-card-head h3 { margin: 3px 0 0; font-size: 16px; overflow-wrap: anywhere; }
.savings-balance { display: block; margin: 15px 0 3px; font-size: 25px; letter-spacing: -.04em; color: var(--ink); }
.interest-form { display: grid; gap: 9px; padding-top: 15px; margin-top: 12px; border-top: 1px solid var(--line); }
.account-actions { margin-top: 10px; }
.money-positive { color: #26734f; }
.money-negative { color: #a3443c; }
@media (max-width: 680px) {
  .savings-account-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .registration-edit-form { grid-template-columns: minmax(0, 1fr) 78px; }
  .registration-edit-form button { grid-column: 1 / -1; justify-self: start; }
  .people-row { align-items: start !important; }
  .savings-balance { font-size: 23px; }
}

.inactive-list { margin-top: 12px; font-size: 11px; color: var(--muted); }
.inactive-list summary { cursor: pointer; font-weight: 700; padding: 7px 0; }


/* Login, sessões e administração de usuários */
.top-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; min-width: 0; flex-wrap: wrap; }
.top-actions form { margin: 0; }
.top-action { display: inline-flex; align-items: center; justify-content: center; min-height: 30px; padding: 6px 9px; border: 1px solid rgba(220, 239, 226, .3); border-radius: 8px; color: #e4f1e8; background: transparent; font: inherit; font-size: 11px; font-weight: 650; cursor: pointer; white-space: nowrap; }
.top-action:hover { color: #fff; background: rgba(255,255,255,.09); }
.auth-body { min-height: 100vh; background: radial-gradient(circle at top, #e4eee7, #f5f7f4 56%); }
.auth-wrap { width: min(100% - 28px, 430px); margin: 0 auto; padding: clamp(28px, 8vh, 76px) 0 32px; }
.auth-brand { display: flex; gap: 12px; align-items: center; justify-content: center; color: var(--ink); margin-bottom: 22px; }
.auth-brand strong { display: block; font-size: 21px; letter-spacing: -.5px; }
.auth-brand small { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
.auth-panel { padding: 25px; box-shadow: 0 18px 55px rgba(31, 63, 48, .09); }
.auth-panel h1 { margin-bottom: 10px; }
.auth-panel > p { font-size: 12px; line-height: 1.6; }
.form-stack { display: grid; gap: 14px; }
.field { display: grid; gap: 6px; color: #3a5345; font-size: 12px; font-weight: 700; }
.field small { font-size: 10px; font-weight: 500; }
.auth-submit { width: 100%; margin-top: 4px; min-height: 44px; font-size: 13px; }
.auth-footnote { text-align: center; color: var(--muted); font-size: 10px !important; margin: 17px 0 0; }
.auth-secondary-form { text-align: center; margin-top: 15px; }
.auth-user-form { max-width: 820px; }
.auth-user-form .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.auth-user-form .form-actions { align-self: end; }
.notice { padding: 11px 13px; border-radius: 9px; margin: 12px 0 16px; font-size: 12px; line-height: 1.5; }
.notice.error { color: #8f312a; background: #fff0ed; border: 1px solid #f2d1ca; }
.notice.success { color: #286747; background: #e8f3ed; border: 1px solid #cee2d4; }
.text-button { border: 0; background: transparent; color: var(--green); cursor: pointer; font-weight: 700; padding: 6px; }
.text-button:hover { text-decoration: underline; }
@media (max-width: 680px) {
  .topbar { align-items: center; gap: 8px; }
  .top-actions { gap: 4px; }
  .top-action { padding: 5px 6px; font-size: 10px; }
  .top-actions .top-date { display: none; }
  .auth-panel { padding: 19px; }
  .auth-user-form .form-grid { grid-template-columns: minmax(0, 1fr); }
}

/* Novo shell visual: dark por padrão, com alternativa Material Light. */
:root {
  color-scheme: dark;
  --ink: #edf2f8;
  --green: #a3e635;
  --green-dark: #84cc16;
  --green-soft: rgba(163, 230, 53, .12);
  --paper: #0b0f14;
  --surface: #121923;
  --surface-raised: #18212d;
  --muted: #91a0b4;
  --line: #263241;
  --amber: #fbbf24;
  --red: #fb7185;
  --red-soft: rgba(251, 113, 133, .12);
  --shadow: 0 16px 40px rgba(0, 0, 0, .16);
  --sidebar-width: 76px;
  --chart-text: #8b9ab0;
  --chart-grid: #283444;
  --chart-income: #45d6a4;
  --chart-expense: #fb7185;
  --chart-accent: #a3e635;
  font-family: "Be Vietnam Pro", Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: var(--ink);
  background: var(--paper);
}
html[data-theme="light"] {
  color-scheme: light;
  --ink: #202939;
  --green: #4f46e5;
  --green-dark: #4338ca;
  --green-soft: #eef2ff;
  --paper: #f4f6fb;
  --surface: #ffffff;
  --surface-raised: #f8faff;
  --muted: #758096;
  --line: #e1e6f0;
  --amber: #b7791f;
  --red: #dc4862;
  --red-soft: #fff0f2;
  --shadow: 0 12px 32px rgba(38, 52, 79, .07);
  --chart-text: #758096;
  --chart-grid: #e6eaf2;
  --chart-income: #0ca678;
  --chart-expense: #e04f69;
  --chart-accent: #5b5ce2;
}
html, body { width: 100%; min-width: 320px; min-height: 100%; overflow-x: clip; }
body { margin: 0; background: var(--paper); color: var(--ink); font-size: 13px; line-height: 1.55; }
* { box-sizing: border-box; }
a { color: var(--green); transition: color .18s ease; }
a:hover { color: var(--green-dark); }
h1, h2, h3, h4, p { margin-top: 0; }
h1 { color: var(--ink); font-size: clamp(25px, 3vw, 34px); font-weight: 700; line-height: 1.2; letter-spacing: -.8px; margin-bottom: 8px; }
h2 { color: var(--ink); font-size: 16px; line-height: 1.35; font-weight: 650; letter-spacing: -.3px; margin-bottom: 9px; }
h3 { color: var(--ink); font-size: 14px; font-weight: 650; }
.muted { color: var(--muted) !important; }
.eyebrow { color: var(--green); font-size: 10px; font-weight: 800; letter-spacing: .16em; margin-bottom: 7px; }

/* Navegação lateral recolhida; desktop expande ao hover/foco e pode ser fixada. */
.nav-grid { display: none !important; }
.sidebar { position: fixed; inset: 0 auto 0 0; z-index: 60; display: flex; flex-direction: column; width: var(--sidebar-width); padding: 18px 11px 14px; overflow-x: hidden; overflow-y: auto; background: #101720; color: #93a1b5; border-right: 1px solid #202a37; transition: width .22s ease, transform .22s ease, box-shadow .22s ease; scrollbar-width: thin; scrollbar-color: #344155 transparent; }
html[data-theme="light"] .sidebar { background: #fff; color: #7c879d; border-right-color: #e4e8f0; }
.sidebar:hover, .sidebar:focus-within, html.sidebar-pinned .sidebar { width: 252px; box-shadow: 12px 0 40px rgba(0, 0, 0, .2); }
.sidebar-brand { display: flex; align-items: center; min-width: 230px; min-height: 48px; gap: 12px; padding: 2px 6px 17px; margin-bottom: 20px; border-bottom: 1px solid #263241; color: var(--ink); text-decoration: none; }
html[data-theme="light"] .sidebar-brand { border-bottom-color: #e6eaf2; }
.sidebar-brand:hover { color: var(--ink); }
.brand-mark { display: inline-grid; flex: 0 0 42px; width: 42px; height: 42px; place-items: center; border-radius: 14px; color: #101720; background: linear-gradient(145deg, #d9f99d, #45d6a4); box-shadow: 0 6px 18px rgba(69, 214, 164, .18); font-size: 13px; font-weight: 850; }
.brand-mark svg { width: 23px; height: 23px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.brand-copy { display: block; min-width: 0; opacity: 0; transform: translateX(-5px); transition: opacity .14s ease, transform .14s ease; white-space: nowrap; pointer-events: none; }
.brand-copy strong { display: block; font-size: 14px; line-height: 1.25; letter-spacing: -.35px; }
.brand-copy small { display: block; color: #75859a; font-size: 8px; letter-spacing: .13em; margin-top: 4px; }
.sidebar:hover .brand-copy, .sidebar:focus-within .brand-copy, html.sidebar-pinned .brand-copy { opacity: 1; transform: translateX(0); }
.sidebar-caption { padding: 0 10px 9px; color: #64748b; font-size: 8px; font-weight: 800; letter-spacing: .18em; white-space: nowrap; opacity: 0; transition: opacity .15s ease; }
.sidebar:hover .sidebar-caption, .sidebar:focus-within .sidebar-caption, html.sidebar-pinned .sidebar-caption { opacity: 1; }
.sidebar-nav { display: flex; flex-direction: column; gap: 5px; min-width: 230px; }
.nav-item { position: relative; display: flex; align-items: center; gap: 15px; width: 100%; min-height: 46px; padding: 0 13px; overflow: hidden; border: 1px solid transparent; border-radius: 12px; color: #91a0b4; background: transparent; font-size: 12px; font-weight: 600; text-align: left; text-decoration: none; white-space: nowrap; transition: background .18s ease, color .18s ease, border-color .18s ease; }
html[data-theme="light"] .nav-item { color: #7c879d; }
.nav-item:hover { color: var(--ink); background: rgba(148, 163, 184, .09); }
.nav-item.active { color: #d9f99d; background: linear-gradient(100deg, rgba(163, 230, 53, .15), rgba(69, 214, 164, .055)); border-color: rgba(163, 230, 53, .14); }
html[data-theme="light"] .nav-item.active { color: #4338ca; background: #eef2ff; border-color: #e0e7ff; }
.nav-item.active::before { content: ""; position: absolute; left: -1px; top: 10px; bottom: 10px; width: 3px; border-radius: 0 4px 4px 0; background: var(--green); }
.nav-icon { display: inline-grid; flex: 0 0 22px; width: 22px; height: 22px; place-items: center; }
.nav-icon svg { display: block; width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.65; stroke-linecap: round; stroke-linejoin: round; }
.nav-label { display: block; opacity: 0; transform: translateX(-4px); transition: opacity .12s ease, transform .12s ease; pointer-events: none; }
.sidebar:hover .nav-label, .sidebar:focus-within .nav-label, html.sidebar-pinned .nav-label { opacity: 1; transform: translateX(0); }
.sidebar-bottom { display: flex; align-items: center; gap: 11px; min-width: 230px; margin-top: auto; padding: 18px 13px 5px; border-top: 1px solid #263241; color: #8291a6; font-size: 10px; white-space: nowrap; }
html[data-theme="light"] .sidebar-bottom { border-top-color: #e6eaf2; }
.sidebar-status-dot, .footer-dot { display: inline-block; flex: 0 0 7px; width: 7px; height: 7px; border-radius: 50%; background: #45d6a4; box-shadow: 0 0 0 4px rgba(69, 214, 164, .1); }
.app-main { min-width: 0; min-height: 100vh; margin-left: var(--sidebar-width); display: flex; flex-direction: column; transition: margin-left .22s ease; }
html.sidebar-pinned .app-main { margin-left: 252px; }
.sidebar-overlay { display: none; }
.topbar { position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 17px; min-height: 78px; padding: 13px clamp(18px, 3vw, 42px); border-bottom: 1px solid var(--line); background: color-mix(in srgb, var(--surface) 92%, transparent); color: var(--ink); backdrop-filter: blur(18px); }
.menu-toggle { flex: 0 0 38px; }
.topbar-heading { display: flex; flex-direction: column; min-width: 0; line-height: 1.3; }
.topbar-overline { color: var(--muted); font-size: 8px; font-weight: 800; letter-spacing: .17em; margin-bottom: 4px; }
.topbar-heading strong { color: var(--ink); font-size: 14px; font-weight: 700; }
.top-actions { display: flex; align-items: center; justify-content: flex-end; gap: 9px; min-width: 0; flex-wrap: wrap; margin-left: auto; }
.top-date { display: inline-flex; align-items: center; gap: 7px; padding-right: 13px; border-right: 1px solid var(--line); color: var(--muted); font-size: 10px; white-space: nowrap; }
.top-date svg, .top-action svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.top-action { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 34px; padding: 5px 9px; border: 1px solid var(--line); border-radius: 10px; color: var(--ink); background: var(--surface-raised); font-size: 10px; font-weight: 650; text-decoration: none; cursor: pointer; white-space: nowrap; }
.top-action:hover { color: var(--ink); border-color: color-mix(in srgb, var(--green) 45%, var(--line)); }
.top-actions form { margin: 0; }
.user-avatar { display: inline-grid; width: 22px; height: 22px; place-items: center; border-radius: 8px; background: var(--green-soft); color: var(--green); font-size: 10px; font-weight: 800; }
.theme-toggle { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 34px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); color: var(--ink); font-size: 10px; font-weight: 650; cursor: pointer; }
.theme-toggle:hover { border-color: var(--green); }
.theme-toggle svg { width: 15px; height: 15px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.icon-button { display: inline-grid; width: 38px; height: 38px; place-items: center; padding: 0; border: 1px solid var(--line); border-radius: 11px; color: var(--ink); background: var(--surface); cursor: pointer; }
.icon-button:hover { background: var(--surface-raised); border-color: var(--green); }
.icon-button svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.container { width: 100%; max-width: 1700px; min-height: calc(100vh - 140px); margin: 0 auto; padding: clamp(18px, 2.4vw, 34px) clamp(17px, 3vw, 42px) 36px; }
.footer { display: flex; align-items: center; justify-content: center; gap: 9px; margin-top: auto; padding: 17px; color: var(--muted); font-size: 9px; }

/* Superfícies e componentes compartilhados entre todas as telas. */
.page-head { align-items: center; gap: 18px; margin-bottom: 24px; }
.page-head p { margin-bottom: 0; }
.headline-spark { color: var(--green); font-size: .8em; }
.month-form, .filter-bar { gap: 9px; border: 1px solid var(--line); border-radius: 13px; background: var(--surface); box-shadow: var(--shadow); }
.month-form { padding: 8px; }
.month-form label, .filter-bar label { color: var(--muted); font-size: 10px; font-weight: 650; }
input, select, textarea { width: 100%; min-width: 0; max-width: 100%; color: var(--ink); background: var(--surface-raised); border: 1px solid var(--line); border-radius: 9px; padding: 10px 11px; outline: 0; }
input::placeholder, textarea::placeholder { color: color-mix(in srgb, var(--muted) 78%, transparent); }
input:focus, select:focus, textarea:focus { border-color: var(--green); box-shadow: 0 0 0 3px color-mix(in srgb, var(--green) 14%, transparent); }
select option { color: var(--ink); background: var(--surface); }
.month-form input, .filter-bar input, .filter-bar select { width: auto; min-width: 130px; }
.button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; min-height: 38px; padding: 10px 15px; border: 1px solid var(--green); border-radius: 10px; background: var(--green); color: #101720; font-size: 11px; font-weight: 800; line-height: 1.2; text-align: center; text-decoration: none; white-space: nowrap; cursor: pointer; }
.button:hover { color: #101720; background: var(--green-dark); border-color: var(--green-dark); }
.button-light { color: var(--ink); border-color: var(--line); background: var(--surface-raised); }
.button-light:hover { color: var(--ink); background: var(--green-soft); border-color: color-mix(in srgb, var(--green) 40%, var(--line)); }
.button-danger { color: var(--red); border-color: color-mix(in srgb, var(--red) 25%, var(--line)); background: var(--red-soft); }
.button-danger:hover { color: #fff; background: var(--red); border-color: var(--red); }
.button-small { min-height: 31px; padding: 7px 10px; border-radius: 8px; font-size: 10px; }
.metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; margin-bottom: 24px; }
.metric-grid-two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.metric, .compare-card, .panel { min-width: 0; border: 1px solid var(--line); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow); }
.metric { padding: 18px 17px 15px; }
.metric > span { display: block; color: var(--muted); font-size: 10px; font-weight: 600; margin-bottom: 9px; }
.metric strong { display: block; color: var(--ink); font-size: clamp(19px, 2vw, 25px); font-weight: 750; letter-spacing: -.7px; overflow-wrap: anywhere; }
.metric small { display: block; margin-top: 8px; color: var(--muted); font-size: 10px; line-height: 1.5; }
.metric-good { border-top: 2px solid #45d6a4; }
.metric-danger { border-top: 2px solid var(--red); }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin: 25px 0 13px; }
.section-heading h2 { margin-bottom: 3px; }
.section-heading p { font-size: 11px; margin-bottom: 0; }
.compare-grid { gap: 13px; margin-bottom: 25px; }
.compare-card { padding: 15px 17px; }
.compare-card span, .compare-card small { display: block; color: var(--muted); font-size: 10px; }
.compare-card b { display: block; margin: 6px 0; color: var(--ink); font-size: 20px; }
.chart-grid { gap: 14px; }
.panel { padding: 19px; }
.chart-panel .muted { font-size: 10px; margin-bottom: 12px; }
.chart-wrap { position: relative; width: 100%; min-width: 0; height: 255px; }
.chart-wrap canvas { display: block; width: 100%; height: 100%; }
.content-grid { gap: 14px; }
.section-gap { margin-top: 20px; }
.panel-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.panel-heading h2 { margin-bottom: 4px; }
.panel-heading p { margin-bottom: 0; font-size: 10px; }
.text-link { color: var(--green); font-size: 10px; font-weight: 750; white-space: nowrap; }
.text-link:hover { color: var(--ink); }
.budget-list { display: grid; gap: 14px; }
.row-between { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 7px; color: var(--ink); font-size: 10px; }
.row-between strong { color: var(--ink); font-size: 10px; text-align: right; white-space: nowrap; }
.progress { height: 6px; background: var(--surface-raised); border-radius: 99px; overflow: hidden; }
.progress span { display: block; max-width: 100%; height: 100%; border-radius: 99px; background: var(--chart-income); }
.progress span.over { background: var(--red); }
.budget-row small { display: block; margin-top: 5px; font-size: 9px; }
.danger-text { color: var(--red) !important; }
.good-text { color: var(--chart-income) !important; }
.change { display: inline-block; font-size: 10px; font-weight: 750; }
.table-wrap { width: 100%; max-width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
table { width: 100%; border-collapse: collapse; font-size: 11px; text-align: left; }
th { color: var(--muted); background: var(--surface-raised); font-size: 9px; font-weight: 750; letter-spacing: .04em; text-transform: uppercase; }
th, td { padding: 12px 10px; border-bottom: 1px solid var(--line); vertical-align: middle; }
td { color: var(--ink); }
tbody tr:hover { background: color-mix(in srgb, var(--green) 4%, transparent); }
tbody tr:last-child td { border-bottom: 0; }
td.money, th.money { text-align: right; white-space: nowrap; font-weight: 750; }
tfoot th { color: var(--ink); font-size: 11px; text-transform: none; }
.subline { display: block; margin-top: 3px; color: var(--muted); font-size: 9px; line-height: 1.3; }
.empty-cell { padding: 30px 12px; color: var(--muted); text-align: center; }
.empty-state { padding: 20px; border: 1px dashed var(--line); border-radius: 12px; background: var(--surface-raised); color: var(--muted); font-size: 11px; line-height: 1.7; }
.empty-state a { font-weight: 750; }
.empty-hint { color: var(--muted); font-size: 11px; text-align: center; }
.upcoming-item { display: grid; grid-template-columns: 43px minmax(0, 1fr) auto; gap: 10px; align-items: center; padding: 11px 0; border-bottom: 1px solid var(--line); }
.upcoming-item:last-child { border-bottom: 0; }
.upcoming-date { padding: 7px 4px; border-radius: 9px; background: var(--green-soft); color: var(--green); text-align: center; }
.upcoming-date b { display: block; font-size: 17px; line-height: 1.1; }
.upcoming-date small { font-size: 9px; }
.upcoming-detail b { display: block; color: var(--ink); font-size: 11px; overflow-wrap: anywhere; }
.upcoming-detail small { display: block; margin-top: 3px; color: var(--muted); font-size: 9px; overflow-wrap: anywhere; }
.upcoming-value { display: flex; align-items: flex-end; flex-direction: column; gap: 4px; color: var(--ink); white-space: nowrap; }
.upcoming-value b { font-size: 10px; }
.status { display: inline-block; padding: 4px 6px; border-radius: 100px; font-size: 8px; font-weight: 800; line-height: 1.1; text-transform: uppercase; white-space: nowrap; }
.status-realizado { color: #45d6a4; background: rgba(69, 214, 164, .12); }
.status-previsto { color: #fbbf24; background: rgba(251, 191, 36, .12); }
.status-cancelado { color: var(--red); background: var(--red-soft); }
.notice { padding: 11px 13px; margin: 12px 0 16px; border: 1px solid var(--line); border-radius: 10px; font-size: 11px; }
.notice.error { color: var(--red); background: var(--red-soft); border-color: color-mix(in srgb, var(--red) 27%, var(--line)); }
.notice.success { color: var(--chart-income); background: color-mix(in srgb, var(--chart-income) 10%, var(--surface)); border-color: color-mix(in srgb, var(--chart-income) 22%, var(--line)); }
.notice.info { color: var(--muted); background: var(--surface-raised); border-color: var(--line); }
.filter-bar { display: flex; align-items: center; flex-wrap: wrap; padding: 10px 12px; margin-bottom: 16px; }
.filter-bar label:not(:first-child) { margin-left: 8px; }
.form-panel { margin-bottom: 20px; }
.form-panel h2 { margin-bottom: 17px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.field { display: flex; flex-direction: column; min-width: 0; gap: 6px; color: var(--muted); font-size: 10px; font-weight: 700; }
.field small { color: var(--muted); font-size: 9px; font-weight: 500; }
.field-wide { grid-column: 1 / -1; }
.form-actions { display: flex; grid-column: 1 / -1; flex-wrap: wrap; gap: 8px; margin-top: 7px; }
.form-actions a { display: inline-flex; align-items: center; }
.helper-text { margin: 13px 0 0; color: var(--muted); font-size: 10px; }
.floating-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.stack-list { display: grid; gap: 10px; }
.fixed-item { padding: 0; overflow: hidden; }
.fixed-item summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 15px 17px; list-style: none; cursor: pointer; }
.fixed-item summary::-webkit-details-marker { display: none; }
.fixed-item summary > span:first-child b, .fixed-item summary small { display: block; }
.fixed-item summary small { color: var(--muted); font-size: 9px; margin-top: 4px; }
.summary-end { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; color: var(--ink); white-space: nowrap; }
.compact-form { padding: 2px 17px 17px; }
.action-stack { display: flex; flex-wrap: wrap; gap: 4px; min-width: 135px; }
.action-stack form { margin: 0; }
.text-button { border: 0; background: transparent; color: var(--green); padding: 5px; font-size: 10px; font-weight: 750; cursor: pointer; }
.registration-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; align-items: start; }
.registration-grid .panel h2 { margin-bottom: 15px; }
.inline-form { display: flex; align-items: center; gap: 7px; }
.inline-form input { flex: 1; min-width: 0; }
.form-stack { display: grid; gap: 11px; }
.simple-list { display: grid; margin-top: 15px; }
.simple-list > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 0; border-bottom: 1px solid var(--line); color: var(--ink); font-size: 10px; }
.simple-list > div:last-child { border-bottom: 0; }
.simple-list span { overflow-wrap: anywhere; }
.simple-list small { display: block; margin-top: 3px; color: var(--muted); font-size: 9px; }
.simple-list b { color: var(--ink); font-size: 10px; white-space: nowrap; }
.summary-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin: 16px 0; }
.summary-grid .panel { min-width: 0; }
.backup-panel { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 15px; }
.backup-panel p { max-width: 660px; margin-bottom: 0; font-size: 11px; }
.backup-panel h2 { margin-bottom: 5px; }
.budget-cell { min-width: 95px; }
.budget-cell small { display: block; margin-top: 4px; }
.floating-actions .button { min-width: 120px; }
.auth-body { min-height: 100vh; padding: 0; background: radial-gradient(circle at 15% 0%, color-mix(in srgb, var(--green) 11%, var(--paper)), var(--paper) 46%); color: var(--ink); }
.auth-wrap { width: min(100% - 28px, 430px); margin: 0 auto; padding: clamp(28px, 8vh, 76px) 0 32px; }
.auth-brand { display: flex; align-items: center; justify-content: center; gap: 12px; margin-bottom: 22px; color: var(--ink); }
.auth-brand strong { display: block; font-size: 21px; letter-spacing: -.5px; }
.auth-brand small { display: block; margin-top: 2px; color: var(--muted); font-size: 12px; }
.auth-panel { padding: 25px; box-shadow: 0 18px 55px rgba(0, 0, 0, .18); }
.auth-panel h1 { margin-bottom: 10px; }
.auth-panel > p { font-size: 12px; line-height: 1.6; }
.auth-submit { width: 100%; min-height: 44px; margin-top: 4px; font-size: 13px; }
.auth-footnote { margin: 17px 0 0; color: var(--muted); font-size: 10px !important; text-align: center; }
.auth-secondary-form { margin-top: 15px; text-align: center; }
.auth-user-form { max-width: 820px; }
.auth-user-form .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.auth-user-form .form-actions { align-self: end; }
[hidden] { display: none !important; }
.registration-row { min-width: 0; }
.registration-edit-form { display: grid; grid-template-columns: minmax(0, 1fr) 84px auto; align-items: center; gap: 5px; min-width: 0; flex: 1; }
.registration-edit-form input, .registration-edit-form select { width: 100%; min-width: 0; padding: 7px 6px; font-size: 10px; }
.registration-row > form:not(.registration-edit-form) { flex: 0 0 auto; }
.category-row > span { flex: 1; min-width: 0; }
.compact-copy { margin: 10px 0 0; color: var(--muted); font-size: 9px; line-height: 1.5; }
.savings-account-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.savings-account-card { min-width: 0; }
.savings-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; }
.savings-card-head h3 { margin: 3px 0 0; color: var(--ink); font-size: 16px; overflow-wrap: anywhere; }
.savings-balance { display: block; margin: 15px 0 3px; color: var(--ink); font-size: 25px; letter-spacing: -.04em; }
.interest-form { display: grid; gap: 9px; padding-top: 15px; margin-top: 12px; border-top: 1px solid var(--line); }
.account-actions { margin-top: 10px; }
.money-positive { color: var(--chart-income); }
.money-negative { color: var(--red); }
.inactive-list { margin-top: 12px; color: var(--muted); font-size: 10px; }
.inactive-list summary { padding: 7px 0; font-weight: 700; cursor: pointer; }

/* Dashboard resumido com fluxo de caixa em linhas. */
.dashboard-head { margin-bottom: 20px; }
.dashboard-head .month-form { flex: 0 0 auto; }
.dashboard-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-bottom: 17px; }
.dashboard-metrics .metric { position: relative; overflow: hidden; padding: 17px 18px 15px; }
.dashboard-metrics .metric::after { content: ""; position: absolute; right: -22px; top: -30px; width: 100px; height: 100px; border-radius: 50%; background: currentColor; opacity: .035; pointer-events: none; }
.metric-income { color: var(--chart-income); }
.metric-expense { color: var(--chart-expense); }
.metric-balance { color: var(--chart-accent); }
.metric-label-row { display: flex; align-items: center; gap: 9px; margin-bottom: 12px; }
.metric-symbol { display: inline-grid; flex: 0 0 32px; width: 32px; height: 32px; place-items: center; border-radius: 10px; background: color-mix(in srgb, currentColor 12%, var(--surface)); color: inherit; }
.metric-symbol svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
.dashboard-metrics .metric-label-row .metric-label { margin: 0; color: var(--muted); font-size: 10px; font-weight: 700; }
.dashboard-metrics .metric > strong { color: var(--ink); font-size: clamp(20px, 2.2vw, 27px); }
.dashboard-metrics .metric > small { display: flex; align-items: center; gap: 7px; margin-top: 8px; color: var(--muted); font-size: 9px; }
.metric-dot { display: inline-block; flex: 0 0 5px; width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
.metric-comparison { margin-top: 9px; font-size: 9px; font-weight: 800; }
.metric-comparison span { color: var(--muted); font-weight: 500; }
.metric-comparison.up { color: var(--chart-income); }
.metric-comparison.down { color: var(--chart-expense); }
.cashflow-panel { padding: 20px 22px 15px; border-radius: 17px; }
.cashflow-heading { align-items: center; margin-bottom: 3px; }
.cashflow-heading h2 { margin-bottom: 3px; font-size: 18px; }
.cashflow-heading .eyebrow { margin-bottom: 5px; }
.chart-period { display: inline-flex; align-items: center; gap: 7px; padding: 6px 9px; border: 1px solid var(--line); border-radius: 9px; color: var(--muted); font-size: 9px; white-space: nowrap; }
.chart-status-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--chart-income); }
.cashflow-legend { display: flex; align-items: center; gap: 17px; margin-top: 15px; color: var(--muted); font-size: 10px; }
.cashflow-legend span { display: inline-flex; align-items: center; gap: 7px; }
.cashflow-legend i { display: inline-block; width: 19px; height: 3px; border-radius: 5px; }
.legend-income { background: var(--chart-income); }
.legend-expense { background: var(--chart-expense); }
.cashflow-chart-wrap { height: clamp(260px, 31vw, 360px); margin-top: 3px; }
.cashflow-footer { display: flex; align-items: stretch; justify-content: flex-start; gap: clamp(24px, 6vw, 72px); padding: 13px 2px 0; border-top: 1px solid var(--line); }
.cashflow-footer span { display: flex; flex-direction: column; gap: 4px; }
.cashflow-footer small { color: var(--muted); font-size: 9px; }
.cashflow-footer strong { color: var(--ink); font-size: 13px; }
.cashflow-footer .positive-value { color: var(--chart-income); }
.cashflow-footer .negative-value { color: var(--chart-expense); }
.dashboard-lower-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.dashboard-lower-grid .card-chart-panel { grid-column: 1 / -1; }
.dashboard-lower-grid .chart-wrap { height: 245px; }
.dashboard-lower-grid .panel-heading { margin-bottom: 8px; }

/* Cartões bancários: só armazenamos e mostramos os quatro últimos dígitos. */
.wallet-section { margin-top: 4px; }
.wallet-section .section-heading { margin-top: 0; }
.wallet-count, .invoice-item-count { color: var(--muted); font-size: 9px; white-space: nowrap; }
.bank-card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 15px; }
.bank-card { position: relative; isolation: isolate; display: flex; flex-direction: column; justify-content: space-between; min-width: 0; min-height: 190px; aspect-ratio: 1.68 / 1; overflow: hidden; padding: 17px 18px 15px; border: 1px solid rgba(255,255,255,.12); border-radius: 17px; color: #fff; box-shadow: 0 13px 28px rgba(0,0,0,.2); }
.bank-card::before { content: ""; position: absolute; z-index: -1; width: 185px; height: 185px; right: -54px; top: -70px; border-radius: 50%; border: 1px solid rgba(255,255,255,.16); box-shadow: 0 0 0 19px rgba(255,255,255,.035), 0 0 0 39px rgba(255,255,255,.025); }
.bank-card::after { content: ""; position: absolute; z-index: -1; inset: 0; background: linear-gradient(125deg, rgba(255,255,255,.12), transparent 40%, rgba(0,0,0,.16)); pointer-events: none; }
.bank-card-nubank { background: linear-gradient(135deg, #820ad1 0%, #5d20a6 50%, #32105d 100%); }
.bank-card-santander { background: linear-gradient(135deg, #30333a 0%, #101216 57%, #050607 100%); }
.bank-card-bradesco { background: linear-gradient(135deg, #f52248 0%, #be092d 56%, #7f0925 100%); }
.bank-card-ticket { background: linear-gradient(135deg, #25bd73 0%, #10834b 54%, #075435 100%); }
.bank-card-clear { background: linear-gradient(135deg, #2788ff 0%, #1551c7 55%, #132d70 100%); }
.bank-card-generic { background: linear-gradient(135deg, #4958d6 0%, #242b68 55%, #151933 100%); }
.bank-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.bank-card-issuer { font-size: 17px; line-height: 1.15; font-weight: 800; letter-spacing: -.55px; }
.bank-card-kind { padding: 4px 6px; border: 1px solid rgba(255,255,255,.27); border-radius: 6px; background: rgba(255,255,255,.11); font-size: 7px; font-weight: 800; letter-spacing: .07em; text-align: center; }
.bank-card-chip { display: grid; grid-template-columns: repeat(2, 10px); grid-template-rows: repeat(2, 9px); width: 23px; height: 20px; overflow: hidden; border: 1px solid rgba(255,255,255,.52); border-radius: 5px; background: linear-gradient(135deg, #f4df9b, #b99e5c); }
.bank-card-chip span { border: .5px solid rgba(74, 61, 34, .36); }
.bank-card-number { margin-top: 4px; color: rgba(255,255,255,.92); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: clamp(11px, 1.08vw, 14px); letter-spacing: .045em; white-space: nowrap; }
.bank-card-number strong { color: #fff; font-weight: 800; }
.bank-card-foot { display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; min-width: 0; }
.bank-card-foot > div { display: flex; flex-direction: column; min-width: 0; gap: 3px; }
.bank-card-foot small { color: rgba(255,255,255,.65); font-size: 6px; font-weight: 800; letter-spacing: .14em; }
.bank-card-foot strong { display: block; max-width: 155px; overflow: hidden; color: #fff; font-size: 9px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.bank-card-label { text-align: right; }
.bank-card-label strong { max-width: 120px; }
.invoice-section { min-width: 0; }
.invoice-section .section-heading { margin-bottom: 13px; }
.invoice-filter { display: flex; align-items: center; gap: 10px; }
.invoice-filter select { flex: 1; min-width: 180px; }
.invoice-summary { display: grid; grid-template-columns: minmax(0, .85fr) minmax(0, 1.15fr); gap: 14px; margin: 16px 0; }
.invoice-card-mini { min-width: 0; }
.invoice-card-mini .bank-card { width: 100%; min-height: 190px; height: 100%; }
.invoice-total-metric { display: flex; flex-direction: column; justify-content: center; }
.invoice-total-metric .invoice-meta { display: flex; gap: 10px; margin-top: 13px; }
.invoice-meta span { padding: 5px 7px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); font-size: 9px; }
.invoice-table-panel { margin-top: 15px; }
.registration-card-list { display: grid; gap: 13px; margin-top: 16px; }
.registration-card-entry { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; align-items: center; padding: 10px; border: 1px solid var(--line); border-radius: 13px; background: var(--surface-raised); }
.registration-card-visual { min-width: 0; }
.registration-card-visual .bank-card { min-height: 145px; padding: 12px; border-radius: 12px; }
.registration-card-visual .bank-card-issuer { font-size: 14px; }
.registration-card-visual .bank-card-kind { font-size: 6px; }
.registration-card-visual .bank-card-number { font-size: 10px; }
.registration-card-edit { display: grid; gap: 13px; min-width: 0; }
.registration-card-edit > div strong { display: block; color: var(--ink); font-size: 11px; }
.registration-card-edit > div small { display: block; margin-top: 4px; color: var(--muted); font-size: 9px; line-height: 1.5; }
.last-four-form { display: flex; align-items: flex-end; gap: 8px; }
.last-four-form .field { flex: 1; }
.last-four-form input { padding: 8px; }

@media (max-width: 1180px) {
  .bank-card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metric-grid:not(.dashboard-metrics) { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .content-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 900px) {
  .top-date { display: none; }
  .registration-grid { grid-template-columns: minmax(0, 1fr); }
  .registration-card-entry { grid-template-columns: minmax(0, .95fr) minmax(0, 1.05fr); }
}
@media (max-width: 760px) {
  :root { --sidebar-width: 0px; }
  .sidebar { width: 260px; max-width: calc(100vw - 54px); transform: translateX(-105%); padding: 17px 12px; box-shadow: none; }
  .sidebar:hover, .sidebar:focus-within, html.sidebar-pinned .sidebar { width: 260px; }
  .brand-copy, .sidebar-caption, .nav-label { opacity: 1; transform: none; }
  .sidebar-overlay { position: fixed; inset: 0; z-index: 55; display: block; width: 100%; height: 100%; padding: 0; border: 0; background: rgba(0,0,0,.55); opacity: 0; visibility: hidden; pointer-events: none; transition: opacity .2s ease, visibility .2s ease; }
  html.sidebar-open .sidebar { transform: translateX(0); box-shadow: 18px 0 50px rgba(0,0,0,.3); }
  html.sidebar-open .sidebar-overlay { opacity: 1; visibility: visible; pointer-events: auto; }
  .app-main, html.sidebar-pinned .app-main { margin-left: 0; }
  .topbar { min-height: 67px; gap: 10px; padding: 10px 13px; }
  .menu-toggle { width: 36px; height: 36px; flex-basis: 36px; }
  .topbar-overline { font-size: 7px; }
  .topbar-heading strong { font-size: 12px; }
  .top-actions { gap: 6px; }
  .theme-toggle { width: 35px; min-height: 35px; padding: 0; }
  .theme-toggle .theme-text { display: none; }
  .user-chip { padding: 4px; }
  .user-name { display: none; }
  .top-action { min-height: 34px; padding: 5px 7px; }
  .logout-action span, .admin-shortcut { display: none; }
  .container { min-height: calc(100vh - 115px); padding: 20px 13px 28px; }
  .page-head { flex-direction: column; align-items: stretch; gap: 13px; margin-bottom: 18px; }
  .page-head > .button { align-self: flex-start; }
  .month-form { align-self: stretch; flex-wrap: nowrap; box-shadow: none; }
  .month-form input { flex: 1; width: 100px; min-width: 0; }
  .month-form .button { padding: 9px 10px; }
  .dashboard-head .month-form { align-self: stretch; }
  .metric-grid, .metric-grid:not(.dashboard-metrics) { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; margin-bottom: 16px; }
  .dashboard-metrics { grid-template-columns: minmax(0, 1fr); }
  .dashboard-metrics .metric { padding: 14px 13px 12px; }
  .dashboard-metrics .metric-label-row { margin-bottom: 8px; }
  .dashboard-metrics .metric > strong { font-size: 23px; }
  .metric { padding: 13px 11px; border-radius: 12px; }
  .metric strong { font-size: 18px; }
  .metric > span { font-size: 9px; margin-bottom: 7px; }
  .metric small { font-size: 9px; }
  .metric-grid-two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .compare-grid, .chart-grid, .registration-grid, .summary-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .compare-card { padding: 13px; }
  .compare-card b { font-size: 18px; }
  .panel { padding: 14px; border-radius: 13px; }
  .cashflow-panel { padding: 15px 12px 12px; }
  .cashflow-heading { align-items: flex-start; }
  .cashflow-heading h2 { font-size: 16px; }
  .cashflow-legend { margin-top: 12px; }
  .cashflow-chart-wrap { height: 260px; }
  .cashflow-footer { gap: 15px; }
  .cashflow-footer strong { font-size: 11px; }
  .dashboard-lower-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .dashboard-lower-grid .card-chart-panel { grid-column: auto; }
  .dashboard-lower-grid .chart-wrap { height: 235px; }
  .chart-wrap { height: 235px; }
  .panel-heading { align-items: flex-start; }
  .panel-heading h2 { font-size: 14px; }
  .section-heading { margin: 22px 0 11px; }
  .filter-bar { gap: 7px; }
  .filter-bar label:not(:first-child) { margin-left: 0; }
  .filter-bar input, .filter-bar select { flex: 1; min-width: 115px; }
  .form-grid { grid-template-columns: minmax(0, 1fr); gap: 12px; }
  .field-wide { grid-column: auto; }
  .form-actions { grid-column: auto; }
  .fixed-item summary { padding: 13px; }
  .compact-form { padding: 0 13px 13px; }
  .upcoming-item { grid-template-columns: 38px minmax(0, 1fr) auto; gap: 7px; }
  .upcoming-detail b { font-size: 10px; }
  .upcoming-value b { font-size: 9px; }
  .status { font-size: 7px; padding: 4px 5px; }
  .backup-panel { flex-direction: column; align-items: flex-start; }
  .backup-panel .button { align-self: stretch; }
  .floating-actions { justify-content: stretch; }
  .floating-actions .button { flex: 1; min-width: 0; white-space: normal; }
  .table-wrap { margin-right: -3px; }
  table { min-width: 640px; }
  .summary-grid .panel { padding: 14px; }
  .savings-account-grid { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .registration-edit-form { grid-template-columns: minmax(0, 1fr) 78px; }
  .registration-edit-form button { grid-column: 1 / -1; justify-self: start; }
  .people-row { align-items: start !important; }
  .savings-balance { font-size: 23px; }
  .bank-card-grid { grid-template-columns: minmax(0, 1fr); gap: 11px; }
  .bank-card { min-height: 190px; }
  .invoice-filter { display: grid; grid-template-columns: minmax(0, 1fr); }
  .invoice-filter label:not(:first-child) { margin-left: 0; }
  .invoice-filter input, .invoice-filter select { width: 100%; min-width: 0; }
  .invoice-summary { grid-template-columns: minmax(0, 1fr); }
  .invoice-card-mini { max-width: 420px; width: 100%; }
  .invoice-total-metric { min-height: 165px; }
  .registration-card-entry { grid-template-columns: minmax(0, 1fr); }
  .registration-card-visual .bank-card { min-height: 185px; padding: 15px 17px; }
  .registration-card-visual .bank-card-issuer { font-size: 17px; }
  .registration-card-visual .bank-card-number { font-size: 13px; }
  .registration-card-edit { padding: 2px 4px 4px; }
  .last-four-form { align-items: flex-end; }
  .auth-user-form .form-grid { grid-template-columns: minmax(0, 1fr); }
}
@media (max-width: 380px) {
  .container { padding-left: 9px; padding-right: 9px; }
  .topbar { gap: 7px; padding-left: 9px; padding-right: 9px; }
  .topbar-heading strong { font-size: 11px; }
  .top-actions { gap: 4px; }
  .theme-toggle, .top-action, .menu-toggle { width: 32px; height: 32px; min-height: 32px; }
  .metric-grid, .metric-grid:not(.dashboard-metrics) { grid-template-columns: minmax(0, 1fr); }
  .dashboard-metrics .metric > strong { font-size: 22px; }
  .month-form { gap: 5px; padding: 7px; }
  .month-form label { display: none; }
  .month-form input { min-width: 0; }
  .upcoming-item { grid-template-columns: 34px minmax(0, 1fr); }
  .upcoming-value { grid-column: 2; flex-direction: row; align-items: center; justify-content: space-between; }
  .cashflow-chart-wrap { height: 235px; }
  .cashflow-footer { flex-wrap: wrap; }
  .bank-card { padding: 15px; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
```

## `app/static/js/app.js`

```javascript
(() => {
  const root = document.documentElement;
  const body = document.body;
  const themeButton = document.getElementById('theme-toggle');
  const themeText = themeButton?.querySelector('.theme-text');
  const themeIcon = themeButton?.querySelector('.theme-icon');
  const sidebar = document.getElementById('app-sidebar');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebarOverlay = document.getElementById('sidebar-overlay');

  function applyTheme(theme) {
    const next = theme === 'light' ? 'light' : 'dark';
    root.dataset.theme = next;
    try { localStorage.setItem('casa-theme', next); } catch (_) { /* Tema continua funcionando sem armazenamento local. */ }
    if (themeText) themeText.textContent = next === 'dark' ? 'Material Light' : 'Tema escuro';
    if (themeIcon) {
      themeIcon.innerHTML = next === 'dark'
        ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>'
        : '<path d="M20.5 15.5A8.5 8.5 0 0 1 8.5 3.5 8.5 8.5 0 1 0 20.5 15.5Z"/>';
    }
    themeButton?.setAttribute('aria-label', next === 'dark' ? 'Mudar para Material Light' : 'Mudar para tema Dark');
    // Aguarda o CSS trocar as cores antes de redesenhar os gráficos em canvas.
    window.setTimeout(renderCharts, 30);
  }

  themeButton?.addEventListener('click', () => applyTheme(root.dataset.theme === 'dark' ? 'light' : 'dark'));

  function mobileMenu() { return window.matchMedia('(max-width: 760px)').matches; }
  function setSidebarOpen(open) {
    root.classList.toggle('sidebar-open', open && mobileMenu());
    if (sidebarToggle) {
      sidebarToggle.setAttribute('aria-expanded', String(open));
      sidebarToggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
    }
    if (sidebarOverlay) sidebarOverlay.tabIndex = open && mobileMenu() ? 0 : -1;
  }
  sidebarToggle?.addEventListener('click', () => {
    if (mobileMenu()) setSidebarOpen(!root.classList.contains('sidebar-open'));
    else {
      const pinned = root.classList.toggle('sidebar-pinned');
      try { localStorage.setItem('casa-sidebar-pinned', pinned ? '1' : '0'); } catch (_) { /* Preferência opcional. */ }
      sidebarToggle.setAttribute('aria-expanded', String(pinned));
      sidebarToggle.setAttribute('aria-label', pinned ? 'Recolher menu' : 'Fixar menu expandido');
    }
  });
  sidebarOverlay?.addEventListener('click', () => setSidebarOpen(false));
  sidebar?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setSidebarOpen(false)));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') setSidebarOpen(false); });
  try {
    if (localStorage.getItem('casa-sidebar-pinned') === '1' && !mobileMenu()) root.classList.add('sidebar-pinned');
  } catch (_) { /* Preferência opcional. */ }
  window.addEventListener('resize', () => { if (!mobileMenu()) setSidebarOpen(false); });

  function renderCharts() {
    const dataNode = document.getElementById('chart-data');
    if (!dataNode || !window.FamilyCharts) return;
    try { window.FamilyCharts.render(JSON.parse(dataNode.textContent)); }
    catch (error) { console.error('Não foi possível renderizar os gráficos locais.', error); }
  }
  document.addEventListener('DOMContentLoaded', renderCharts);
  let resizeTimer;
  window.addEventListener('resize', () => {
    window.clearTimeout(resizeTimer);
    resizeTimer = window.setTimeout(renderCharts, 140);
  });
  applyTheme(root.dataset.theme || 'dark');
})();
```

## `app/static/js/htmx-lite.js`

```javascript
/* Adaptador mínimo para os atributos hx-get/hx-trigger/hx-swap usados neste projeto. */
(() => {
  async function loadElement(element) {
    const url = element.getAttribute("hx-get");
    if (!url) return;
    try {
      const response = await fetch(url, { headers: { "HX-Request": "true" } });
      if (!response.ok) throw new Error("Falha ao carregar conteúdo");
      const html = await response.text();
      if ((element.getAttribute("hx-swap") || "innerHTML") === "innerHTML") element.innerHTML = html;
    } catch (_) { element.innerHTML = '<p class="muted">Não foi possível carregar esta seção.</p>'; }
  }
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("[hx-get]").forEach(element => {
      const trigger = element.getAttribute("hx-trigger") || "load";
      if (trigger.split(" ").includes("load")) loadElement(element);
    });
  });
  window.htmx = { ajax: (_method, url, options = {}) => fetch(url).then(r => r.text()).then(html => { if (options.target) document.querySelector(options.target).innerHTML = html; }) };
})();
```

## `app/static/js/local-charts.js`

```javascript
/* Gráficos locais em canvas; sem CDN ou requisições externas. */
(() => {
  const palette = ['#a3e635', '#fb7185', '#60a5fa', '#c084fc', '#fbbf24', '#2dd4bf', '#f472b6', '#a3a3a3', '#818cf8', '#34d399'];
  const money = cents => (Number(cents || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const shortMoney = cents => {
    const value = Math.abs(Number(cents || 0)) / 100;
    if (value >= 1000000) return `${(value / 1000000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mi`;
    if (value >= 1000) return `${(value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} mil`;
    return `${Math.round(value).toLocaleString('pt-BR')}`;
  };
  const colors = () => {
    const style = getComputedStyle(document.documentElement);
    return {
      text: style.getPropertyValue('--chart-text').trim() || '#91a0b7',
      grid: style.getPropertyValue('--chart-grid').trim() || '#293548',
      surface: style.getPropertyValue('--surface').trim() || '#151c27',
      ink: style.getPropertyValue('--ink').trim() || '#e9eef7',
      income: style.getPropertyValue('--chart-income').trim() || '#45d6a4',
      expense: style.getPropertyValue('--chart-expense').trim() || '#fb7185',
      accent: style.getPropertyValue('--chart-accent').trim() || '#a3e635',
    };
  };
  const shorten = (text, size = 12) => String(text ?? '').length > size ? String(text).slice(0, size - 1) + '…' : String(text ?? '');

  function setup(canvas) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(240, Math.floor(rect.width || 340));
    const height = Math.max(210, Math.floor(rect.height || 260));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext('2d'); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const c = colors();
    ctx.font = '11px system-ui, sans-serif'; ctx.fillStyle = c.text; ctx.strokeStyle = c.grid;
    return { ctx, width, height, c };
  }

  function drawLegend(ctx, items, x, y, maxWidth, textColor) {
    let cx = x, cy = y;
    items.forEach(item => {
      const needed = 22 + Math.min(138, ctx.measureText(String(item.label || '')).width);
      if (cx + needed > x + maxWidth && cx !== x) { cx = x; cy += 18; }
      ctx.fillStyle = item.color; ctx.fillRect(cx, cy - 8, 9, 9);
      ctx.fillStyle = textColor; ctx.textAlign = 'left'; ctx.fillText(shorten(item.label, 21), cx + 14, cy);
      cx += needed + 8;
    });
  }

  function axes(ctx, width, plot, max, min, c) {
    ctx.strokeStyle = c.grid; ctx.fillStyle = c.text; ctx.font = '10px system-ui'; ctx.textAlign = 'right';
    const range = max - min || 1;
    for (let i = 0; i <= 4; i++) {
      const y = plot.top + plot.height * i / 4;
      ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke();
      const value = max - range * i / 4;
      const prefix = value < -0.5 ? '−' : '';
      ctx.fillText(`${prefix}${shortMoney(value)}`, plot.left - 7, y + 3);
    }
  }

  function drawPie(canvas, payload) {
    const { ctx, width, height, c } = setup(canvas); const values = payload.data || []; const labels = payload.labels || [];
    const total = values.reduce((a, b) => a + Number(b), 0);
    if (!total) return false;
    const cx = width / 2, cy = height * 0.30, radius = Math.min(width * 0.30, height * 0.27);
    let angle = -Math.PI / 2;
    values.forEach((v, i) => {
      const next = angle + Math.PI * 2 * Number(v) / total;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, radius, angle, next); ctx.closePath();
      ctx.fillStyle = palette[i % palette.length]; ctx.fill(); angle = next;
    });
    ctx.beginPath(); ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2); ctx.fillStyle = c.surface; ctx.fill();
    ctx.textAlign = 'center'; ctx.fillStyle = c.ink; ctx.font = '700 13px system-ui'; ctx.fillText(shortMoney(total), cx, cy + 4);
    ctx.textAlign = 'left'; ctx.font = '10px system-ui';
    const legendItems = labels.map((label, i) => ({ label: `${label}: ${money(values[i])}`, color: palette[i % palette.length] }));
    const colWidth = width > 430 ? width / 2 - 14 : width - 22; const startY = height * 0.62;
    legendItems.slice(0, 8).forEach((item, i) => {
      const col = width > 430 ? i % 2 : 0; const row = width > 430 ? Math.floor(i / 2) : i;
      const y = startY + row * 16;
      ctx.fillStyle = item.color; ctx.fillRect(10 + col * (colWidth + 8), y - 8, 8, 8);
      ctx.fillStyle = c.text; ctx.fillText(shorten(item.label, width > 430 ? 35 : 31), 23 + col * (colWidth + 8), y);
    });
    return true;
  }

  function drawBars(canvas, labels, series, stacked = false) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 48, right: 10, top: 17, bottom: 43 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    let max = 0;
    labels.forEach((_, i) => { const vals = series.map(s => Number(s.data[i] || 0)); max = Math.max(max, stacked ? vals.reduce((a, b) => a + b, 0) : Math.max(0, ...vals)); });
    max = max || 100; axes(ctx, width, plot, max * 1.08, 0, c);
    const groupWidth = plot.width / labels.length; const inner = groupWidth * .72; const barWidth = Math.max(2, inner / (stacked ? 1 : Math.max(1, series.length)) - 3);
    labels.forEach((label, i) => {
      let stackedHeight = 0;
      series.forEach((s, j) => {
        const val = Number(s.data[i] || 0); const h = val / (max * 1.08) * plot.height;
        const x = plot.left + i * groupWidth + (groupWidth - inner) / 2 + (stacked ? 0 : j * (barWidth + 3));
        const y = plot.top + plot.height - (stacked ? stackedHeight + h : h);
        ctx.fillStyle = s.color || palette[j % palette.length]; ctx.beginPath();
        const radius = Math.min(4, barWidth / 2); ctx.roundRect(x, y, barWidth, Math.max(0, h), radius); ctx.fill();
        if (stacked) stackedHeight += h;
      });
      ctx.save(); ctx.translate(plot.left + i * groupWidth + groupWidth / 2, height - 22); ctx.rotate(labels.length > 8 ? -0.50 : 0);
      ctx.textAlign = labels.length > 8 ? 'right' : 'center'; ctx.fillStyle = c.text; ctx.fillText(shorten(label, 9), 0, 0); ctx.restore();
    });
    drawLegend(ctx, series.map((s, i) => ({ label: s.label, color: s.color || palette[i % palette.length] })), plot.left, height - 4, plot.width, c.text);
  }

  function drawLine(canvas, labels, values) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas); if (!labels || !labels.length || !values?.length) return;
    const plot = { left: 48, right: 12, top: 18, bottom: 36 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
    axes(ctx, width, plot, max, min, c);
    const point = (v, i) => ({ x: plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)), y: plot.top + (max - v) / range * plot.height });
    ctx.beginPath(); values.forEach((v, i) => { const p = point(v, i); i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y); });
    ctx.strokeStyle = c.accent; ctx.lineWidth = 2.5; ctx.lineJoin = 'round'; ctx.stroke();
    values.forEach((v, i) => { const p = point(v, i); ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fillStyle = c.accent; ctx.fill(); });
    labels.forEach((label, i) => { const p = point(values[i], i); ctx.fillStyle = c.text; ctx.textAlign = 'center'; ctx.fillText(shorten(label, 9), p.x, height - 15); });
  }

  // Duas curvas compartilham a escala; quando entradas/saídas variam, as linhas cruzam visualmente.
  function drawCashflow(canvas, labels, incomes, expenses) {
    if (!canvas) return;
    const { ctx, width, height, c } = setup(canvas);
    if (!labels?.length) return;
    const maxValue = Math.max(1, ...incomes.map(Number), ...expenses.map(Number));
    const plot = { left: 58, right: 18, top: 24, bottom: 42 };
    plot.width = Math.max(1, width - plot.left - plot.right); plot.height = Math.max(1, height - plot.top - plot.bottom);
    axes(ctx, width, plot, maxValue * 1.08, 0, c);
    const xAt = i => plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1));
    const yAt = value => plot.top + plot.height - (Number(value || 0) / (maxValue * 1.08)) * plot.height;
    const series = [
      { label: 'Entradas', data: incomes || [], color: c.income },
      { label: 'Saídas', data: expenses || [], color: c.expense },
    ];
    series.forEach(s => {
      const points = labels.map((_, i) => ({ x: xAt(i), y: yAt(s.data[i] || 0) }));
      if (!points.length) return;
      ctx.beginPath(); ctx.moveTo(points[0].x, points[0].y);
      for (let i = 1; i < points.length; i++) {
        const prev = points[i - 1], current = points[i], midX = (prev.x + current.x) / 2;
        ctx.bezierCurveTo(midX, prev.y, midX, current.y, current.x, current.y);
      }
      ctx.strokeStyle = s.color; ctx.lineWidth = 3; ctx.lineCap = 'round'; ctx.lineJoin = 'round'; ctx.stroke();
      points.forEach(point => { ctx.beginPath(); ctx.arc(point.x, point.y, 3, 0, Math.PI * 2); ctx.fillStyle = s.color; ctx.fill(); });
    });
    labels.forEach((label, i) => {
      ctx.fillStyle = c.text; ctx.font = '10px system-ui'; ctx.textAlign = 'center';
      ctx.fillText(shorten(label, 8), xAt(i), height - 17);
    });
  }

  window.FamilyCharts = {
    render(payload) {
      const pie = document.getElementById('chart-pie');
      if (pie) { const ok = drawPie(pie, payload.pie || {}); const empty = document.getElementById('pie-empty'); if (empty) empty.hidden = ok; }
      const cashflow = document.getElementById('chart-cashflow');
      const lineData = payload.cashflow || payload.bars || {};
      if (cashflow) drawCashflow(cashflow, lineData.labels || [], lineData.income || [], lineData.expense || []);
      const bars = document.getElementById('chart-bars');
      if (bars) drawBars(bars, payload.bars?.labels || [], [
        { label: 'Entradas', data: payload.bars?.income || [], color: colors().income },
        { label: 'Saídas', data: payload.bars?.expense || [], color: colors().expense },
      ]);
      const line = document.getElementById('chart-line'); if (line) drawLine(line, payload.line?.labels || [], payload.line?.data || []);
      const cards = document.getElementById('chart-cards');
      if (cards) drawBars(cards, payload.cards?.labels || [], (payload.cards?.datasets || []).map((s, i) => ({ ...s, color: palette[i % palette.length] })), true);
    }
  };
})();
```

## `app/templates/base.html`

```html
<!doctype html>
<html lang="pt-BR" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0b0f14">
  <title>{% block title %}Finanças da Família{% endblock %}</title>
  <script>try{document.documentElement.dataset.theme=localStorage.getItem('casa-theme')||'dark'}catch(e){}</script>
  <link rel="stylesheet" href="/static/css/app.css">
  <script defer src="/static/js/htmx-lite.js"></script>
  <script defer src="/static/js/local-charts.js"></script>
  <script defer src="/static/js/app.js"></script>
</head>
<body>
  <aside class="sidebar" id="app-sidebar" aria-label="Menu principal">
    <a class="sidebar-brand" href="/" aria-label="Casa em Ordem — página inicial">
      <span class="brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/><path d="M9.5 10.5h5"/></svg></span>
      <span class="brand-copy"><strong>Casa em Ordem</strong><small>FINANÇAS DA FAMÍLIA</small></span>
    </a>
    <div class="sidebar-caption">MENU PRINCIPAL</div>
    <nav class="sidebar-nav" aria-label="Navegação principal">
      <a class="nav-item {% if active_nav == 'dashboard' %}active{% endif %}" href="/" title="Visão geral" {% if active_nav == 'dashboard' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="5" rx="2"/><rect x="13" y="10" width="8" height="11" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/></svg></span><span class="nav-label">Visão geral</span></a>
      <a class="nav-item {% if active_nav == 'transacoes' %}active{% endif %}" href="/transacoes" title="Gastos" {% if active_nav == 'transacoes' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M7 7h13m0 0-4-4m4 4-4 4M17 17H4m0 0 4-4m-4 4 4 4"/></svg></span><span class="nav-label">Gastos</span></a>
      <a class="nav-item {% if active_nav == 'fixos' %}active{% endif %}" href="/transacoes/fixos" title="Gastos fixos" {% if active_nav == 'fixos' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18M8 14h3m-3 3h6"/></svg></span><span class="nav-label">Gastos fixos</span></a>
      <a class="nav-item {% if active_nav == 'planejados' %}active{% endif %}" href="/planejados" title="Planejados" {% if active_nav == 'planejados' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18"/><circle cx="12" cy="12" r="9"/></svg></span><span class="nav-label">Planejados</span></a>
      <a class="nav-item {% if active_nav == 'receitas' %}active{% endif %}" href="/receitas" title="Receitas" {% if active_nav == 'receitas' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M12 19V5m-6 6 6-6 6 6"/><path d="M4 21h16"/></svg></span><span class="nav-label">Receitas</span></a>
      <a class="nav-item {% if active_nav == 'cartoes' %}active{% endif %}" href="/cartoes" title="Cartões e faturas" {% if active_nav == 'cartoes' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><rect x="2.5" y="4" width="19" height="16" rx="3"/><path d="M3 9h18M7 15h4"/></svg></span><span class="nav-label">Cartões e faturas</span></a>
      <a class="nav-item {% if active_nav == 'poupanca' %}active{% endif %}" href="/poupanca" title="Poupança" {% if active_nav == 'poupanca' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M5 9 3 6m16 3 2-3M4 14c0-4 3-7 8-7s8 3 8 7-3 7-8 7-8-3-8-7Z"/><path d="M8 13h.01M16 13h.01M10 17h4"/><path d="M12 7V4h4"/></svg></span><span class="nav-label">Poupança</span></a>
      <a class="nav-item {% if active_nav == 'orcamento' %}active{% endif %}" href="/orcamento" title="Orçamento" {% if active_nav == 'orcamento' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M4 20V10m8 10V4m8 16v-7"/><path d="M2 20h20"/></svg></span><span class="nav-label">Orçamento</span></a>
      <a class="nav-item {% if active_nav == 'projecao' %}active{% endif %}" href="/projecao" title="Projeção" {% if active_nav == 'projecao' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="m3 17 6-6 4 3 8-9"/><path d="M15 5h6v6"/></svg></span><span class="nav-label">Projeção</span></a>
      <a class="nav-item {% if active_nav == 'historico' %}active{% endif %}" href="/historico" title="Histórico" {% if active_nav == 'historico' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5m4-1v5l4 2"/></svg></span><span class="nav-label">Histórico</span></a>
      <a class="nav-item {% if active_nav == 'relatorios' %}active{% endif %}" href="/relatorios" title="Relatórios" {% if active_nav == 'relatorios' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><path d="M4 20h16M6 17V9m6 8V4m6 13v-5"/><path d="M4 4h2"/></svg></span><span class="nav-label">Relatórios e backup</span></a>
      <a class="nav-item {% if active_nav == 'cadastros' %}active{% endif %}" href="/cadastros" title="Cadastros" {% if active_nav == 'cadastros' %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M19 8v8m-4-4h8"/></svg></span><span class="nav-label">Cadastros</span></a>
      {% if current_user and current_user.is_admin %}<a class="nav-item {% if request.url.path.startswith('/usuarios') %}active{% endif %}" href="/usuarios" title="Usuários" {% if request.url.path.startswith('/usuarios') %}aria-current="page"{% endif %}><span class="nav-icon"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M19 8v8m-4-4h8"/></svg></span><span class="nav-label">Usuários</span></a>{% endif %}
    </nav>
    <div class="sidebar-bottom"><span class="sidebar-status-dot"></span><span class="nav-label">Banco local protegido</span></div>
  </aside>
  <button class="sidebar-overlay" id="sidebar-overlay" type="button" aria-label="Fechar menu" tabindex="-1"></button>
  <div class="app-main">
    <header class="topbar">
      <button type="button" class="icon-button menu-toggle" id="sidebar-toggle" aria-label="Abrir menu" aria-controls="app-sidebar" aria-expanded="false"><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>
      <div class="topbar-heading"><span class="topbar-overline">FINANÇAS FAMILIARES</span><strong>{% if active_nav == 'dashboard' %}Visão geral{% elif active_nav == 'transacoes' %}Gastos{% elif active_nav == 'fixos' %}Gastos fixos{% elif active_nav == 'planejados' %}Planejados{% elif active_nav == 'receitas' %}Receitas{% elif active_nav == 'cartoes' %}Cartões e faturas{% elif active_nav == 'poupanca' %}Poupança{% elif active_nav == 'orcamento' %}Orçamento{% elif active_nav == 'projecao' %}Projeção financeira{% elif active_nav == 'historico' %}Histórico{% elif active_nav == 'relatorios' %}Relatórios{% elif active_nav == 'cadastros' %}Cadastros{% elif request.url.path.startswith('/usuarios') %}Usuários{% else %}Casa em Ordem{% endif %}</strong></div>
      <div class="top-actions">
        <span class="top-date"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 10h18"/></svg>{{ today.strftime('%d/%m/%Y') }}</span>
        <button type="button" class="theme-toggle" id="theme-toggle" aria-label="Alternar tema" title="Alternar tema"><svg class="theme-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg><span class="theme-text">Material Light</span></button>
        {% if current_user %}<a class="top-action user-chip" href="/alterar-senha"><span class="user-avatar">{{ current_user.username[:1]|upper }}</span><span class="user-name">{{ current_user.username }}</span></a>{% if current_user.is_admin %}<a class="top-action admin-shortcut" href="/usuarios" title="Gerenciar usuários"><svg viewBox="0 0 24 24"><circle cx="9" cy="8" r="4"/><path d="M2 21v-2a7 7 0 0 1 14 0v2M19 8v8m-4-4h8"/></svg></a>{% endif %}<form method="post" action="/logout"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="top-action logout-action" type="submit" title="Sair"><svg viewBox="0 0 24 24"><path d="M10 17l5-5-5-5m5 5H3"/><path d="M12 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-6"/></svg><span>Sair</span></button></form>{% endif %}
      </div>
    </header>
    <main class="container">
      {% if erro %}<div class="notice error" role="alert">{{ erro }}</div>{% endif %}
      {% if ok %}<div class="notice success">Alterações salvas.</div>{% endif %}
      {% block content %}{% endblock %}
    </main>
    <footer class="footer"><span class="footer-dot"></span> Seus dados financeiros · BRL · Armazenados localmente</footer>
  </div>
</body>
</html>
```

## `app/templates/budgets.html`

```html
{% extends "base.html" %}
{% block title %}Orçamento mensal · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CONTROLE DO PLANEJADO</p><h1>Orçamento mensal</h1><p class="muted">O gasto contabilizado no orçamento é classificado pela data da compra e pelo status realizado.</p></div></section>
<form class="filter-bar" method="get"><label for="mes">Mês</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light">Ver mês</button></form>
<form class="panel form-panel" method="post" action="/orcamento"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><h2>Definir orçamento por categoria</h2><div class="form-grid"><input type="hidden" name="mes" value="{{ mes }}"><label class="field">Categoria<select name="category_id" required>{% for c in category_options %}<option value="{{ c.id }}">{{ c.label }}</option>{% endfor %}</select></label><label class="field">Valor mensal (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label></div><div class="form-actions"><button class="button" type="submit">Salvar orçamento</button></div></form>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Categoria</th><th>Orçamento</th><th>Realizado</th><th>Uso</th><th></th></tr></thead><tbody>{% for row in rows %}<tr><td>{{ row.label }}</td><td>{{ row.budget.amount_cents|brl }}</td><td>{{ row.spent|brl }}</td><td><div class="budget-cell"><div class="progress"><span class="{% if row.over %}over{% endif %}" style="width:{{ row.percent if row.percent < 100 else 100 }}%"></span></div><small class="{% if row.over %}danger-text{% endif %}">{{ row.percent }}%{% if row.over %} · excedido{% endif %}</small></div></td><td><form method="post" action="/orcamento/{{ row.budget.id }}/excluir" onsubmit="return confirm('Excluir este orçamento?')"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="text-button danger-text">Excluir</button></form></td></tr>{% else %}<tr><td colspan="5" class="empty-cell">Nenhum orçamento cadastrado neste mês.</td></tr>{% endfor %}</tbody></table></div></section>
{% endblock %}
```

## `app/templates/cards.html`

```html
{% extends "base.html" %}
{% block title %}Cartões e faturas · Casa em Ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CARTEIRA FAMILIAR</p><h1>Cartões e faturas</h1><p class="muted">Uma visão rápida dos cartões da família e dos compromissos de crédito.</p></div><a class="button button-light" href="/cadastros">＋ Gerenciar cartões</a></section>
<section class="wallet-section"><div class="section-heading"><div><h2>Seus cartões</h2><p class="muted">Os números completos não são armazenados, apenas os quatro últimos dígitos.</p></div><span class="wallet-count">{{ all_cards|length }} cartão(ões)</span></div>
  {% if all_cards %}<div class="bank-card-grid">{% for card in all_cards %}{% include "partials/bank_card.html" %}{% endfor %}</div>{% else %}<div class="empty-state">Nenhum cartão cadastrado. <a href="/cadastros">Adicionar cartão</a></div>{% endif %}
</section>
<section class="invoice-section section-gap">
  <div class="section-heading"><div><p class="eyebrow">CONTROLE DE CRÉDITO</p><h2>Consultar fatura</h2><p class="muted">A fatura é agrupada pelo vencimento calculado a partir do fechamento.</p></div></div>
  {% if credit_cards %}<form class="filter-bar invoice-filter" method="get"><label for="mes">Mês de vencimento</label><input id="mes" type="month" name="mes" value="{{ mes }}"><label for="cartao">Cartão de crédito</label><select id="cartao" name="cartao">{% for c in credit_cards %}<option value="{{ c.id }}" {% if selected_card and selected_card.id == c.id %}selected{% endif %}>{{ c.name }} · {{ c.owner.name }}{% if c.last_four_digits %} · •••• {{ c.last_four_digits }}{% endif %}</option>{% endfor %}</select><button class="button" type="submit">Ver fatura</button></form>
  {% if selected_card %}<div class="invoice-summary"><div class="invoice-card-mini">{% set card = selected_card %}{% include "partials/bank_card.html" %}</div><article class="metric invoice-total-metric"><span>Total previsto da fatura</span><strong>{{ total|brl }}</strong><small>Limite cadastrado: {{ selected_card.limit_cents|brl }}</small><div class="invoice-meta"><span>Fecha dia {{ selected_card.closing_day }}</span><span>Vence dia {{ selected_card.due_day }}</span></div></article></div>
  <section class="panel invoice-table-panel"><div class="panel-heading"><div><h2>Itens da fatura — {{ mes[5:7] }}/{{ mes[:4] }}</h2><p class="muted">Relatórios de categoria usam a data da compra; fluxo de caixa, o vencimento.</p></div><span class="invoice-item-count">{{ items|length }} item(ns)</span></div><div class="table-wrap"><table><thead><tr><th>Compra / descrição</th><th>Categoria</th><th>Responsável</th><th>Vencimento</th><th>Status</th><th class="money">Valor</th><th></th></tr></thead><tbody>{% for item in items %}<tr><td>{{ item.description }}<small class="subline">Compra em {{ item.purchase_date|date_br }}</small>{% if item.installment_number %}<small class="subline">Parcela {{ item.installment_number }}/{{ item.installment_count }}</small>{% endif %}</td><td>{{ item.category.name }}</td><td>{{ item.person.name }}</td><td>{{ item.cashflow_date|date_br }}</td><td><span class="status status-{{ item.status }}">{{ item.status }}</span></td><td class="money">{{ item.amount_cents|brl }}</td><td><a class="text-link" href="/transacoes/{{ item.id }}/editar">Editar</a></td></tr>{% else %}<tr><td colspan="7" class="empty-cell">Nenhuma compra nesta fatura.</td></tr>{% endfor %}</tbody><tfoot><tr><th colspan="5">Total da fatura</th><th class="money">{{ total|brl }}</th><th></th></tr></tfoot></table></div></section>{% endif %}
  {% else %}<div class="empty-state">Não há cartões de crédito ativos. Cartões de débito e Vale Alimentação aparecem acima e lançam a saída na data da compra.</div>{% endif %}
</section>
{% endblock %}
```

## `app/templates/change_password.html`

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#12352d">
  <title>Alterar senha · Casa em Ordem</title>
  <link rel="stylesheet" href="/static/css/app.css">
</head>
<body class="auth-body">
  <main class="auth-wrap">
    <div class="auth-brand"><span class="brand-mark">R$</span><div><strong>Casa em Ordem</strong><small>Finanças da família</small></div></div>
    <section class="panel auth-panel">
      <p class="eyebrow">SEGURANÇA DA CONTA</p>
      <h1>{% if mandatory %}Crie sua senha{% else %}Alterar senha{% endif %}</h1>
      {% if mandatory %}<div class="notice error">Esta senha é provisória. Você precisa definir uma nova senha antes de acessar os dados financeiros.</div>{% endif %}
      {% if erro %}<div class="notice error" role="alert">{{ erro }}</div>{% endif %}
      <p class="muted">Usuário: <strong>{{ username }}</strong>. Use pelo menos 12 caracteres.</p>
      <form method="post" action="/alterar-senha" class="form-stack">
        <input type="hidden" name="_csrf" value="{{ csrf_token }}">
        <label class="field">Senha atual<input name="current_password" type="password" autocomplete="current-password" required></label>
        <label class="field">Nova senha<input name="new_password" type="password" autocomplete="new-password" minlength="12" required></label>
        <label class="field">Confirme a nova senha<input name="confirm_password" type="password" autocomplete="new-password" minlength="12" required></label>
        <button class="button auth-submit" type="submit">Salvar nova senha</button>
      </form>
      <form method="post" action="/logout" class="auth-secondary-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="text-button" type="submit">Sair</button></form>
    </section>
  </main>
</body>
</html>
```

## `app/templates/dashboard.html`

```html
{% extends "base.html" %}
{% block title %}Visão geral · Casa em Ordem{% endblock %}
{% block content %}
<section class="page-head dashboard-head">
  <div><p class="eyebrow">PAINEL FINANCEIRO</p><h1>Bom dia, família <span class="headline-spark">✦</span></h1><p class="muted">Aqui está o resumo de {{ '%02d'|format(month) }}/{{ year }}.</p></div>
  <form class="month-form" method="get" action="/"><label for="mes">Período</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button" type="submit">Atualizar</button></form>
</section>
<section class="metric-grid dashboard-metrics">
  <article class="metric metric-income"><div class="metric-label-row"><span class="metric-symbol"><svg viewBox="0 0 24 24"><path d="M12 19V5m-6 6 6-6 6 6"/><path d="M4 21h16"/></svg></span><span class="metric-label">Entradas no mês</span></div><strong>{{ income_total|brl }}</strong><small><span class="metric-dot"></span>{{ income_count }} lançamento(s) no fluxo de caixa</small><div class="metric-comparison {% if income_total >= prev_income %}up{% else %}down{% endif %}">{% if income_total >= prev_income %}↑{% else %}↓{% endif %} {{ ((income_total-prev_income)*100//prev_income if prev_income else (100 if income_total else 0))|abs }}% <span>vs. mês anterior</span></div></article>
  <article class="metric metric-expense"><div class="metric-label-row"><span class="metric-symbol"><svg viewBox="0 0 24 24"><path d="M12 5v14m6-6-6 6-6-6"/><path d="M4 3h16"/></svg></span><span class="metric-label">Saídas no mês</span></div><strong>{{ expense_total|brl }}</strong><small><span class="metric-dot"></span>{{ expense_count }} compromisso(s), cartão pelo vencimento</small><div class="metric-comparison {% if expense_total <= prev_expense %}up{% else %}down{% endif %}">{% if expense_total <= prev_expense %}↓{% else %}↑{% endif %} {{ ((expense_total-prev_expense)*100//prev_expense if prev_expense else (100 if expense_total else 0))|abs }}% <span>vs. mês anterior</span></div></article>
  <article class="metric {% if balance < 0 %}metric-danger{% else %}metric-balance{% endif %}"><div class="metric-label-row"><span class="metric-symbol"><svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="15" rx="3"/><path d="M3 10h18m-13 5h4"/></svg></span><span class="metric-label">Saldo previsto</span></div><strong>{{ balance|brl }}</strong><small><span class="metric-dot"></span>Entradas menos compromissos do mês</small><div class="metric-comparison {% if balance >= prev_balance %}up{% else %}down{% endif %}">{% if balance >= prev_balance %}↑{% else %}↓{% endif %} {{ ((balance-prev_balance)*100//(prev_balance if prev_balance else 1))|abs }}% <span>vs. saldo anterior</span></div></article>
</section>
<section class="panel cashflow-panel">
  <div class="panel-heading cashflow-heading"><div><p class="eyebrow">FLUXO DE CAIXA</p><h2>Entradas x saídas</h2><p class="muted">Comparativo mensal dos últimos 12 meses · valores em reais</p></div><span class="chart-period"><span class="chart-status-dot"></span>12 meses</span></div>
  <div class="cashflow-legend"><span><i class="legend-income"></i> Entradas</span><span><i class="legend-expense"></i> Saídas</span></div>
  <div class="chart-wrap cashflow-chart-wrap"><canvas id="chart-cashflow" aria-label="Gráfico de linhas comparando entradas e saídas do fluxo de caixa nos últimos doze meses"></canvas></div>
  <div class="cashflow-footer"><span><small>Diferença no mês selecionado</small><strong class="{% if balance < 0 %}negative-value{% else %}positive-value{% endif %}">{{ balance|brl }}</strong></span><span><small>Despesas vs. mês anterior</small><strong>{% if expense_total > prev_expense %}+{% elif expense_total < prev_expense %}−{% endif %}{{ ((expense_total-prev_expense)|abs)|brl }}</strong></span></div>
</section>
<section class="dashboard-lower-grid section-gap">
  <article class="panel chart-panel"><div class="panel-heading"><div><h2>Gastos por categoria</h2><p class="muted">Compras realizadas em {{ '%02d'|format(month) }}/{{ year }}</p></div><a class="text-link" href="/historico?mes={{ mes }}">Detalhes ↗</a></div><div class="chart-wrap"><canvas id="chart-pie" aria-label="Gastos por categoria"></canvas></div><p class="empty-hint" id="pie-empty" hidden>Sem despesas realizadas neste mês.</p></article>
  <article class="panel chart-panel"><div class="panel-heading"><div><h2>Evolução do saldo</h2><p class="muted">Saldo acumulado relativo nos 12 meses</p></div><a class="text-link" href="/projecao">Projeção ↗</a></div><div class="chart-wrap"><canvas id="chart-line" aria-label="Evolução do saldo acumulado"></canvas></div></article>
  <article class="panel chart-panel card-chart-panel"><div class="panel-heading"><div><h2>Uso por cartão</h2><p class="muted">Saídas agrupadas por cartão · últimos 6 meses</p></div><a class="text-link" href="/cartoes">Cartões ↗</a></div><div class="chart-wrap"><canvas id="chart-cards" aria-label="Despesas por cartão"></canvas></div></article>
</section>
<section class="content-grid section-gap">
  <article class="panel"><div class="panel-heading"><div><h2>Próximos vencimentos</h2><p class="muted">Até 45 dias · faturas sem dupla contagem</p></div><a class="text-link" href="/planejados">Ver planejados ↗</a></div><div id="upcoming-list" hx-get="/partials/proximos" hx-trigger="load" hx-swap="innerHTML"><p class="muted">Carregando vencimentos…</p></div></article>
  <article class="panel"><div class="panel-heading"><div><h2>Orçamento por categoria</h2><p class="muted">Despesas realizadas pela data da compra</p></div><a class="text-link" href="/orcamento?mes={{ mes }}">Gerenciar ↗</a></div>
    {% if budget_rows %}<div class="budget-list">{% for item in budget_rows %}<div class="budget-row"><div class="row-between"><span>{{ item.name }}</span><strong>{{ item.spent|brl }} / {{ item.amount|brl }}</strong></div><div class="progress"><span class="{% if item.over %}over{% endif %}" style="width:{{ item.percent if item.percent < 100 else 100 }}%"></span></div><small class="{% if item.over %}danger-text{% else %}muted{% endif %}">{% if item.over %}Orçamento excedido em {{ (item.spent-item.amount)|brl }}{% else %}{{ item.percent }}% utilizado{% endif %}</small></div>{% endfor %}</div>{% else %}<div class="empty-state">Nenhum orçamento cadastrado para este mês. <a href="/orcamento?mes={{ mes }}">Criar orçamento</a></div>{% endif %}
  </article>
</section>
<section class="panel section-gap"><div class="panel-heading"><div><h2>Categorias com maior gasto</h2><p class="muted">Variação comparada ao mês anterior</p></div><a class="text-link" href="/historico?mes={{ mes }}">Resumo do mês ↗</a></div>
  {% if ranking %}<div class="table-wrap"><table><thead><tr><th>Categoria</th><th>Este mês</th><th>Mês anterior</th><th>Variação</th></tr></thead><tbody>{% for item in ranking %}<tr><td>{{ item.name }}</td><td>{{ item.amount|brl }}</td><td>{{ item.previous|brl }}</td><td><span class="change {% if item.delta > 0 %}danger-text{% elif item.delta < 0 %}good-text{% endif %}">{% if item.delta > 0 %}+{% endif %}{{ item.delta }}%</span></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty-state">Registre despesas realizadas para montar o ranking.</p>{% endif %}
</section>
<script id="chart-data" type="application/json">{{ chart_payload|tojson }}</script>
{% endblock %}
```

## `app/templates/fixed.html`

```html
{% extends "base.html" %}
{% block title %}Gastos fixos · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">RECORRÊNCIA MENSAL</p><h1>Gastos fixos</h1><p class="muted">Ocorrências são criadas automaticamente até 12 meses à frente. Ajuste um mês específico em Gastos, sem alterar os demais.</p></div></section>
<form class="panel form-panel" method="post" action="/transacoes/fixos"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><h2>Novo gasto recorrente</h2><div class="form-grid">
<label class="field field-wide">Descrição<input name="name" required placeholder="Ex.: mensalidade do colégio"></label><label class="field">Valor mensal (R$)<input name="amount" required inputmode="decimal" placeholder="0,00"></label><label class="field">Dia do mês<input type="number" name="day_of_month" min="1" max="31" value="10" required></label>
<label class="field">Categoria<select name="category_id" required>{% for c in category_options %}<option value="{{ c.id }}">{{ c.label }}</option>{% endfor %}</select></label><label class="field">Responsável<select name="person_id" required>{% for p in people %}<option value="{{ p.id }}" {% if p.name == 'Família' %}selected{% endif %}>{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Início da vigência<input type="date" name="start_date" value="{{ today.isoformat() }}" required></label><label class="field">Fim da vigência (opcional)<input type="date" name="end_date"></label>
<label class="field">Conta<select name="account_id"><option value="">Nenhuma / dinheiro</option>{% for a in accounts %}<option value="{{ a.id }}">{{ a.name }}</option>{% endfor %}</select></label><label class="field">Cartão<select name="card_id"><option value="">Não usar cartão</option>{% for c in cards %}<option value="{{ c.id }}">{{ c.name }} · {{ c.owner.name }}</option>{% endfor %}</select></label>
</div><div class="form-actions"><button class="button" type="submit">Criar recorrência</button></div></form>
<section class="section-heading"><div><h2>Recorrências cadastradas</h2><p class="muted">Editar a recorrência afeta a regra, não os lançamentos já gerados.</p></div></section>
{% if fixed_items %}<div class="stack-list">{% for item in fixed_items %}<details class="panel fixed-item"><summary><span><b>{{ item.name }}</b><small>{{ item.category.name }} · dia {{ item.day_of_month }} · {{ item.person.name }}</small></span><span class="summary-end"><b>{{ item.amount_cents|brl }}</b><span class="status {% if item.active %}status-realizado{% else %}status-cancelado{% endif %}">{% if item.active %}ativa{% else %}inativa{% endif %}</span></span></summary>
<form method="post" action="/transacoes/fixos/{{ item.id }}/editar" class="form-grid compact-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
<label class="field field-wide">Descrição<input name="name" required value="{{ item.name }}"></label><label class="field">Valor (R$)<input name="amount" required value="{{ item.amount_cents|brl }}"></label><label class="field">Dia<input name="day_of_month" type="number" min="1" max="31" value="{{ item.day_of_month }}"></label>
<label class="field">Categoria<select name="category_id">{% for c in category_options %}<option value="{{ c.id }}" {% if c.id == item.category_id %}selected{% endif %}>{{ c.label }}</option>{% endfor %}</select></label><label class="field">Responsável<select name="person_id">{% for p in people %}<option value="{{ p.id }}" {% if p.id == item.person_id %}selected{% endif %}>{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Início<input name="start_date" type="date" value="{{ item.start_date.isoformat() }}"></label><label class="field">Fim<input name="end_date" type="date" value="{{ item.end_date.isoformat() if item.end_date else '' }}"></label>
<label class="field">Conta<select name="account_id"><option value="">Nenhuma / dinheiro</option>{% for a in accounts %}<option value="{{ a.id }}" {% if item.account_id == a.id %}selected{% endif %}>{{ a.name }}</option>{% endfor %}</select></label><label class="field">Cartão<select name="card_id"><option value="">Não usar cartão</option>{% for c in cards %}<option value="{{ c.id }}" {% if item.card_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></label>
<label class="field">Situação<select name="active"><option value="sim" {% if item.active %}selected{% endif %}>Ativa</option><option value="nao" {% if not item.active %}selected{% endif %}>Inativa</option></select></label><div class="form-actions"><button class="button button-small" type="submit">Salvar regra</button></div>
</form></details>{% endfor %}</div>{% else %}<div class="empty-state">Cadastre aqui colégio, internet, seguro e outros compromissos mensais.</div>{% endif %}
{% endblock %}
```

## `app/templates/history.html`

```html
{% extends "base.html" %}
{% block title %}Resumo mensal · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CONSULTA HISTÓRICA</p><h1>Resumo do mês</h1><p class="muted">Os relatórios por categoria seguem a data da compra, não a data de vencimento do cartão.</p></div></section>
<form class="filter-bar" method="get"><label for="mes">Mês/ano</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light">Consultar</button></form>
<section class="metric-grid metric-grid-two"><article class="metric metric-good"><span>Receitas no fluxo</span><strong>{{ income_total|brl }}</strong></article><article class="metric"><span>Gastos realizados por data de compra</span><strong>{{ expense_total|brl }}</strong></article></section>
<div class="summary-grid">
<section class="panel"><h2>Por categoria</h2><div class="simple-list">{% for item in category_totals %}<div><span>{{ item.name }}</span><b>{{ item.amount|brl }}</b></div>{% else %}<p class="muted">Sem dados.</p>{% endfor %}</div></section>
<section class="panel"><h2>Por pessoa</h2><div class="simple-list">{% for item in person_totals %}<div><span>{{ item.name }}</span><b>{{ item.amount|brl }}</b></div>{% else %}<p class="muted">Sem dados.</p>{% endfor %}</div></section>
<section class="panel"><h2>Por cartão</h2><div class="simple-list">{% for item in card_totals %}<div><span>{{ item.name }}</span><b>{{ item.amount|brl }}</b></div>{% else %}<p class="muted">Nenhuma despesa em cartão neste mês.</p>{% endfor %}</div></section>
</div>
<section class="panel"><h2>Maiores gastos do mês</h2><div class="table-wrap"><table><thead><tr><th>Data</th><th>Descrição</th><th>Categoria</th><th>Pessoa</th><th>Cartão</th><th>Valor</th></tr></thead><tbody>{% for item in top_expenses %}<tr><td>{{ item.purchase_date|date_br }}</td><td>{{ item.description }}</td><td>{{ item.category.name }}</td><td>{{ item.person.name }}</td><td>{{ item.card.name if item.card else '—' }}</td><td class="money">{{ item.amount_cents|brl }}</td></tr>{% else %}<tr><td class="empty-cell" colspan="6">Sem gastos realizados neste mês.</td></tr>{% endfor %}</tbody></table></div></section>
{% endblock %}
```

## `app/templates/incomes.html`

```html
{% extends "base.html" %}
{% block title %}Receitas · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">ENTRADAS E DESCONTOS</p><h1>Receitas</h1><p class="muted">Plano de saúde, INSS e IR em folha são informativos e não entram novamente nas despesas.</p></div></section>
<section class="metric-grid metric-grid-two"><article class="metric metric-good"><span>Receitas incluídas no caixa</span><strong>{{ cash_total|brl }}</strong><small>Salários e rendas extras lançados no mês</small></article><article class="metric"><span>Descontos em folha informativos</span><strong>{{ deductions|brl }}</strong><small>Não duplicados como despesa</small></article></section>
<form class="filter-bar" method="get"><label for="mes">Mês</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light" type="submit">Filtrar</button></form>
<form class="panel form-panel" method="post" action="/receitas"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><h2>Adicionar receita ou desconto</h2><div class="form-grid">
<label class="field">Data<input type="date" name="happened_on" value="{{ today.isoformat() }}" required></label><label class="field">Pessoa<select name="person_id" required>{% for p in people if p.name != 'Família' %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Tipo<select name="kind" required><option value="salario">Salário</option><option value="extra">Renda extra</option><optgroup label="Desconto em folha"><option value="plano_saude">Plano de saúde</option><option value="inss">INSS</option><option value="ir">IR</option><option value="vale">Vale</option><option value="outros_desconto">Outros</option></optgroup><option value="vale">Vale descontado em folha</option><option value="outros_desconto">Outros descontos em folha</option></select></label>
<label class="field">Valor (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label><label class="field field-wide">Descrição (opcional)<input name="description" placeholder="Ex.: salário de outubro, freela de fim de semana"></label>
</div><div class="form-actions"><button class="button" type="submit">Salvar lançamento</button></div></form>
<section class="section-heading"><div><h2>Lançamentos de {{ mes[5:7] }}/{{ mes[:4] }}</h2></div></section>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Pessoa</th><th>Tipo / descrição</th><th>Tratamento</th><th>Valor</th><th></th></tr></thead><tbody>{% for item in rows %}<tr><td>{{ item.happened_on|date_br }}</td><td>{{ item.person.name }}</td><td>{{ kinds[item.kind] }}<small class="subline">{{ item.description }}</small></td><td>{% if item.included_in_cashflow %}<span class="status status-realizado">No fluxo</span>{% else %}<span class="status status-previsto">Informativo</span>{% endif %}</td><td class="money">{{ item.amount_cents|brl }}</td><td><form method="post" action="/receitas/{{ item.id }}/excluir" onsubmit="return confirm('Excluir este lançamento?')"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="text-button danger-text" type="submit">Excluir</button></form></td></tr>{% else %}<tr><td class="empty-cell" colspan="6">Nenhum lançamento neste mês.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
```

## `app/templates/login.html`

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#12352d">
  <title>Entrar · Casa em Ordem</title>
  <link rel="stylesheet" href="/static/css/app.css">
</head>
<body class="auth-body">
  <main class="auth-wrap">
    <div class="auth-brand"><span class="brand-mark">R$</span><div><strong>Casa em Ordem</strong><small>Finanças da família</small></div></div>
    <section class="panel auth-panel">
      <p class="eyebrow">ÁREA PROTEGIDA</p>
      <h1>Entrar</h1>
      <p class="muted">Informe seu usuário e sua senha para continuar.</p>
      {% if erro %}<div class="notice error" role="alert">{{ erro }}</div>{% endif %}
      {% if request.query_params.get('ok') == 'logout' %}<div class="notice success">Você saiu da aplicação.</div>{% endif %}
      <form method="post" action="/login" class="form-stack">
        <input type="hidden" name="_csrf" value="{{ csrf_token }}">
        <input type="hidden" name="next_url" value="{{ next_url }}">
        <label class="field">Usuário<input name="username" autocomplete="username" required autofocus maxlength="32"></label>
        <label class="field">Senha<input name="password" type="password" autocomplete="current-password" required></label>
        <button class="button auth-submit" type="submit">Entrar</button>
      </form>
      <p class="auth-footnote">A sessão expira após 8 horas de inatividade ou validade.</p>
    </section>
  </main>
</body>
</html>
```

## `app/templates/partials/bank_card.html`

```html
{% set card_name_lc = card.name|lower %}
{% if 'nubank' in card_name_lc %}{% set card_brand = 'nubank' %}{% set card_issuer = 'Nubank' %}
{% elif 'santander' in card_name_lc %}{% set card_brand = 'santander' %}{% set card_issuer = 'Santander' %}
{% elif 'bradesco' in card_name_lc %}{% set card_brand = 'bradesco' %}{% set card_issuer = 'Bradesco' %}
{% elif 'ticket' in card_name_lc %}{% set card_brand = 'ticket' %}{% set card_issuer = 'Ticket' %}
{% elif 'clear' in card_name_lc %}{% set card_brand = 'clear' %}{% set card_issuer = 'Clear' %}
{% else %}{% set card_brand = 'generic' %}{% set card_issuer = 'Cartão' %}{% endif %}
<article class="bank-card bank-card-{{ card_brand }}">
  <div class="bank-card-head"><span class="bank-card-issuer">{{ card_issuer }}</span><span class="bank-card-kind">{% if card.kind == 'credito' %}CRÉDITO{% elif card.kind == 'vale_alimentacao' %}VALE ALIMENTAÇÃO{% else %}DÉBITO{% endif %}</span></div>
  <div class="bank-card-chip" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
  <div class="bank-card-number" aria-label="Final do cartão {{ card.last_four_digits if card.last_four_digits else 'não informado' }}">•••• &nbsp;•••• &nbsp;•••• &nbsp;<strong>{{ card.last_four_digits if card.last_four_digits else '••••' }}</strong></div>
  <div class="bank-card-foot"><div><small>TITULAR</small><strong>{{ card.owner.name }}</strong></div><div class="bank-card-label"><small>CARTÃO</small><strong>{{ card.name }}</strong></div></div>
</article>
```

## `app/templates/partials/upcoming_rows.html`

```html
{% if rows %}
<div class="upcoming-list">{% for item in rows %}<div class="upcoming-item"><div class="upcoming-date"><b>{{ item.cashflow_date.strftime('%d') }}</b><small>{{ item.cashflow_date.strftime('%m/%Y') }}</small></div><div class="upcoming-detail"><b>{{ item.description }}</b><small>{{ item.person.name }} · {% if item.card %}{{ item.card.name }}{% elif item.account %}{{ item.account.name }}{% else %}Sem conta/cartão{% endif %}</small><small>{{ item.category.name }}</small></div><div class="upcoming-value"><b>{{ item.amount_cents|brl }}</b><span class="status status-{{ item.status }}">{{ item.status }}</span></div></div>{% endfor %}</div>
{% else %}<div class="empty-state">Nenhum vencimento previsto para os próximos 45 dias.</div>{% endif %}
```

## `app/templates/planned.html`

```html
{% extends "base.html" %}
{% block title %}Gastos planejados · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">PREVISÃO</p><h1>Gastos planejados</h1><p class="muted">Marque como realizado quando pago/confirmado, edite ou cancele o compromisso.</p></div><a class="button" href="/transacoes/nova?tipo=previsto">+ Planejar gasto</a></section>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Data de caixa</th><th>Descrição</th><th>Categoria / responsável</th><th>Pagamento</th><th>Valor</th><th>Ações</th></tr></thead><tbody>
{% for item in rows %}<tr><td>{{ item.cashflow_date|date_br }}</td><td>{{ item.description }}{% if item.installment_number %}<small class="subline">Parcela {{ item.installment_number }}/{{ item.installment_count }}</small>{% endif %}</td><td>{{ item.category.name }}<small class="subline">{{ item.person.name }}</small></td><td>{% if item.card %}{{ item.card.name }}{% elif item.account %}{{ item.account.name }}{% else %}Dinheiro/outro{% endif %}</td><td class="money">{{ item.amount_cents|brl }}</td><td><div class="action-stack"><form method="post" action="/transacoes/{{ item.id }}/status"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><input type="hidden" name="status" value="realizado"><button class="button button-small" type="submit">Marcar pago</button></form><a class="button button-light button-small" href="/transacoes/{{ item.id }}/editar">Editar</a><form method="post" action="/transacoes/{{ item.id }}/cancelar" onsubmit="return confirm('Cancelar este lançamento?')"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="button button-danger button-small" type="submit">Cancelar</button></form></div></td></tr>
{% else %}<tr><td colspan="6" class="empty-cell">Nenhum gasto com status previsto.</td></tr>{% endfor %}
</tbody></table></div></section>
{% endblock %}
```

## `app/templates/projection.html`

```html
{% extends "base.html" %}
{% block title %}Projeção · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">PLANEJAMENTO</p><h1>Projeção de 12 meses</h1><p class="muted">Inclui gastos previstos/realizados conforme o vencimento de caixa. Receitas futuras precisam ser cadastradas com a respectiva data.</p></div><a class="button" href="/transacoes/nova?tipo=previsto">+ Planejar gasto</a></section>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>Mês</th><th>Receitas cadastradas</th><th>Despesas/compromissos</th><th>Saldo previsto</th></tr></thead><tbody>{% for row in months %}<tr><td><b>{{ row.name }}</b></td><td>{{ row.income|brl }}</td><td>{{ row.expenses|brl }}</td><td class="money {% if row.balance < 0 %}danger-text{% else %}good-text{% endif %}">{{ row.balance|brl }}</td></tr>{% endfor %}</tbody></table></div></div>
<div class="notice info">A projeção não presume um salário futuro automaticamente: cadastre entradas com a data esperada para que apareçam no mês correspondente. Despesas fixas ativas são geradas automaticamente.</div>
{% endblock %}
```

## `app/templates/registrations.html`

```html
{% extends "base.html" %}
{% block title %}Cadastros · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CONFIGURAÇÃO DA CASA</p><h1>Cadastros</h1><p class="muted">Gerencie pessoas, categorias, contas e cartões usados no dia a dia.</p></div></section>
<div class="registration-grid">
<section class="panel"><h2>Pessoas</h2>
  <form method="post" action="/cadastros/pessoas" class="inline-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><input name="name" required maxlength="80" placeholder="Nome da pessoa"><button class="button button-small">Adicionar</button></form>
  <div class="simple-list">{% for p in all_people %}<div class="registration-row people-row">
    <form method="post" action="/cadastros/pessoas/{{ p.id }}/editar" class="registration-edit-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
      <input name="name" aria-label="Nome de {{ p.name }}" value="{{ p.name }}" required maxlength="80">
      <select name="active" aria-label="Situação de {{ p.name }}"><option value="sim" {% if p.active %}selected{% endif %}>Ativa</option><option value="nao" {% if not p.active %}selected{% endif %}>Inativa</option></select>
      <button class="text-button" type="submit">Salvar</button>
    </form>
    <form method="post" action="/cadastros/pessoas/{{ p.id }}/excluir" onsubmit="return confirm('Excluir/inativar {{ p.name }}? Se houver histórico, a pessoa será preservada como inativa.')"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="text-button danger-text" type="submit">Excluir</button></form>
  </div>{% endfor %}</div>
  <p class="muted compact-copy">Se a pessoa tiver lançamentos relacionados, será inativada para preservar o histórico.</p>
</section>
<section class="panel"><h2>Categorias e subcategorias</h2>
  <form method="post" action="/cadastros/categorias" class="form-stack"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><label class="field">Nome<input name="name" required maxlength="100" placeholder="Ex.: Material escolar"></label>
    <label class="field">Categoria principal<select name="parent_id"><option value="">Criar categoria principal</option>{% for c in all_categories if not c.parent_id and c.active %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></label>
    <button class="button button-small" type="submit">Adicionar categoria</button>
  </form>
  <div class="simple-list">{% for c in all_categories if c.active %}<div class="registration-row category-row"><span>{% if c.parent %}↳ {{ c.parent.name }} / {% endif %}{{ c.name }}</span>
    <form method="post" action="/cadastros/categorias/{{ c.id }}/excluir" onsubmit="return confirm('Excluir a categoria {{ c.name }}?')"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="text-button danger-text" type="submit">Excluir</button></form>
  </div>{% endfor %}</div>
  <details class="inactive-list"><summary>Mostrar categorias excluídas/inativas</summary><div class="simple-list">{% for c in all_categories if not c.active %}<div class="registration-row category-row"><span>{% if c.parent %}↳ {{ c.parent.name }} / {% endif %}{{ c.name }}<small>Inativa · histórico preservado</small></span></div>{% else %}<p class="muted">Nenhuma categoria inativa.</p>{% endfor %}</div></details>
  <p class="muted compact-copy">Lazer fica sem subcategorias: use o campo de descrição do gasto para detalhar. Categorias excluídas saem dos novos lançamentos, preservando relatórios antigos.</p>
</section>
<section class="panel"><h2>Contas e carteiras</h2>
  <form method="post" action="/cadastros/contas" class="form-stack"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><label class="field">Nome<input name="name" required placeholder="Ex.: Conta principal"></label>
    <label class="field">Tipo<select name="kind"><option value="corrente">Conta corrente</option><option value="poupanca">Poupança</option><option value="dinheiro">Dinheiro/carteira</option><option value="outro">Outra</option></select></label>
    <label class="field">Responsável<select name="person_id"><option value="">Família/compartilhada</option>{% for p in people %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
    <label class="field">Saldo inicial (R$)<input name="initial_balance" value="0,00" inputmode="decimal"></label><button class="button button-small" type="submit">Adicionar conta</button>
  </form>
  <div class="simple-list">{% for a in all_accounts %}<div><span>{{ a.name }}<small>{{ a.kind }}{% if a.person %} · {{ a.person.name }}{% endif %}</small></span><b>{{ a.initial_balance_cents|brl }}</b></div>{% else %}<p class="muted">Nenhuma conta cadastrada.</p>{% endfor %}</div>
</section>
<section class="panel"><h2>Cartões e vales</h2>
  <form method="post" action="/cadastros/cartoes" class="form-stack" id="card-registration-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
    <label class="field">Nome do cartão<input name="name" required placeholder="Ex.: Visa principal"></label>
    <label class="field">Titular<select name="owner_id" required>{% for p in people if p.name != 'Família' and p.active %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
    <label class="field">Tipo<select name="kind" id="registration-card-kind"><option value="credito">Cartão de crédito</option><option value="debito">Cartão de débito</option><option value="vale_alimentacao">Vale Alimentação (débito)</option></select></label>
    <label class="field">4 últimos dígitos <small>Não informe o número completo do cartão.</small><input name="last_four_digits" inputmode="numeric" autocomplete="off" pattern="[0-9]{4}" minlength="4" maxlength="4" placeholder="1234"></label>
    <div class="form-grid" id="card-cycle-fields"><label class="field">Fecha dia<input type="number" name="closing_day" min="1" max="31" value="10"></label><label class="field">Vence dia<input type="number" name="due_day" min="1" max="31" value="17"></label></div>
    <label class="field">Limite / valor de referência (R$)<input name="limit" value="0,00" inputmode="decimal"></label>
    <label class="field">Conta usada para pagar a fatura (opcional)<select name="payment_account_id"><option value="">Não definida</option>{% for a in all_accounts if a.active %}<option value="{{ a.id }}">{{ a.name }}</option>{% endfor %}</select></label>
    <button class="button button-small" type="submit">Adicionar cartão</button>
  </form>
  <div class="registration-card-list">{% for c in all_cards %}<div class="registration-card-entry"><div class="registration-card-visual">{% set card = c %}{% include "partials/bank_card.html" %}</div><div class="registration-card-edit"><div><strong>{{ c.name }}</strong><small>{{ c.owner.name }} · {% if c.kind == 'credito' %}Crédito · fecha dia {{ c.closing_day }} · vence dia {{ c.due_day }}{% elif c.kind == 'vale_alimentacao' %}Vale Alimentação · débito{% else %}Débito{% endif %}</small></div><form method="post" action="/cadastros/cartoes/{{ c.id }}/editar" class="last-four-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><label class="field">4 últimos dígitos<input name="last_four_digits" value="{{ c.last_four_digits }}" inputmode="numeric" pattern="[0-9]{4}" minlength="4" maxlength="4" placeholder="1234"></label><button class="button button-small" type="submit">Salvar</button></form></div></div>{% else %}<p class="muted">Nenhum cartão cadastrado.</p>{% endfor %}</div>
  <p class="muted compact-copy">Débito e Vale Alimentação não pedem fechamento ou vencimento; as compras entram no fluxo de caixa na data da compra.</p>
</section>
</div>
<script>
document.addEventListener('DOMContentLoaded', function () {
  const kind = document.getElementById('registration-card-kind');
  const cycle = document.getElementById('card-cycle-fields');
  function toggleCardCycle() {
    if (!kind || !cycle) return;
    const credit = kind.value === 'credito';
    cycle.hidden = !credit;
    cycle.querySelectorAll('input').forEach(input => { input.disabled = !credit; input.required = credit; });
  }
  if (kind) { kind.addEventListener('change', toggleCardCycle); toggleCardCycle(); }
});
</script>
{% endblock %}
```

## `app/templates/reports.html`

```html
{% extends "base.html" %}
{% block title %}Relatórios e backup · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">SEUS DADOS</p><h1>Relatórios e backup</h1><p class="muted">Exporte o período em CSV ou baixe uma cópia consistente do banco SQLite.</p></div></section>
<section class="panel form-panel"><h2>Exportar CSV por período</h2><form method="get" action="/exportar.csv" class="form-grid"><label class="field">Data inicial<input type="date" name="inicio" value="{{ default_start }}" required></label><label class="field">Data final<input type="date" name="fim" value="{{ default_end }}" required></label><div class="form-actions"><button class="button" type="submit">Exportar CSV</button></div></form><p class="muted helper-text">O CSV inclui despesas pela data da compra e receitas/descontos pela data do lançamento, com valor em centavos e reais, status, conta, cartão e parcela.</p></section>
<section class="panel backup-panel"><div><h2>Backup completo do banco</h2><p class="muted">Baixa o arquivo .db com cadastros, movimentos, orçamentos e regras recorrentes. Guarde a cópia em local seguro.</p></div><a class="button" href="/backup.db">Baixar backup .db</a></section>
{% endblock %}
```

## `app/templates/savings.html`

```html
{% extends "base.html" %}
{% block title %}Poupança · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">RESERVAS E APLICAÇÕES</p><h1>Poupança</h1><p class="muted">Acompanhe o capital de cada pessoa. Depósitos e juros aumentam o saldo; retiradas diminuem.</p></div></section>
<section class="metric-grid metric-grid-two">
  <article class="metric metric-good"><span>Capital total guardado</span><strong>{{ total_capital|brl }}</strong><small>Soma dos saldos iniciais, depósitos, juros e retiradas de todas as poupanças ativas</small></article>
  <article class="metric"><span>Poupanças cadastradas</span><strong>{{ savings_accounts|length }}</strong><small>Podem existir várias poupanças por pessoa</small></article>
</section>
<div class="registration-grid savings-top-grid">
  <section class="panel"><h2>Criar poupança</h2><form method="post" action="/poupanca/contas" class="form-stack"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
    <label class="field">Nome / objetivo<input name="name" required maxlength="120" placeholder="Ex.: Reserva de emergência"></label>
    <label class="field">Pessoa titular<select name="person_id" required>{% for person in people if person.name != 'Família' %}<option value="{{ person.id }}">{{ person.name }}</option>{% endfor %}</select></label>
    <label class="field">Capital inicial (R$)<input name="initial_balance" value="0,00" inputmode="decimal" required><small class="muted">Informe 0,00 se estiver começando agora.</small></label>
    <button class="button button-small" type="submit">Criar poupança</button>
  </form></section>
  <section class="panel"><h2>Adicionar depósito ou retirada</h2><p class="muted compact-copy">Escolha a poupança e registre uma movimentação. Retiradas não podem superar o saldo disponível.</p>
    {% if savings_accounts %}<form method="post" action="/poupanca/movimentos" class="form-stack" id="general-savings-movement"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
      <label class="field">Poupança<select name="account_id" id="movement-account" required>{% for account in savings_accounts %}<option value="{{ account.id }}">{{ account.name }} · {{ account.person.name }}</option>{% endfor %}</select></label>
      <label class="field">Tipo<select name="kind" required><option value="deposito">Depósito</option><option value="retirada">Retirada</option></select></label>
      <label class="field">Data<input name="happened_on" type="date" value="{{ today.isoformat() }}" required></label>
      <label class="field">Valor (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label>
      <label class="field">Descrição<input name="description" maxlength="240" placeholder="Ex.: transferência mensal"></label>
      <button class="button button-small" type="submit">Salvar movimentação</button>
    </form>{% else %}<p class="empty-state">Crie uma poupança para registrar depósitos e retiradas.</p>{% endif %}
  </section>
</div>
<section class="section-heading"><div><h2>Capital por poupança</h2><p class="muted">O saldo inclui os juros lançados manualmente.</p></div></section>
<div class="savings-account-grid">
{% for item in balances %}<article class="panel savings-account-card">
  <div class="savings-card-head"><div><p class="eyebrow">{{ item.account.person.name }}</p><h3>{{ item.account.name }}</h3></div><span class="status status-realizado">Ativa</span></div>
  <strong class="savings-balance">{{ item.balance|brl }}</strong>
  <small class="muted">Capital inicial: {{ item.account.initial_balance_cents|brl }}</small>
  <form method="post" action="/poupanca/movimentos" class="interest-form"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
    <input type="hidden" name="account_id" value="{{ item.account.id }}"><input type="hidden" name="kind" value="juros">
    <label class="field">Data do rendimento<input name="happened_on" type="date" value="{{ today.isoformat() }}" required></label>
    <label class="field">Retorno de juros da aplicação (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label>
    <label class="field">Referência (opcional)<input name="description" maxlength="240" placeholder="Ex.: rendimento de outubro"></label>
    <button class="button button-light button-small" type="submit">Adicionar juros ao capital</button>
  </form>
  {% if savings_accounts %}<div class="account-actions"><a class="text-link" href="#general-savings-movement" onclick="document.getElementById('movement-account').value='{{ item.account.id }}'">Registrar depósito/retirada</a></div>{% endif %}
</article>{% else %}<div class="empty-state">Nenhuma poupança cadastrada. Crie uma acima para começar a acompanhar o capital.</div>{% endfor %}
</div>
<section class="section-heading"><div><h2>Movimentações recentes</h2><p class="muted">Últimos 100 lançamentos de todas as poupanças.</p></div></section>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Poupança / titular</th><th>Tipo</th><th>Descrição</th><th class="money">Valor</th></tr></thead><tbody>
{% for movement in movements %}<tr><td>{{ movement.happened_on|date_br }}</td><td>{{ movement.account.name }}<small class="subline">{{ movement.account.person.name }}</small></td><td>{% if movement.kind == 'deposito' %}Depósito{% elif movement.kind == 'retirada' %}Retirada{% else %}Juros de aplicação{% endif %}</td><td>{{ movement.description }}</td><td class="money {% if movement.kind == 'retirada' %}money-negative{% else %}money-positive{% endif %}">{% if movement.kind == 'retirada' %}−{% else %}+{% endif %}{{ movement.amount_cents|brl }}</td></tr>
{% else %}<tr><td colspan="5" class="empty-cell">Ainda não há movimentações registradas.</td></tr>{% endfor %}
</tbody></table></div></section>
{% endblock %}
```

## `app/templates/transaction_form.html`

```html
{% extends "base.html" %}
{% block title %}{{ title }} · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">MOVIMENTAÇÃO</p><h1>{{ title }}</h1><p class="muted">Valores em reais; parcelamento gera uma linha por fatura de crédito.</p></div><a class="button button-light" href="/transacoes">Voltar</a></section>
<form class="panel form-panel" method="post" action="{{ form_action }}"><input type="hidden" name="_csrf" value="{{ csrf_token }}">
  <div class="form-grid">
    <label class="field field-wide">Descrição<input name="description" required maxlength="240" value="{{ transaction.description if transaction else '' }}" placeholder="Ex.: supermercado, material escolar"></label>
    <label class="field">Valor total (R$)<input name="amount" required inputmode="decimal" placeholder="0,00" value="{{ transaction.amount_cents|brl if transaction else '' }}"></label>
    <label class="field">Data da compra<input type="date" name="purchase_date" required value="{{ transaction.purchase_date.isoformat() if transaction else today.isoformat() }}"></label>
    <label class="field">Categoria<select name="category_id" required><option value="">Selecione…</option>{% for c in category_options %}<option value="{{ c.id }}" {% if transaction and transaction.category_id == c.id %}selected{% endif %}>{{ c.label }}</option>{% endfor %}</select></label>
    <label class="field">Responsável<select name="person_id" required>{% for person in people %}<option value="{{ person.id }}" {% if transaction and transaction.person_id == person.id %}selected{% elif not transaction and person.name == 'Família' %}selected{% endif %}>{{ person.name }}</option>{% endfor %}</select></label>
    <label class="field">Conta de pagamento<select name="account_id" id="account_id"><option value="">Nenhuma / dinheiro</option>{% for account in accounts %}<option value="{{ account.id }}" {% if transaction and transaction.account_id == account.id %}selected{% endif %}>{{ account.name }}{% if account.person %} · {{ account.person.name }}{% endif %}</option>{% endfor %}</select></label>
    <label class="field">Cartão de pagamento<select name="card_id" id="card_id"><option value="">Não usar cartão</option>{% for card in cards %}<option value="{{ card.id }}" data-kind="{{ card.kind }}" {% if transaction and transaction.card_id == card.id %}selected{% endif %}>{{ card.name }} · {{ card.owner.name }}{% if card.kind == 'credito' %} · Crédito (fecha dia {{ card.closing_day }}){% elif card.kind == 'vale_alimentacao' %} · Vale Alimentação{% else %} · Débito{% endif %}</option>{% endfor %}</select></label>
    {% if not transaction %}<label class="field" id="installments-field">Parcelas no cartão de crédito<select name="installments" id="installments">{% for n in range(1, 61) %}<option value="{{ n }}" {% if n == 1 %}selected{% endif %}>{{ n }}x</option>{% endfor %}</select><small class="muted">O valor informado é o total da compra; o sistema distribui os centavos sem perder valor.</small></label>{% else %}<input type="hidden" name="installments" value="1">{% endif %}
    <label class="field">Status<select name="status"><option value="realizado" {% if default_status == 'realizado' %}selected{% endif %}>Realizado</option><option value="previsto" {% if default_status == 'previsto' %}selected{% endif %}>Previsto</option></select></label>
  </div>
  <div class="form-actions"><button class="button" type="submit">Salvar gasto</button><a class="button button-light" href="/transacoes">Cancelar</a></div>
</form>
<script>
document.addEventListener('DOMContentLoaded', function () {
  const cardSelect = document.getElementById('card_id');
  const installmentField = document.getElementById('installments-field');
  const installmentSelect = document.getElementById('installments');
  function updateInstallments() {
    if (!cardSelect || !installmentField || !installmentSelect) return;
    const option = cardSelect.selectedOptions[0];
    const isCredit = !option || !option.value || option.dataset.kind === 'credito';
    installmentField.hidden = !isCredit;
    installmentSelect.disabled = !isCredit;
    if (!isCredit) installmentSelect.value = '1';
  }
  if (cardSelect) { cardSelect.addEventListener('change', updateInstallments); updateInstallments(); }
});
</script>
{% endblock %}
```

## `app/templates/transactions.html`

```html
{% extends "base.html" %}
{% block title %}Gastos · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">LANÇAMENTOS</p><h1>Gastos</h1><p class="muted">Relatórios por categoria usam a data da compra.</p></div><a class="button" href="/transacoes/nova">+ Novo gasto</a></section>
<form class="filter-bar" method="get"><label for="mes">Mês da compra</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light" type="submit">Filtrar</button></form>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Descrição</th><th>Categoria / responsável</th><th>Pagamento</th><th>Status</th><th>Valor</th><th></th></tr></thead><tbody>
{% for item in rows %}<tr><td>{{ item.purchase_date|date_br }}</td><td>{{ item.description }}{% if item.installment_number %}<small class="subline">Parcela {{ item.installment_number }}/{{ item.installment_count }}</small>{% endif %}{% if item.fixed_expense_id %}<small class="subline">Gasto fixo recorrente</small>{% endif %}</td><td>{{ item.category.name }}<small class="subline">{{ item.person.name }}</small></td><td>{% if item.card %}{{ item.card.name }}<small class="subline">Venc. {{ item.cashflow_date|date_br }}</small>{% elif item.account %}{{ item.account.name }}{% else %}Dinheiro/outro{% endif %}</td><td><span class="status status-{{ item.status }}">{{ item.status }}</span></td><td class="money">{{ item.amount_cents|brl }}</td><td><a class="text-link" href="/transacoes/{{ item.id }}/editar">Editar</a></td></tr>
{% else %}<tr><td colspan="7" class="empty-cell">Nenhum gasto neste mês.</td></tr>{% endfor %}
</tbody></table></div></section>
<div class="floating-actions"><a class="button" href="/transacoes/nova">+ Lançar gasto</a><a class="button button-light" href="/transacoes/nova?tipo=previsto">+ Planejar gasto</a></div>
{% endblock %}
```

## `app/templates/users.html`

```html
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#12352d">
  <title>Usuários · Casa em Ordem</title>
  <link rel="stylesheet" href="/static/css/app.css">
  <script defer src="/static/js/app.js"></script>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Página inicial"><span class="brand-mark">R$</span><span>Casa em ordem<small>Finanças da família</small></span></a>
    <div class="top-actions"><a class="top-action" href="/alterar-senha">Alterar senha</a><form method="post" action="/logout"><input type="hidden" name="_csrf" value="{{ csrf_token }}"><button class="top-action" type="submit">Sair</button></form></div>
  </header>
  <nav class="nav-grid" aria-label="Navegação principal"><a class="nav-item" href="/">Visão geral</a><a class="nav-item" href="/cadastros">Cadastros</a><a class="nav-item active" href="/usuarios">Usuários</a></nav>
  <main class="container">
    {% if erro %}<div class="notice error" role="alert">{{ erro }}</div>{% endif %}
    {% if ok %}<div class="notice success">Usuário criado. Ele deverá trocar a senha no primeiro acesso.</div>{% endif %}
    <div class="page-head"><div><p class="eyebrow">ADMINISTRAÇÃO</p><h1>Usuários</h1><p class="muted">Somente o Admin pode criar contas. Novos usuários precisam trocar a senha no primeiro acesso.</p></div></div>
    <section class="panel auth-user-form">
      <h2>Criar usuário</h2>
      <form method="post" action="/usuarios" class="form-grid">
        <input type="hidden" name="_csrf" value="{{ csrf_token }}">
        <label class="field">Nome de usuário<input name="username" required minlength="3" maxlength="32" autocomplete="off" pattern="[A-Za-z0-9_.-]{3,32}"><small class="subline">3–32 caracteres: letras, números, ponto, hífen ou sublinhado.</small></label>
        <label class="field">Senha provisória<input name="password" type="password" required minlength="12" autocomplete="new-password"></label>
        <label class="field">Confirme a senha<input name="confirm_password" type="password" required minlength="12" autocomplete="new-password"></label>
        <div class="form-actions"><button class="button" type="submit">Criar usuário</button></div>
      </form>
    </section>
    <section class="panel section-gap">
      <h2>Contas cadastradas</h2>
      <div class="table-wrap"><table><thead><tr><th>Usuário</th><th>Perfil</th><th>Estado</th><th>Criado em</th></tr></thead><tbody>
      {% for user in users %}<tr><td>{{ user.username }}{% if user.id == current_user.id %}<small class="subline">Sua conta</small>{% endif %}</td><td>{% if user.is_admin %}Administrador{% else %}Usuário{% endif %}</td><td>{% if not user.is_active %}Inativo{% elif user.must_change_password %}Troca de senha pendente{% else %}Ativo{% endif %}</td><td>{{ user.created_at.strftime('%d/%m/%Y') }}</td></tr>{% endfor %}
      </tbody></table></div>
    </section>
  </main>
  <footer class="footer">Dados guardados no banco local · Acesso administrativo</footer>
</body>
</html>
```

## `docker-compose.yml`

```yaml
services:
  familia-financas:
    build: .
    container_name: familia-financas
    ports:
      - "8080:8080"
    volumes:
      - familia_financas_data:/data
    environment:
      TZ: America/Cuiaba
      DATABASE_URL: sqlite:////data/financas.db
      COOKIE_SECURE: "${COOKIE_SECURE:-true}"
      FORWARDED_ALLOW_IPS: "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
    command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "${FORWARDED_ALLOW_IPS:-127.0.0.1}"]
    restart: unless-stopped
volumes:
  familia_financas_data:
```

## `requirements.txt`

```text
fastapi==0.115.12
uvicorn[standard]==0.34.2
SQLAlchemy==2.0.40
Jinja2==3.1.6
python-multipart==0.0.20
pydantic==2.11.4
argon2-cffi==23.1.0
itsdangerous==2.2.0
```

## `start.sh`

```bash
#!/bin/sh
set -eu
# O volume já existia nas versões anteriores, então corrigimos proprietário e permissões ao iniciar.
mkdir -p /data
chown -R app:app /data
chmod 700 /data
find /data -maxdepth 1 -type f -exec chmod 600 {} \;
umask 077
exec gosu app "$@"
```

## `tests/test_auth_flow.py`

```python
"""Teste integrado de login, troca obrigatória de senha e controle de CSRF."""
import os
import re
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="casa-em-ordem-auth-test-"))
os.environ["DATABASE_URL"] = f"sqlite:////{str(_TEST_ROOT / 'test.db').lstrip('/')}"
os.environ["SESSION_SECRET_FILE"] = str(_TEST_ROOT / "session_secret.key")
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Person, CreditCard  # noqa: E402


def csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf" value="([^"]+)"', html)
    if not match:
        raise AssertionError("Token CSRF não encontrado no formulário")
    return match.group(1)


class AuthenticationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_admin_login_password_rotation_csrf_and_new_user(self):
        # A aplicação exige autenticação antes de exibir o dashboard.
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))

        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/login", data={
            "username": "Admin", "password": "admin", "next_url": "/", "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/alterar-senha", response.headers["location"])

        response = self.client.get("/alterar-senha")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/alterar-senha", data={
            "current_password": "admin",
            "new_password": "SenhaSeguraCasa2026!",
            "confirm_password": "SenhaSeguraCasa2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?ok=1")
        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('id="chart-cashflow"', dashboard.text)
        self.assertIn('class="sidebar"', dashboard.text)
        self.assertIn('data-theme="dark"', dashboard.text)

        # O cadastro armazena apenas os quatro últimos dígitos, exibidos no cartão visual.
        db = SessionLocal()
        try:
            husband = db.query(Person).filter(Person.name == "Marido").first()
            husband_id = husband.id
        finally:
            db.close()
        registration = self.client.get("/cadastros")
        token = csrf_token(registration.text)
        response = self.client.post("/cadastros/cartoes", data={
            "_csrf": token, "name": "Nubank Roxinho", "owner_id": str(husband_id),
            "kind": "credito", "closing_day": "10", "due_day": "17",
            "limit": "1500,00", "last_four_digits": "4821", "payment_account_id": "",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        card_page = self.client.get("/cartoes")
        self.assertEqual(card_page.status_code, 200)
        self.assertIn("bank-card-nubank", card_page.text)
        self.assertIn("4821", card_page.text)
        self.assertIn("Entradas x saídas", dashboard.text)

        # Um POST sem token CSRF é bloqueado mesmo com uma sessão autenticada.
        response = self.client.post("/usuarios", data={
            "username": "sem-token", "password": "SenhaSeguraUsuario2026!",
            "confirm_password": "SenhaSeguraUsuario2026!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/usuarios")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/usuarios", data={
            "username": "esposa",
            "password": "PrimeiraSenha2026!",
            "confirm_password": "PrimeiraSenha2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/usuarios?ok=1", response.headers["location"])

        response = self.client.post("/logout", data={"_csrf": token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.get("/login")
        token = csrf_token(response.text)
        response = self.client.post("/login", data={
            "username": "esposa", "password": "PrimeiraSenha2026!", "next_url": "/", "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/alterar-senha", response.headers["location"])
        response = self.client.get("/alterar-senha")
        token = csrf_token(response.text)
        response = self.client.post("/alterar-senha", data={
            "current_password": "PrimeiraSenha2026!",
            "new_password": "OutraSenhaSegura2026!",
            "confirm_password": "OutraSenhaSegura2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.get("/usuarios", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/?erro="))


if __name__ == "__main__":
    unittest.main()
```

## `tests/test_services.py`

```python
import unittest
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Person, Category, CreditCard, FixedExpense, FinancialTransaction, SavingsAccount, SavingsMovement
from app.seed import seed_database
from app.services.finance import parse_brl_to_cents, brl, invoice_due_date
from app.services.recurring import ensure_fixed_transactions
from app.services.finance import cashflow_date_for
from app.services.savings import savings_balance

class FinanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        seed_database(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_parse_and_format_brl_without_float(self):
        self.assertEqual(parse_brl_to_cents("1.234,56"), 123456)
        self.assertEqual(parse_brl_to_cents("1234.56"), 123456)
        self.assertEqual(brl(123456), "R$ 1.234,56")


    def test_seed_has_lazer_and_savings_without_old_motorcycle_categories(self):
        roots = set(self.db.scalars(select(Category.name).where(Category.parent_id.is_(None), Category.active.is_(True))).all())
        self.assertIn("Lazer", roots)
        self.assertIn("Poupança", roots)
        self.assertNotIn("Lazer/Moto", roots)
        self.assertEqual(self.db.scalar(select(Category.id).where(Category.name == "Lazer/Moto")), None)

    def test_legacy_motorcycle_categories_are_inactivated(self):
        legacy = Category(name="Lazer/Moto")
        self.db.add(legacy)
        self.db.flush()
        child = Category(name="Equipamentos Moto", parent_id=legacy.id)
        self.db.add(child)
        self.db.commit()
        seed_database(self.db)
        self.db.refresh(legacy)
        self.db.refresh(child)
        self.assertFalse(legacy.active)
        self.assertFalse(child.active)
        self.assertIsNotNone(self.db.scalar(select(Category.id).where(Category.name == "Lazer", Category.parent_id.is_(None), Category.active.is_(True))))

    def test_card_purchase_after_close_moves_to_next_cycle(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Marido"))
        card = CreditCard(name="Visa", owner_id=owner.id, closing_day=10, due_day=17, limit_cents=500000)
        self.db.add(card)
        self.db.commit()
        self.assertEqual(invoice_due_date(card, date(2026, 10, 9)), date(2026, 10, 17))
        self.assertEqual(invoice_due_date(card, date(2026, 10, 20)), date(2026, 11, 17))


    def test_debit_and_meal_voucher_use_purchase_date_without_invoice(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Marido"))
        for kind in ("debito", "vale_alimentacao"):
            card = CreditCard(name=f"Cartão {kind}", owner_id=owner.id, kind=kind, closing_day=0, due_day=0, limit_cents=0)
            self.db.add(card)
            self.db.flush()
            self.assertEqual(cashflow_date_for(self.db, card.id, date(2026, 10, 20)), date(2026, 10, 20))

    def test_savings_deposits_interest_and_withdrawal_change_capital_in_cents(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Esposa"))
        category = self.db.scalar(select(Category).where(Category.name == "Poupança", Category.parent_id.is_(None)))
        account = SavingsAccount(name="Reserva", person_id=owner.id, category_id=category.id, initial_balance_cents=10000)
        self.db.add(account)
        self.db.flush()
        self.db.add_all([
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 1), kind="deposito", amount_cents=2500),
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 2), kind="juros", amount_cents=37),
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 3), kind="retirada", amount_cents=1200),
        ])
        self.db.commit()
        self.assertEqual(savings_balance(self.db, account), 11337)

    def test_recurring_occurrences_are_idempotent_and_monthly(self):
        family = self.db.scalar(select(Person).where(Person.name == "Família"))
        category = self.db.scalar(select(Category).where(Category.name == "Mensalidade"))
        fixed = FixedExpense(name="Colégio", amount_cents=125000, day_of_month=10, category_id=category.id,
                             person_id=family.id, start_date=date(2026, 10, 1), active=True)
        self.db.add(fixed)
        self.db.commit()
        first_count = ensure_fixed_transactions(self.db, date(2026, 10, 20), months_ahead=2)
        second_count = ensure_fixed_transactions(self.db, date(2026, 10, 20), months_ahead=2)
        rows = list(self.db.scalars(select(FinancialTransaction).where(FinancialTransaction.fixed_expense_id == fixed.id)).all())
        self.assertEqual(first_count, 3)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.occurrence_month.month for row in sorted(rows, key=lambda row: row.occurrence_month)], [10, 11, 12])

if __name__ == "__main__":
    unittest.main()
```
