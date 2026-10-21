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
