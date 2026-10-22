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
    limit: str = Form("0,00"), payment_account_id: str = Form(""),
    last_four_digits: str = Form(""), db: Session = Depends(get_db),
):
    clean = name.strip()
    last_four_digits = last_four_digits.strip()
    if last_four_digits and (len(last_four_digits) != 4 or not last_four_digits.isascii() or not last_four_digits.isdigit()):
        return RedirectResponse("/cadastros?erro=Informe+somente+os+4+ultimos+digitos+do+cartao", status_code=303)
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
            limit_cents=parse_brl_to_cents(limit), last_four_digits=last_four_digits,
            payment_account_id=int(payment_account_id) if payment_account_id else None,
        ))
        db.commit()
    except (ValueError, TypeError, IntegrityError) as exc:
        db.rollback()
        msg = str(exc) if isinstance(exc, ValueError) else "Não foi possível salvar o cartão"
        return RedirectResponse(f"/cadastros?erro={msg.replace(' ', '+')}", status_code=303)
    return RedirectResponse("/cadastros?ok=1", status_code=303)


@router.post("/cartoes/{card_id}/editar")
def update_card(card_id: int, last_four_digits: str = Form(""), db: Session = Depends(get_db)):
    card = db.get(CreditCard, card_id)
    digits = last_four_digits.strip()
    if not card:
        return RedirectResponse("/cadastros?erro=Cartao+nao+encontrado", status_code=303)
    if digits and (len(digits) != 4 or not digits.isascii() or not digits.isdigit()):
        return RedirectResponse("/cadastros?erro=Informe+zero+ou+quatro+digitos", status_code=303)
    card.last_four_digits = digits
    db.commit()
    return RedirectResponse("/cadastros?ok=1", status_code=303)
