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
