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
