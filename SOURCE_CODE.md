# Código-fonte completo — Casa em ordem

Versão atualizada com edição/exclusão de pessoas, categorias, cartões de débito/Vale Alimentação e gestão de poupança. Cada seção contém o arquivo integral correspondente.


## `.dockerignore`

````text
__pycache__/
*.py[cod]
*.db
*.sqlite3
.venv/
.git/
tests/
````


## `Dockerfile`

````text
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Cuiaba DATABASE_URL=sqlite:////data/financas.db
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
````


## `README.md`

````text
# Casa em ordem — Finanças da família

Aplicação web local para organizar receitas, despesas, cartões, orçamento, projeções e poupanças pessoais. Não exige autenticação nem serviço externo durante o uso. O banco SQLite fica no volume persistente `/data`.

## Executar

```bash
docker compose up -d --build
```

Abra `http://IP-DO-SERVIDOR:8080` na rede local. No próprio servidor, use `http://localhost:8080`.

Para parar sem apagar os dados:

```bash
docker compose down
```

Depois, `docker compose up -d` volta a usar o mesmo volume. Para ver logs: `docker compose logs -f familia-financas`.

## Alterações nesta versão

- Pessoas podem ser editadas ou excluídas; pessoas que já aparecem no histórico são inativadas para preservar os lançamentos.
- Categorias podem ser excluídas. As excluídas saem dos formulários novos; o histórico antigo continua ligado à categoria inativa. A taxonomia `Lazer/Moto` é migrada para `Lazer`, com as subcategorias antigas inativadas.
- Descontos em folha têm os tipos Plano de saúde, INSS, IR, Vale e Outros. São informativos e não entram novamente no fluxo de caixa.
- Cartões têm tipos Crédito, Débito e Vale Alimentação. Só os cartões de crédito têm dias de fechamento/vencimento e fatura; os lançamentos de débito e vale usam a data da compra e não permitem parcelamento.
- A página **Poupança** permite criar contas de capital por pessoa, registrar depósitos, retiradas e juros de aplicações. O capital é calculado em centavos; retirada acima do saldo é recusada. O saldo inicial é informado ao criar a poupança.

## Regras importantes

- Valores financeiros são armazenados e calculados como centavos inteiros. O formulário aceita, por exemplo, `1.234,56`.
- A compra no cartão de crédito é classificada por sua data original para relatórios por categoria; a saída do caixa cai na data de vencimento da fatura. O cartão não gera uma segunda despesa de pagamento.
- Compra parcelada recebe uma linha por parcela/fatura; os centavos restantes são distribuídos nas primeiras parcelas para que a soma permaneça idêntica ao total da compra.
- Gastos fixos geram ocorrências mensais por até 12 meses à frente e não duplicam ocorrências já existentes. Edite uma ocorrência em **Gastos** para ajustar só aquele mês.
- Depósitos, retiradas e juros na página **Poupança** compõem um livro auxiliar de capital, separado de despesas/receitas do orçamento doméstico; assim, transferir dinheiro para a poupança não é contado como consumo.
- Plano de saúde, INSS, IR e demais descontos em folha ficam informativos e não entram como uma segunda despesa nem reduzem novamente o salário. Cadastre como salário o valor líquido que efetivamente entra na conta.
- A projeção considera as receitas cadastradas nas datas correspondentes. Ela não presume salários futuros automaticamente; lance as entradas futuras para vê-las na projeção.
- O backup usa o mecanismo de backup do SQLite para gerar um arquivo consistente, inclusive quando o banco está em uso.

## Arquitetura e operação

- Python 3.12, FastAPI, SQLAlchemy, SQLite, Jinja2 e templates responsivos.
- As tabelas são criadas na primeira execução. Categorias e pessoas iniciais são inseridas de forma idempotente; o banco existente recebe uma migração aditiva para o tipo do cartão, e novas tabelas de poupança são criadas sem apagar dados.
- Fuso horário do container: `America/Cuiaba`.
- Sem CDN: os gráficos são desenhados em canvas por um renderizador JavaScript local, e o adaptador HTMX usado em uma tela é local. O ambiente de geração não tinha acesso à rede para baixar as distribuições oficiais de Chart.js e HTMX; esses arquivos oficiais não estão embutidos. As telas e quatro gráficos continuam funcionando offline com as implementações locais incluídas, mas não são as distribuições upstream dessas bibliotecas.

## Segurança e rede

A aplicação não tem autenticação conforme solicitado. Exponha a porta 8080 apenas na rede confiável; não publique diretamente na internet.
````


## `app/__init__.py`

````text
"""Gestão financeira familiar."""
````


## `app/database.py`

````text
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
````


## `app/main.py`

````text
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
````


## `app/models.py`

````text
from datetime import date, datetime
from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base

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
````


## `app/routers/__init__.py`

````text
"""Rotas HTTP da aplicação."""
````


## `app/routers/budgets.py`

````text
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
````


## `app/routers/cards.py`

````text
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
    cards = list(db.scalars(select(CreditCard).where(CreditCard.active.is_(True), CreditCard.kind == "credito").order_by(CreditCard.name)).all())
    selected_card = next((c for c in cards if c.id == cartao), cards[0] if cards else None)
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
    for card in cards:
        amount = sum(t.amount_cents for t in items if t.card_id == card.id) if selected_card and card.id == selected_card.id else 0
        card_totals.append({"card": card, "amount": amount})
    return page(request, db, "cards.html", active_nav="cartoes", mes=f"{year:04d}-{month:02d}", all_cards=cards,
                selected_card=selected_card, items=items, total=total, card_totals=card_totals)
````


## `app/routers/common.py`

````text
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
    context = {"request": request, "today": date.today(), "erro": request.query_params.get("erro"), "ok": request.query_params.get("ok"), "people": people,
               "categories": categories, "category_options": category_options,
               "accounts": accounts, "cards": cards, "active_nav": "", **extra}
    return context

def page(request: Request, db: Session, template: str, **extra):
    return templates.TemplateResponse(request=request, name=template, context=base_context(request, db, **extra))
````


## `app/routers/dashboard.py`

````text
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
````


## `app/routers/incomes.py`

````text
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
````


## `app/routers/registrations.py`

