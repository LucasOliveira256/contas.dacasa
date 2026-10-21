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
