from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from .database import Base, engine, SessionLocal, migrate_database
from . import models  # registra os mapeamentos antes do create_all
from .seed import seed_database
from .services.recurring import ensure_fixed_transactions
from .routers import dashboard, transactions, registrations, incomes, cards, budgets, reports, savings

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

app = FastAPI(title="Finanças da Família", description="Controle financeiro familiar local", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(dashboard.router)
app.include_router(transactions.router)
app.include_router(registrations.router)
app.include_router(incomes.router)
app.include_router(cards.router)
app.include_router(budgets.router)
app.include_router(reports.router)
app.include_router(savings.router)
