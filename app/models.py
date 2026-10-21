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
