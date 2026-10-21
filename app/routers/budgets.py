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
