from datetime import date
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import FixedExpense, FinancialTransaction, Income, RecurringIncome
from .finance import add_months, cashflow_date_for, is_payroll_deduction, month_start


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


def ensure_recurring_incomes(db: Session, today: date | None = None, months_ahead: int = 12) -> int:
    """Gera as receitas/descontos recorrentes que faltam até o horizonte.

    generated_until registra o último mês processado de cada série, então um lançamento
    excluído individualmente não é recriado. Idempotente.
    """
    today = today or date.today()
    horizon = add_months(today, months_ahead).replace(day=1)
    created, touched = 0, False
    for series in db.scalars(select(RecurringIncome).where(RecurringIncome.active.is_(True))).all():
        cursor = add_months(series.generated_until, 1, 1) if series.generated_until else series.start_date.replace(day=1)
        last = min(horizon, series.end_month) if series.end_month else horizon
        if cursor > last:
            continue
        while cursor <= last:
            exists = db.scalar(select(Income.id).where(
                Income.recurring_income_id == series.id, Income.occurrence_month == cursor))
            if not exists:
                db.add(Income(
                    person_id=series.person_id, kind=series.kind, happened_on=add_months(cursor, 0, series.day_of_month),
                    amount_cents=series.amount_cents, description=series.description,
                    included_in_cashflow=not is_payroll_deduction(series.kind),
                    recurring_income_id=series.id, occurrence_month=cursor,
                ))
                created += 1
            cursor = add_months(cursor, 1, 1)
        series.generated_until = last
        touched = True
    if touched:
        db.commit()
    return created