````text
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
    limit: str = Form("0,00"), payment_account_id: str = Form(""), db: Session = Depends(get_db),
):
    clean = name.strip()
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
            limit_cents=parse_brl_to_cents(limit),
            payment_account_id=int(payment_account_id) if payment_account_id else None,
        ))
        db.commit()
    except (ValueError, TypeError, IntegrityError) as exc:
        db.rollback()
        msg = str(exc) if isinstance(exc, ValueError) else "Não foi possível salvar o cartão"
        return RedirectResponse(f"/cadastros?erro={msg.replace(' ', '+')}", status_code=303)
    return RedirectResponse("/cadastros?ok=1", status_code=303)
````


## `app/routers/reports.py`

````text
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
````


## `app/routers/savings.py`

````text
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
````


## `app/routers/transactions.py`

````text
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
````


## `app/schemas.py`

````text
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
````


## `app/seed.py`

````text
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Person, Category

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
````


## `app/services/__init__.py`

````text
"""Regras de negócio."""
````


## `app/services/finance.py`

````text
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
````


## `app/services/recurring.py`

````text
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
````


## `app/services/savings.py`

````text
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
````


## `app/static/css/app.css`

````text
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
.nav-grid { display: grid; grid-template-columns: repeat(11, minmax(0, 1fr)); gap: 4px; padding: 8px max(12px, calc((100vw - 1240px) / 2)); background: #fff; border-bottom: 1px solid var(--line); }
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
````


## `app/static/js/app.js`

````text
(() => {
  function renderCharts() {
    const dataNode = document.getElementById("chart-data");
    if (!dataNode || !window.FamilyCharts) return;
    try { window.FamilyCharts.render(JSON.parse(dataNode.textContent)); }
    catch (error) { console.error("Não foi possível renderizar os gráficos locais.", error); }
  }
  document.addEventListener("DOMContentLoaded", renderCharts);
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderCharts, 140);
  });
})();
````


## `app/static/js/htmx-lite.js`

````text
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
````


## `app/static/js/local-charts.js`

````text
/* Renderizador local de canvas para gráficos offline. Interface limitada ao uso desta aplicação. */
(() => {
  const palette = ["#236b56", "#e2a348", "#547bba", "#ba6d58", "#8d7ab8", "#63a6a1", "#d477a8", "#8a9b65", "#7b8794", "#c4a75b"];
  const money = cents => {
    const value = (Number(cents || 0) / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL", maximumFractionDigits: 0 });
    return value;
  };
  function setup(canvas) {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(280, Math.floor(rect.width || 340));
    const height = Math.max(220, Math.floor(rect.height || 260));
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    const ctx = canvas.getContext("2d"); ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.font = "11px system-ui, sans-serif"; ctx.fillStyle = "#69756f"; ctx.strokeStyle = "#e4e9e5";
    return { ctx, width, height };
  }
  const shorten = (text, size = 12) => String(text).length > size ? String(text).slice(0, size - 1) + "…" : String(text);
  function legend(ctx, items, x, y, maxWidth) {
    let cx = x, cy = y;
    items.forEach((item, index) => {
      const label = String(item.label || ""); const needed = 20 + Math.min(124, ctx.measureText(label).width);
      if (cx + needed > x + maxWidth && cx !== x) { cx = x; cy += 18; }
      ctx.fillStyle = item.color || palette[index % palette.length]; ctx.fillRect(cx, cy - 8, 9, 9);
      ctx.fillStyle = "#4f5e56"; ctx.fillText(shorten(label, 22), cx + 13, cy);
      cx += needed + 8;
    });
  }
  function drawPie(canvas, payload) {
    const { ctx, width, height } = setup(canvas); const values = payload.data || []; const labels = payload.labels || [];
    const total = values.reduce((a, b) => a + Number(b), 0);
    if (!total) return false;
    const cx = width / 2, cy = height * 0.30, radius = Math.min(width * 0.30, height * 0.27);
    let angle = -Math.PI / 2;
    values.forEach((v, i) => {
      const next = angle + Math.PI * 2 * Number(v) / total;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, radius, angle, next); ctx.closePath();
      ctx.fillStyle = palette[i % palette.length]; ctx.fill(); angle = next;
    });
    ctx.beginPath(); ctx.arc(cx, cy, radius * 0.58, 0, Math.PI * 2); ctx.fillStyle = "#fff"; ctx.fill();
    ctx.textAlign = "center"; ctx.fillStyle = "#1e3c31"; ctx.font = "700 14px system-ui"; ctx.fillText(money(total), cx, cy + 4);
    ctx.textAlign = "left"; ctx.font = "11px system-ui";
    const legendItems = labels.map((label, i) => ({ label: `${label}: ${money(values[i])}`, color: palette[i % palette.length] }));
    const colWidth = width > 400 ? width / 2 - 14 : width - 22; let y = height * 0.62;
    legendItems.slice(0, 7).forEach((item, i) => {
      const col = width > 400 ? i % 2 : 0; const row = width > 400 ? Math.floor(i / 2) : i;
      ctx.fillStyle = item.color; ctx.fillRect(10 + col * (colWidth + 8), y + row * 16 - 8, 8, 8);
      ctx.fillStyle = "#53635b"; ctx.fillText(shorten(item.label, width > 400 ? 36 : 34), 23 + col * (colWidth + 8), y + row * 16);
    });
    return true;
  }
  function axes(ctx, width, height, plot, max) {
    ctx.strokeStyle = "#e5eae6"; ctx.fillStyle = "#78837d"; ctx.font = "10px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) {
      const y = plot.top + (plot.height * i / 4); ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke();
      const value = max * (1 - i / 4); ctx.fillText(value === 0 ? "0" : (Math.abs(value) >= 100000 ? `${Math.round(value / 100000) / 10} mi` : `${Math.round(value / 1000)} mil`), plot.left - 7, y + 3);
    }
  }
  function drawBars(canvas, labels, series, stacked = false) {
    const { ctx, width, height } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 44, right: 8, top: 15, bottom: 40 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    let max = 0;
    labels.forEach((_, i) => { const vals = series.map(s => Number(s.data[i] || 0)); max = Math.max(max, stacked ? vals.reduce((a, b) => a + b, 0) : Math.max(...vals)); });
    max = max || 100; axes(ctx, width, height, plot, max * 1.08);
    const groupWidth = plot.width / labels.length; const inner = groupWidth * .72; const barWidth = Math.max(2, inner / (stacked ? 1 : series.length) - 3);
    labels.forEach((label, i) => {
      let stackedHeight = 0;
      series.forEach((s, j) => {
        const val = Number(s.data[i] || 0); const h = val / (max * 1.08) * plot.height;
        const x = plot.left + i * groupWidth + (groupWidth - inner) / 2 + (stacked ? 0 : j * (barWidth + 3));
        const y = plot.top + plot.height - (stacked ? stackedHeight + h : h);
        ctx.fillStyle = s.color || palette[j % palette.length]; ctx.fillRect(x, y, barWidth, h);
        if (stacked) stackedHeight += h;
      });
      ctx.save(); ctx.translate(plot.left + i * groupWidth + groupWidth / 2, height - 22); ctx.rotate(labels.length > 8 ? -0.55 : 0);
      ctx.textAlign = labels.length > 8 ? "right" : "center"; ctx.fillStyle = "#69756f"; ctx.fillText(shorten(label, 9), 0, 0); ctx.restore();
    });
    legend(ctx, series.map((s, i) => ({ label: s.label, color: s.color || palette[i % palette.length] })), plot.left, height - 4, plot.width);
  }
  function drawLine(canvas, labels, values) {
    const { ctx, width, height } = setup(canvas); if (!labels || !labels.length) return;
    const plot = { left: 45, right: 10, top: 17, bottom: 40 }; plot.width = width - plot.left - plot.right; plot.height = height - plot.top - plot.bottom;
    const min = Math.min(0, ...values), max = Math.max(1, ...values), range = max - min || 1;
    ctx.strokeStyle = "#e5eae6"; ctx.fillStyle = "#78837d"; ctx.font = "10px system-ui"; ctx.textAlign = "right";
    for (let i = 0; i <= 4; i++) { const y = plot.top + plot.height * i / 4; ctx.beginPath(); ctx.moveTo(plot.left, y); ctx.lineTo(width - plot.right, y); ctx.stroke(); const val = max - (range * i / 4); ctx.fillText(`${Math.round(val / 1000)} mil`, plot.left - 7, y + 3); }
    ctx.beginPath(); values.forEach((v, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); const y = plot.top + (max - v) / range * plot.height; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
    ctx.strokeStyle = "#236b56"; ctx.lineWidth = 2.5; ctx.stroke();
    values.forEach((v, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); const y = plot.top + (max - v) / range * plot.height; ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fillStyle = "#236b56"; ctx.fill(); });
    labels.forEach((label, i) => { const x = plot.left + (labels.length === 1 ? plot.width / 2 : i * plot.width / (labels.length - 1)); ctx.fillStyle = "#69756f"; ctx.textAlign = "center"; ctx.fillText(shorten(label, 9), x, height - 21); });
  }
  window.FamilyCharts = {
    render(payload) {
      const pie = document.getElementById("chart-pie");
      if (pie) { const ok = drawPie(pie, payload.pie || {}); const empty = document.getElementById("pie-empty"); if (empty) empty.hidden = ok; }
      const bars = document.getElementById("chart-bars");
      if (bars) drawBars(bars, payload.bars.labels, [
        { label: "Receitas", data: payload.bars.income, color: "#236b56" },
        { label: "Despesas", data: payload.bars.expense, color: "#e2a348" }
      ]);
      const line = document.getElementById("chart-line"); if (line) drawLine(line, payload.line.labels, payload.line.data);
      const cards = document.getElementById("chart-cards");
      if (cards) drawBars(cards, payload.cards.labels, (payload.cards.datasets || []).map((s, i) => ({ ...s, color: palette[i % palette.length] })), true);
    }
  };
})();
````


