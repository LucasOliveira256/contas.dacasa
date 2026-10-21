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

app = FastAPI(title="Casa em Ordem", description="Gestão financeira familiar", version="1.1.0", lifespan=lifespan)
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
