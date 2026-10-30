from collections import defaultdict
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Income, FinancialTransaction, Budget, Category, CreditCard
from ..services.finance import active_transactions_for_month, incomes_for_month, payroll_deductions_for_month, month_start, month_end, add_months, parse_month, month_key, category_name
from ..services.recurring import ensure_fixed_transactions, ensure_recurring_incomes
from .common import page
from ..services.local_time import local_now, local_today, greeting_for_hour

router = APIRouter()

@router.get("/")
def dashboard(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    now = local_now()
    today = now.date()
    greeting = greeting_for_hour(now.hour)
    year, month = parse_month(mes, today)
    selected = month_start(year, month)
    ensure_fixed_transactions(db, today)
    ensure_recurring_incomes(db, today)
    incomes = incomes_for_month(db, year, month)
    cash_incomes = [i for i in incomes if i.included_in_cashflow]
    deduction_incomes = [i for i in incomes if not i.included_in_cashflow]
    transactions = active_transactions_for_month(db, year, month, by_cashflow=True)
    income_total = sum(i.amount_cents for i in cash_incomes)
    expense_total = sum(t.amount_cents for t in transactions)
    deductions_total = payroll_deductions_for_month(db, year, month)
    previous_date = add_months(selected, -1, 1)
    prev_deductions = payroll_deductions_for_month(db, previous_date.year, previous_date.month)
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
        monthly_deductions = payroll_deductions_for_month(db, current.year, current.month)
        labels.append(label)
        incomes_data.append(monthly_income)
        # As barras de saída incluem os descontos em folha para reconciliar com a linha de saldo.
        expenses_data.append(monthly_expense + monthly_deductions)
        running_balance += monthly_income - monthly_deductions - monthly_expense
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
                income_total=income_total, expense_total=expense_total, balance=income_total-deductions_total-expense_total,
                deductions_total=deductions_total, prev_deductions=prev_deductions, deductions_count=len(deduction_incomes),
                prev_income=prev_income, prev_expense=prev_expense, prev_balance=prev_income-prev_deductions-prev_expense,
                income_count=len(cash_incomes), expense_count=len(transactions), budget_total=budget_total,
                actual_budgeted=actual_budgeted, budget_rows=budget_rows, ranking=ranking, upcoming=upcoming,
                chart_payload=chart_payload, previous_month=month_key(previous_date), actual_spend=sum(t.amount_cents for t in actual_purchase),
                greeting=greeting)

@router.get("/partials/proximos")
def upcoming_partial(request: Request, db: Session = Depends(get_db)):
    from datetime import timedelta
    from .common import templates
    from .common import base_context
    today = local_today()
    rows = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.cashflow_date >= today,
        FinancialTransaction.cashflow_date <= today + timedelta(days=45),
        FinancialTransaction.status != "cancelado").order_by(FinancialTransaction.cashflow_date).limit(10)).all())
    return templates.TemplateResponse(request=request, name="partials/upcoming_rows.html",
                                      context=base_context(request, db, rows=rows))