## `app/templates/base.html`

````text
<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#12352d">
  <title>{% block title %}Finanças da Família{% endblock %}</title>
  <link rel="stylesheet" href="/static/css/app.css">
  <script defer src="/static/js/htmx-lite.js"></script>
  <script defer src="/static/js/local-charts.js"></script>
  <script defer src="/static/js/app.js"></script>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="Página inicial"><span class="brand-mark">R$</span><span>Casa em ordem<small>Finanças da família</small></span></a>
    <span class="top-date">{{ today.strftime('%d/%m/%Y') }}</span>
  </header>
  <nav class="nav-grid" aria-label="Navegação principal">
    <a class="nav-item {% if active_nav == 'dashboard' %}active{% endif %}" href="/">Visão geral</a>
    <a class="nav-item {% if active_nav == 'transacoes' %}active{% endif %}" href="/transacoes">Gastos</a>
    <a class="nav-item {% if active_nav == 'fixos' %}active{% endif %}" href="/transacoes/fixos">Gastos fixos</a>
    <a class="nav-item {% if active_nav == 'planejados' %}active{% endif %}" href="/planejados">Planejados</a>
    <a class="nav-item {% if active_nav == 'receitas' %}active{% endif %}" href="/receitas">Receitas</a>
    <a class="nav-item {% if active_nav == 'cartoes' %}active{% endif %}" href="/cartoes">Faturas</a>
    <a class="nav-item {% if active_nav == 'poupanca' %}active{% endif %}" href="/poupanca">Poupança</a>
    <a class="nav-item {% if active_nav == 'orcamento' %}active{% endif %}" href="/orcamento">Orçamento</a>
    <a class="nav-item {% if active_nav == 'projecao' %}active{% endif %}" href="/projecao">Projeção</a>
    <a class="nav-item {% if active_nav == 'historico' %}active{% endif %}" href="/historico">Histórico</a>
    <a class="nav-item {% if active_nav == 'relatorios' %}active{% endif %}" href="/relatorios">Relatórios</a>
    <a class="nav-item {% if active_nav == 'cadastros' %}active{% endif %}" href="/cadastros">Cadastros</a>
  </nav>
  <main class="container">
    {% if erro %}<div class="notice error" role="alert">{{ erro }}</div>{% endif %}
    {% if ok %}<div class="notice success">Alterações salvas.</div>{% endif %}
    {% block content %}{% endblock %}
  </main>
  <footer class="footer">Dados guardados localmente neste dispositivo/rede · Valores em reais (BRL)</footer>
</body>
</html>
````


## `app/templates/budgets.html`

