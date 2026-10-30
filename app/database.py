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
    # Receitas recorrentes: colunas nulas, então linhas antigas continuam avulsas.
    if "incomes" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("incomes")}
        with engine.begin() as connection:
            if "recurring_income_id" not in columns:
                connection.execute(text("ALTER TABLE incomes ADD COLUMN recurring_income_id INTEGER REFERENCES recurring_incomes(id) ON DELETE SET NULL"))
            if "occurrence_month" not in columns:
                connection.execute(text("ALTER TABLE incomes ADD COLUMN occurrence_month DATE"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_income_recurring_occurrence ON incomes (recurring_income_id, occurrence_month)"))
    # Permite invalidar sessões antigas ao trocar a senha.
    if "users" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "session_version" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE users ADD COLUMN session_version INTEGER NOT NULL DEFAULT 0"))
    # create_all adiciona tabelas novas sem alterar os dados financeiros antigos.
    Base.metadata.create_all(bind=engine)
