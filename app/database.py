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
        if "kind" not in columns:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE credit_cards ADD COLUMN kind VARCHAR(30) NOT NULL DEFAULT 'credito'"))
    # create_all adiciona as novas tabelas de poupança sem alterar tabelas antigas.
    Base.metadata.create_all(bind=engine)