````text
{% extends "base.html" %}
{% block title %}Orçamento mensal · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CONTROLE DO PLANEJADO</p><h1>Orçamento mensal</h1><p class="muted">O gasto contabilizado no orçamento é classificado pela data da compra e pelo status realizado.</p></div></section>
<form class="filter-bar" method="get"><label for="mes">Mês</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light">Ver mês</button></form>
<form class="panel form-panel" method="post" action="/orcamento"><h2>Definir orçamento por categoria</h2><div class="form-grid"><input type="hidden" name="mes" value="{{ mes }}"><label class="field">Categoria<select name="category_id" required>{% for c in category_options %}<option value="{{ c.id }}">{{ c.label }}</option>{% endfor %}</select></label><label class="field">Valor mensal (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label></div><div class="form-actions"><button class="button" type="submit">Salvar orçamento</button></div></form>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Categoria</th><th>Orçamento</th><th>Realizado</th><th>Uso</th><th></th></tr></thead><tbody>{% for row in rows %}<tr><td>{{ row.label }}</td><td>{{ row.budget.amount_cents|brl }}</td><td>{{ row.spent|brl }}</td><td><div class="budget-cell"><div class="progress"><span class="{% if row.over %}over{% endif %}" style="width:{{ row.percent if row.percent < 100 else 100 }}%"></span></div><small class="{% if row.over %}danger-text{% endif %}">{{ row.percent }}%{% if row.over %} · excedido{% endif %}</small></div></td><td><form method="post" action="/orcamento/{{ row.budget.id }}/excluir" onsubmit="return confirm('Excluir este orçamento?')"><button class="text-button danger-text">Excluir</button></form></td></tr>{% else %}<tr><td colspan="5" class="empty-cell">Nenhum orçamento cadastrado neste mês.</td></tr>{% endfor %}</tbody></table></div></section>
{% endblock %}
````


## `app/templates/cards.html`

````text
{% extends "base.html" %}
{% block title %}Faturas de cartão · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CARTÕES DE CRÉDITO</p><h1>Faturas</h1><p class="muted">A fatura é agrupada pelo vencimento calculado a partir da data de fechamento.</p></div><a class="button button-light" href="/cadastros">Gerenciar cartões</a></section>
<form class="filter-bar" method="get"><label for="mes">Mês do vencimento</label><input id="mes" type="month" name="mes" value="{{ mes }}"><label for="cartao">Cartão</label><select id="cartao" name="cartao"><option value="">Selecione cartão</option>{% for c in all_cards %}<option value="{{ c.id }}" {% if selected_card and selected_card.id == c.id %}selected{% endif %}>{{ c.name }} · {{ c.owner.name }}</option>{% endfor %}</select><button class="button button-light">Ver fatura</button></form>
{% if selected_card %}<section class="metric-grid metric-grid-two"><article class="metric"><span>Cartão / titular</span><strong>{{ selected_card.name }}</strong><small>{{ selected_card.owner.name }} · fecha dia {{ selected_card.closing_day }} · vence dia {{ selected_card.due_day }}</small></article><article class="metric"><span>Total previsto da fatura</span><strong>{{ total|brl }}</strong><small>Limite cadastrado: {{ selected_card.limit_cents|brl }}</small></article></section>
<section class="panel"><div class="panel-heading"><div><h2>Itens da fatura — {{ mes[5:7] }}/{{ mes[:4] }}</h2><p class="muted">Os lançamentos usam a data da compra nos relatórios de categoria.</p></div></div><div class="table-wrap"><table><thead><tr><th>Vencimento</th><th>Compra / descrição</th><th>Categoria</th><th>Responsável</th><th>Status</th><th>Valor</th><th></th></tr></thead><tbody>{% for item in items %}<tr><td>{{ item.cashflow_date|date_br }}</td><td>{{ item.purchase_date|date_br }}<small class="subline">{{ item.description }}</small>{% if item.installment_number %}<small class="subline">Parcela {{ item.installment_number }}/{{ item.installment_count }}</small>{% endif %}</td><td>{{ item.category.name }}</td><td>{{ item.person.name }}</td><td><span class="status status-{{ item.status }}">{{ item.status }}</span></td><td class="money">{{ item.amount_cents|brl }}</td><td><a class="text-link" href="/transacoes/{{ item.id }}/editar">Editar</a></td></tr>{% else %}<tr><td colspan="7" class="empty-cell">Nenhuma compra nesta fatura.</td></tr>{% endfor %}</tbody><tfoot><tr><th colspan="5">Total da fatura</th><th>{{ total|brl }}</th><th></th></tr></tfoot></table></div></section>{% else %}<div class="empty-state">Cadastre um cartão em Cadastros para consultar faturas.</div>{% endif %}
{% endblock %}
````


## `app/templates/dashboard.html`

````text
{% extends "base.html" %}
{% block title %}Visão geral · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head">
  <div><p class="eyebrow">PAINEL FAMILIAR</p><h1>Visão geral</h1><p class="muted">Receitas e compromissos de {{ '%02d'|format(month) }}/{{ year }}</p></div>
  <form class="month-form" method="get" action="/"><label for="mes">Mês</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button" type="submit">Ver mês</button></form>
</section>
<section class="metric-grid">
  <article class="metric"><span>Receitas no fluxo</span><strong>{{ income_total|brl }}</strong><small>{{ income_count }} lançamento(s)</small></article>
  <article class="metric"><span>Despesas previstas no caixa</span><strong>{{ expense_total|brl }}</strong><small>{{ expense_count }} lançamento(s), cartão pelo vencimento</small></article>
  <article class="metric {% if balance < 0 %}metric-danger{% else %}metric-good{% endif %}"><span>Saldo previsto do mês</span><strong>{{ balance|brl }}</strong><small>Receitas menos compromissos</small></article>
  <article class="metric"><span>Orçamento já usado</span><strong>{% if budget_total %}{{ (actual_budgeted * 100 // budget_total) }}%{% else %}—{% endif %}</strong><small>{{ actual_budgeted|brl }} de {{ budget_total|brl }}</small></article>
</section>
<section class="section-heading"><div><h2>Comparação com o mês anterior</h2><p class="muted">Fluxo de caixa estimado no mesmo critério</p></div></section>
<div class="compare-grid">
  <div class="compare-card"><span>Receitas anteriores</span><b>{{ prev_income|brl }}</b><small>Saldo atual de receitas: {{ (income_total - prev_income)|brl }} de diferença</small></div>
  <div class="compare-card"><span>Despesas anteriores</span><b>{{ prev_expense|brl }}</b><small>Saldo anterior: {{ prev_balance|brl }}</small></div>
</div>
<section class="section-heading"><div><h2>Visão por gráficos</h2><p class="muted">Gráficos locais; funcionam sem internet.</p></div></section>
<section class="chart-grid">
  <article class="panel chart-panel"><h3>Despesas por categoria</h3><p class="muted">Compras realizadas na data selecionada</p><div class="chart-wrap"><canvas id="chart-pie" aria-label="Despesas por categoria"></canvas></div><p class="empty-hint" id="pie-empty" hidden>Sem despesas realizadas neste mês.</p></article>
  <article class="panel chart-panel"><h3>Receitas x despesas</h3><p class="muted">Últimos 12 meses pelo fluxo de caixa</p><div class="chart-wrap"><canvas id="chart-bars" aria-label="Receitas comparadas com despesas"></canvas></div></article>
  <article class="panel chart-panel"><h3>Evolução do saldo</h3><p class="muted">Saldo acumulado relativo dos 12 meses</p><div class="chart-wrap"><canvas id="chart-line" aria-label="Evolução do saldo acumulado"></canvas></div></article>
  <article class="panel chart-panel"><h3>Faturas por cartão</h3><p class="muted">Compromissos por mês de vencimento · 6 meses</p><div class="chart-wrap"><canvas id="chart-cards" aria-label="Despesas por cartão"></canvas></div></article>
</section>
<section class="content-grid section-gap">
  <article class="panel"><div class="panel-heading"><div><h2>Próximos vencimentos</h2><p class="muted">Até 45 dias · sem duplicar fatura</p></div><a class="text-link" href="/planejados">Ver planejados</a></div>
    <div id="upcoming-list" hx-get="/partials/proximos" hx-trigger="load" hx-swap="innerHTML"><p class="muted">Carregando vencimentos…</p></div>
  </article>
  <article class="panel"><div class="panel-heading"><div><h2>Orçamento por categoria</h2><p class="muted">Considera gastos realizados na data da compra</p></div><a class="text-link" href="/orcamento?mes={{ mes }}">Gerenciar</a></div>
    {% if budget_rows %}<div class="budget-list">{% for item in budget_rows %}<div class="budget-row"><div class="row-between"><span>{{ item.name }}</span><strong>{{ item.spent|brl }} / {{ item.amount|brl }}</strong></div><div class="progress"><span class="{% if item.over %}over{% endif %}" style="width:{{ item.percent if item.percent < 100 else 100 }}%"></span></div><small class="{% if item.over %}danger-text{% else %}muted{% endif %}">{% if item.over %}Orçamento excedido em {{ (item.spent-item.amount)|brl }}{% else %}{{ item.percent }}% utilizado{% endif %}</small></div>{% endfor %}</div>{% else %}<div class="empty-state">Nenhum orçamento cadastrado para este mês. <a href="/orcamento?mes={{ mes }}">Criar orçamento</a></div>{% endif %}
  </article>
</section>
<section class="panel"><div class="panel-heading"><div><h2>Categorias com maior gasto</h2><p class="muted">Variação comparada ao mês anterior</p></div><a class="text-link" href="/historico?mes={{ mes }}">Resumo do mês</a></div>
  {% if ranking %}<div class="table-wrap"><table><thead><tr><th>Categoria</th><th>Este mês</th><th>Mês anterior</th><th>Variação</th></tr></thead><tbody>{% for item in ranking %}<tr><td>{{ item.name }}</td><td>{{ item.amount|brl }}</td><td>{{ item.previous|brl }}</td><td><span class="change {% if item.delta > 0 %}danger-text{% elif item.delta < 0 %}good-text{% endif %}">{% if item.delta > 0 %}+{% endif %}{{ item.delta }}%</span></td></tr>{% endfor %}</tbody></table></div>{% else %}<p class="empty-state">Registre despesas realizadas para montar o ranking.</p>{% endif %}
</section>
<script id="chart-data" type="application/json">{{ chart_payload|tojson }}</script>
{% endblock %}
````


## `app/templates/fixed.html`

````text
{% extends "base.html" %}
{% block title %}Gastos fixos · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">RECORRÊNCIA MENSAL</p><h1>Gastos fixos</h1><p class="muted">Ocorrências são criadas automaticamente até 12 meses à frente. Ajuste um mês específico em Gastos, sem alterar os demais.</p></div></section>
<form class="panel form-panel" method="post" action="/transacoes/fixos"><h2>Novo gasto recorrente</h2><div class="form-grid">
<label class="field field-wide">Descrição<input name="name" required placeholder="Ex.: mensalidade do colégio"></label><label class="field">Valor mensal (R$)<input name="amount" required inputmode="decimal" placeholder="0,00"></label><label class="field">Dia do mês<input type="number" name="day_of_month" min="1" max="31" value="10" required></label>
<label class="field">Categoria<select name="category_id" required>{% for c in category_options %}<option value="{{ c.id }}">{{ c.label }}</option>{% endfor %}</select></label><label class="field">Responsável<select name="person_id" required>{% for p in people %}<option value="{{ p.id }}" {% if p.name == 'Família' %}selected{% endif %}>{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Início da vigência<input type="date" name="start_date" value="{{ today.isoformat() }}" required></label><label class="field">Fim da vigência (opcional)<input type="date" name="end_date"></label>
<label class="field">Conta<select name="account_id"><option value="">Nenhuma / dinheiro</option>{% for a in accounts %}<option value="{{ a.id }}">{{ a.name }}</option>{% endfor %}</select></label><label class="field">Cartão<select name="card_id"><option value="">Não usar cartão</option>{% for c in cards %}<option value="{{ c.id }}">{{ c.name }} · {{ c.owner.name }}</option>{% endfor %}</select></label>
</div><div class="form-actions"><button class="button" type="submit">Criar recorrência</button></div></form>
<section class="section-heading"><div><h2>Recorrências cadastradas</h2><p class="muted">Editar a recorrência afeta a regra, não os lançamentos já gerados.</p></div></section>
{% if fixed_items %}<div class="stack-list">{% for item in fixed_items %}<details class="panel fixed-item"><summary><span><b>{{ item.name }}</b><small>{{ item.category.name }} · dia {{ item.day_of_month }} · {{ item.person.name }}</small></span><span class="summary-end"><b>{{ item.amount_cents|brl }}</b><span class="status {% if item.active %}status-realizado{% else %}status-cancelado{% endif %}">{% if item.active %}ativa{% else %}inativa{% endif %}</span></span></summary>
<form method="post" action="/transacoes/fixos/{{ item.id }}/editar" class="form-grid compact-form">
<label class="field field-wide">Descrição<input name="name" required value="{{ item.name }}"></label><label class="field">Valor (R$)<input name="amount" required value="{{ item.amount_cents|brl }}"></label><label class="field">Dia<input name="day_of_month" type="number" min="1" max="31" value="{{ item.day_of_month }}"></label>
<label class="field">Categoria<select name="category_id">{% for c in category_options %}<option value="{{ c.id }}" {% if c.id == item.category_id %}selected{% endif %}>{{ c.label }}</option>{% endfor %}</select></label><label class="field">Responsável<select name="person_id">{% for p in people %}<option value="{{ p.id }}" {% if p.id == item.person_id %}selected{% endif %}>{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Início<input name="start_date" type="date" value="{{ item.start_date.isoformat() }}"></label><label class="field">Fim<input name="end_date" type="date" value="{{ item.end_date.isoformat() if item.end_date else '' }}"></label>
<label class="field">Conta<select name="account_id"><option value="">Nenhuma / dinheiro</option>{% for a in accounts %}<option value="{{ a.id }}" {% if item.account_id == a.id %}selected{% endif %}>{{ a.name }}</option>{% endfor %}</select></label><label class="field">Cartão<select name="card_id"><option value="">Não usar cartão</option>{% for c in cards %}<option value="{{ c.id }}" {% if item.card_id == c.id %}selected{% endif %}>{{ c.name }}</option>{% endfor %}</select></label>
<label class="field">Situação<select name="active"><option value="sim" {% if item.active %}selected{% endif %}>Ativa</option><option value="nao" {% if not item.active %}selected{% endif %}>Inativa</option></select></label><div class="form-actions"><button class="button button-small" type="submit">Salvar regra</button></div>
</form></details>{% endfor %}</div>{% else %}<div class="empty-state">Cadastre aqui colégio, internet, seguro e outros compromissos mensais.</div>{% endif %}
{% endblock %}
````


## `app/templates/history.html`

````text
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
````


## `app/templates/incomes.html`

````text
{% extends "base.html" %}
{% block title %}Receitas · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">ENTRADAS E DESCONTOS</p><h1>Receitas</h1><p class="muted">Plano de saúde, INSS e IR em folha são informativos e não entram novamente nas despesas.</p></div></section>
<section class="metric-grid metric-grid-two"><article class="metric metric-good"><span>Receitas incluídas no caixa</span><strong>{{ cash_total|brl }}</strong><small>Salários e rendas extras lançados no mês</small></article><article class="metric"><span>Descontos em folha informativos</span><strong>{{ deductions|brl }}</strong><small>Não duplicados como despesa</small></article></section>
<form class="filter-bar" method="get"><label for="mes">Mês</label><input id="mes" type="month" name="mes" value="{{ mes }}"><button class="button button-light" type="submit">Filtrar</button></form>
<form class="panel form-panel" method="post" action="/receitas"><h2>Adicionar receita ou desconto</h2><div class="form-grid">
<label class="field">Data<input type="date" name="happened_on" value="{{ today.isoformat() }}" required></label><label class="field">Pessoa<select name="person_id" required>{% for p in people if p.name != 'Família' %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
<label class="field">Tipo<select name="kind" required><option value="salario">Salário</option><option value="extra">Renda extra</option><optgroup label="Desconto em folha"><option value="plano_saude">Plano de saúde</option><option value="inss">INSS</option><option value="ir">IR</option><option value="vale">Vale</option><option value="outros_desconto">Outros</option></optgroup><option value="vale">Vale descontado em folha</option><option value="outros_desconto">Outros descontos em folha</option></select></label>
<label class="field">Valor (R$)<input name="amount" inputmode="decimal" placeholder="0,00" required></label><label class="field field-wide">Descrição (opcional)<input name="description" placeholder="Ex.: salário de outubro, freela de fim de semana"></label>
</div><div class="form-actions"><button class="button" type="submit">Salvar lançamento</button></div></form>
<section class="section-heading"><div><h2>Lançamentos de {{ mes[5:7] }}/{{ mes[:4] }}</h2></div></section>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>Data</th><th>Pessoa</th><th>Tipo / descrição</th><th>Tratamento</th><th>Valor</th><th></th></tr></thead><tbody>{% for item in rows %}<tr><td>{{ item.happened_on|date_br }}</td><td>{{ item.person.name }}</td><td>{{ kinds[item.kind] }}<small class="subline">{{ item.description }}</small></td><td>{% if item.included_in_cashflow %}<span class="status status-realizado">No fluxo</span>{% else %}<span class="status status-previsto">Informativo</span>{% endif %}</td><td class="money">{{ item.amount_cents|brl }}</td><td><form method="post" action="/receitas/{{ item.id }}/excluir" onsubmit="return confirm('Excluir este lançamento?')"><button class="text-button danger-text" type="submit">Excluir</button></form></td></tr>{% else %}<tr><td class="empty-cell" colspan="6">Nenhum lançamento neste mês.</td></tr>{% endfor %}</tbody></table></div></div>
{% endblock %}
````


## `app/templates/partials/upcoming_rows.html`

````text
{% if rows %}
<div class="upcoming-list">{% for item in rows %}<div class="upcoming-item"><div class="upcoming-date"><b>{{ item.cashflow_date.strftime('%d') }}</b><small>{{ item.cashflow_date.strftime('%m/%Y') }}</small></div><div class="upcoming-detail"><b>{{ item.description }}</b><small>{{ item.person.name }} · {% if item.card %}{{ item.card.name }}{% elif item.account %}{{ item.account.name }}{% else %}Sem conta/cartão{% endif %}</small><small>{{ item.category.name }}</small></div><div class="upcoming-value"><b>{{ item.amount_cents|brl }}</b><span class="status status-{{ item.status }}">{{ item.status }}</span></div></div>{% endfor %}</div>
{% else %}<div class="empty-state">Nenhum vencimento previsto para os próximos 45 dias.</div>{% endif %}
````


## `app/templates/planned.html`

````text
{% extends "base.html" %}
{% block title %}Gastos planejados · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">PREVISÃO</p><h1>Gastos planejados</h1><p class="muted">Marque como realizado quando pago/confirmado, edite ou cancele o compromisso.</p></div><a class="button" href="/transacoes/nova?tipo=previsto">+ Planejar gasto</a></section>
<section class="panel"><div class="table-wrap"><table><thead><tr><th>Data de caixa</th><th>Descrição</th><th>Categoria / responsável</th><th>Pagamento</th><th>Valor</th><th>Ações</th></tr></thead><tbody>
{% for item in rows %}<tr><td>{{ item.cashflow_date|date_br }}</td><td>{{ item.description }}{% if item.installment_number %}<small class="subline">Parcela {{ item.installment_number }}/{{ item.installment_count }}</small>{% endif %}</td><td>{{ item.category.name }}<small class="subline">{{ item.person.name }}</small></td><td>{% if item.card %}{{ item.card.name }}{% elif item.account %}{{ item.account.name }}{% else %}Dinheiro/outro{% endif %}</td><td class="money">{{ item.amount_cents|brl }}</td><td><div class="action-stack"><form method="post" action="/transacoes/{{ item.id }}/status"><input type="hidden" name="status" value="realizado"><button class="button button-small" type="submit">Marcar pago</button></form><a class="button button-light button-small" href="/transacoes/{{ item.id }}/editar">Editar</a><form method="post" action="/transacoes/{{ item.id }}/cancelar" onsubmit="return confirm('Cancelar este lançamento?')"><button class="button button-danger button-small" type="submit">Cancelar</button></form></div></td></tr>
{% else %}<tr><td colspan="6" class="empty-cell">Nenhum gasto com status previsto.</td></tr>{% endfor %}
</tbody></table></div></section>
{% endblock %}
````


## `app/templates/projection.html`

````text
{% extends "base.html" %}
{% block title %}Projeção · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">PLANEJAMENTO</p><h1>Projeção de 12 meses</h1><p class="muted">Inclui gastos previstos/realizados conforme o vencimento de caixa. Receitas futuras precisam ser cadastradas com a respectiva data.</p></div><a class="button" href="/transacoes/nova?tipo=previsto">+ Planejar gasto</a></section>
<div class="panel"><div class="table-wrap"><table><thead><tr><th>Mês</th><th>Receitas cadastradas</th><th>Despesas/compromissos</th><th>Saldo previsto</th></tr></thead><tbody>{% for row in months %}<tr><td><b>{{ row.name }}</b></td><td>{{ row.income|brl }}</td><td>{{ row.expenses|brl }}</td><td class="money {% if row.balance < 0 %}danger-text{% else %}good-text{% endif %}">{{ row.balance|brl }}</td></tr>{% endfor %}</tbody></table></div></div>
<div class="notice info">A projeção não presume um salário futuro automaticamente: cadastre entradas com a data esperada para que apareçam no mês correspondente. Despesas fixas ativas são geradas automaticamente.</div>
{% endblock %}
````


## `app/templates/registrations.html`

````text
{% extends "base.html" %}
{% block title %}Cadastros · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">CONFIGURAÇÃO DA CASA</p><h1>Cadastros</h1><p class="muted">Gerencie pessoas, categorias, contas e cartões usados no dia a dia.</p></div></section>
<div class="registration-grid">
<section class="panel"><h2>Pessoas</h2>
  <form method="post" action="/cadastros/pessoas" class="inline-form"><input name="name" required maxlength="80" placeholder="Nome da pessoa"><button class="button button-small">Adicionar</button></form>
  <div class="simple-list">{% for p in all_people %}<div class="registration-row people-row">
    <form method="post" action="/cadastros/pessoas/{{ p.id }}/editar" class="registration-edit-form">
      <input name="name" aria-label="Nome de {{ p.name }}" value="{{ p.name }}" required maxlength="80">
      <select name="active" aria-label="Situação de {{ p.name }}"><option value="sim" {% if p.active %}selected{% endif %}>Ativa</option><option value="nao" {% if not p.active %}selected{% endif %}>Inativa</option></select>
      <button class="text-button" type="submit">Salvar</button>
    </form>
    <form method="post" action="/cadastros/pessoas/{{ p.id }}/excluir" onsubmit="return confirm('Excluir/inativar {{ p.name }}? Se houver histórico, a pessoa será preservada como inativa.')"><button class="text-button danger-text" type="submit">Excluir</button></form>
  </div>{% endfor %}</div>
  <p class="muted compact-copy">Se a pessoa tiver lançamentos relacionados, será inativada para preservar o histórico.</p>
</section>
<section class="panel"><h2>Categorias e subcategorias</h2>
  <form method="post" action="/cadastros/categorias" class="form-stack"><label class="field">Nome<input name="name" required maxlength="100" placeholder="Ex.: Material escolar"></label>
    <label class="field">Categoria principal<select name="parent_id"><option value="">Criar categoria principal</option>{% for c in all_categories if not c.parent_id and c.active %}<option value="{{ c.id }}">{{ c.name }}</option>{% endfor %}</select></label>
    <button class="button button-small" type="submit">Adicionar categoria</button>
  </form>
  <div class="simple-list">{% for c in all_categories if c.active %}<div class="registration-row category-row"><span>{% if c.parent %}↳ {{ c.parent.name }} / {% endif %}{{ c.name }}</span>
    <form method="post" action="/cadastros/categorias/{{ c.id }}/excluir" onsubmit="return confirm('Excluir a categoria {{ c.name }}?')"><button class="text-button danger-text" type="submit">Excluir</button></form>
  </div>{% endfor %}</div>
  <details class="inactive-list"><summary>Mostrar categorias excluídas/inativas</summary><div class="simple-list">{% for c in all_categories if not c.active %}<div class="registration-row category-row"><span>{% if c.parent %}↳ {{ c.parent.name }} / {% endif %}{{ c.name }}<small>Inativa · histórico preservado</small></span></div>{% else %}<p class="muted">Nenhuma categoria inativa.</p>{% endfor %}</div></details>
  <p class="muted compact-copy">Lazer fica sem subcategorias: use o campo de descrição do gasto para detalhar. Categorias excluídas saem dos novos lançamentos, preservando relatórios antigos.</p>
</section>
<section class="panel"><h2>Contas e carteiras</h2>
  <form method="post" action="/cadastros/contas" class="form-stack"><label class="field">Nome<input name="name" required placeholder="Ex.: Conta principal"></label>
    <label class="field">Tipo<select name="kind"><option value="corrente">Conta corrente</option><option value="poupanca">Poupança</option><option value="dinheiro">Dinheiro/carteira</option><option value="outro">Outra</option></select></label>
    <label class="field">Responsável<select name="person_id"><option value="">Família/compartilhada</option>{% for p in people %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
    <label class="field">Saldo inicial (R$)<input name="initial_balance" value="0,00" inputmode="decimal"></label><button class="button button-small" type="submit">Adicionar conta</button>
  </form>
  <div class="simple-list">{% for a in all_accounts %}<div><span>{{ a.name }}<small>{{ a.kind }}{% if a.person %} · {{ a.person.name }}{% endif %}</small></span><b>{{ a.initial_balance_cents|brl }}</b></div>{% else %}<p class="muted">Nenhuma conta cadastrada.</p>{% endfor %}</div>
</section>
<section class="panel"><h2>Cartões e vales</h2>
  <form method="post" action="/cadastros/cartoes" class="form-stack" id="card-registration-form">
    <label class="field">Nome do cartão<input name="name" required placeholder="Ex.: Visa principal"></label>
    <label class="field">Titular<select name="owner_id" required>{% for p in people if p.name != 'Família' and p.active %}<option value="{{ p.id }}">{{ p.name }}</option>{% endfor %}</select></label>
    <label class="field">Tipo<select name="kind" id="registration-card-kind"><option value="credito">Cartão de crédito</option><option value="debito">Cartão de débito</option><option value="vale_alimentacao">Vale Alimentação (débito)</option></select></label>
    <div class="form-grid" id="card-cycle-fields"><label class="field">Fecha dia<input type="number" name="closing_day" min="1" max="31" value="10"></label><label class="field">Vence dia<input type="number" name="due_day" min="1" max="31" value="17"></label></div>
    <label class="field">Limite / valor de referência (R$)<input name="limit" value="0,00" inputmode="decimal"></label>
    <label class="field">Conta usada para pagar a fatura (opcional)<select name="payment_account_id"><option value="">Não definida</option>{% for a in all_accounts if a.active %}<option value="{{ a.id }}">{{ a.name }}</option>{% endfor %}</select></label>
    <button class="button button-small" type="submit">Adicionar cartão</button>
  </form>
  <div class="simple-list">{% for c in all_cards %}<div><span>{{ c.name }}<small>{{ c.owner.name }} · {% if c.kind == 'credito' %}Crédito · fecha dia {{ c.closing_day }} · vence dia {{ c.due_day }}{% elif c.kind == 'vale_alimentacao' %}Vale Alimentação (débito) · sem fatura{% else %}Débito · sem fatura{% endif %}</small></span><b>{% if c.kind == 'credito' %}Limite {% else %}Referência {% endif %}{{ c.limit_cents|brl }}</b></div>{% else %}<p class="muted">Nenhum cartão cadastrado.</p>{% endfor %}</div>
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
````


## `app/templates/reports.html`

````text
{% extends "base.html" %}
{% block title %}Relatórios e backup · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">SEUS DADOS</p><h1>Relatórios e backup</h1><p class="muted">Exporte o período em CSV ou baixe uma cópia consistente do banco SQLite.</p></div></section>
<section class="panel form-panel"><h2>Exportar CSV por período</h2><form method="get" action="/exportar.csv" class="form-grid"><label class="field">Data inicial<input type="date" name="inicio" value="{{ default_start }}" required></label><label class="field">Data final<input type="date" name="fim" value="{{ default_end }}" required></label><div class="form-actions"><button class="button" type="submit">Exportar CSV</button></div></form><p class="muted helper-text">O CSV inclui despesas pela data da compra e receitas/descontos pela data do lançamento, com valor em centavos e reais, status, conta, cartão e parcela.</p></section>
<section class="panel backup-panel"><div><h2>Backup completo do banco</h2><p class="muted">Baixa o arquivo .db com cadastros, movimentos, orçamentos e regras recorrentes. Guarde a cópia em local seguro.</p></div><a class="button" href="/backup.db">Baixar backup .db</a></section>
{% endblock %}
````


## `app/templates/savings.html`

````text
{% extends "base.html" %}
{% block title %}Poupança · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">RESERVAS E APLICAÇÕES</p><h1>Poupança</h1><p class="muted">Acompanhe o capital de cada pessoa. Depósitos e juros aumentam o saldo; retiradas diminuem.</p></div></section>
<section class="metric-grid metric-grid-two">
  <article class="metric metric-good"><span>Capital total guardado</span><strong>{{ total_capital|brl }}</strong><small>Soma dos saldos iniciais, depósitos, juros e retiradas de todas as poupanças ativas</small></article>
  <article class="metric"><span>Poupanças cadastradas</span><strong>{{ savings_accounts|length }}</strong><small>Podem existir várias poupanças por pessoa</small></article>
</section>
<div class="registration-grid savings-top-grid">
  <section class="panel"><h2>Criar poupança</h2><form method="post" action="/poupanca/contas" class="form-stack">
    <label class="field">Nome / objetivo<input name="name" required maxlength="120" placeholder="Ex.: Reserva de emergência"></label>
    <label class="field">Pessoa titular<select name="person_id" required>{% for person in people if person.name != 'Família' %}<option value="{{ person.id }}">{{ person.name }}</option>{% endfor %}</select></label>
    <label class="field">Capital inicial (R$)<input name="initial_balance" value="0,00" inputmode="decimal" required><small class="muted">Informe 0,00 se estiver começando agora.</small></label>
    <button class="button button-small" type="submit">Criar poupança</button>
  </form></section>
  <section class="panel"><h2>Adicionar depósito ou retirada</h2><p class="muted compact-copy">Escolha a poupança e registre uma movimentação. Retiradas não podem superar o saldo disponível.</p>
    {% if savings_accounts %}<form method="post" action="/poupanca/movimentos" class="form-stack" id="general-savings-movement">
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
  <form method="post" action="/poupanca/movimentos" class="interest-form">
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
````


## `app/templates/transaction_form.html`

````text
{% extends "base.html" %}
{% block title %}{{ title }} · Casa em ordem{% endblock %}
{% block content %}
<section class="page-head"><div><p class="eyebrow">MOVIMENTAÇÃO</p><h1>{{ title }}</h1><p class="muted">Valores em reais; parcelamento gera uma linha por fatura de crédito.</p></div><a class="button button-light" href="/transacoes">Voltar</a></section>
<form class="panel form-panel" method="post" action="{{ form_action }}">
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
````


## `app/templates/transactions.html`

````text
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
````


## `docker-compose.yml`

````text
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
    restart: unless-stopped
volumes:
  familia_financas_data:
````


## `requirements.txt`

````text
fastapi==0.115.12
uvicorn[standard]==0.34.2
SQLAlchemy==2.0.40
Jinja2==3.1.6
python-multipart==0.0.20
pydantic==2.11.4
````


## `tests/test_services.py`

````text
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
````
