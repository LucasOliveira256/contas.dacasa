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
