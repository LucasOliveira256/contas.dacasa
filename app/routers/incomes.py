from datetime import date
from urllib.parse import quote_plus
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import Income, Person, RecurringIncome
from ..services.finance import add_months, is_payroll_deduction, parse_brl_to_cents, parse_month, month_start, month_end
from ..services.local_time import local_today
from ..services.recurring import ensure_recurring_incomes
from .common import page

router = APIRouter(prefix="/receitas", tags=["receitas"])

KINDS = {"salario": "Salário", "extra": "Renda extra", "plano_saude": "Plano de saúde (desconto em folha)",
         "inss": "INSS (desconto em folha)", "ir": "IR (desconto em folha)",
         "vale": "Vale (desconto em folha)", "outros_desconto": "Outros (desconto em folha)"}


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _parse_month_strict(value: str) -> date:
    """Lê 'AAAA-MM' (campo type=month) e devolve o primeiro dia do mês."""
    try:
        year, month = (int(part) for part in value.strip().split("-", 1))
        return date(year, month, 1)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Informe um mês válido para o fim da repetição.")


def _redirect(mes: str | None, erro: str | None = None) -> RedirectResponse:
    url = "/receitas"
    params = []
    if mes:
        params.append(f"mes={mes}")
    if erro:
        params.append(f"erro={quote_plus(erro)}")
    if params:
        url += "?" + "&".join(params)
    return RedirectResponse(url, status_code=303)


def _check_overlap(db: Session, person_id: int, kind: str, description: str, start: date, end: date | None,
                   ignore_id: int | None = None) -> None:
    """Impede duas séries ativas iguais (mesma pessoa, tipo e descrição) no mesmo período."""
    candidates = db.scalars(select(RecurringIncome).where(
        RecurringIncome.active.is_(True), RecurringIncome.person_id == person_id,
        RecurringIncome.kind == kind, RecurringIncome.description == description)).all()
    for other in candidates:
        if ignore_id and other.id == ignore_id:
            continue
        other_start = other.start_date.replace(day=1)
        starts_before_other_ends = other.end_month is None or other.end_month >= start
        ends_after_other_starts = end is None or end >= other_start
        if starts_before_other_ends and ends_after_other_starts:
            raise ValueError("Já existe uma repetição ativa com a mesma pessoa, tipo e descrição neste período. "
                             "Edite ou encerre a existente antes de criar outra.")


@router.get("")
def incomes_page(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    ensure_recurring_incomes(db, local_today())
    rows = list(db.scalars(select(Income).where(Income.happened_on >= month_start(year, month),
                                       Income.happened_on <= month_end(year, month)).order_by(Income.happened_on.desc(), Income.id.desc())).all())
    cash_total = sum(r.amount_cents for r in rows if r.included_in_cashflow)
    deductions = sum(r.amount_cents for r in rows if not r.included_in_cashflow)
    return page(request, db, "incomes.html", active_nav="receitas", rows=rows, mes=_month_key(date(year, month, 1)),
                cash_total=cash_total, deductions=deductions, net_total=cash_total - deductions, kinds=KINDS)


@router.post("")
def create_income(happened_on: date = Form(...), person_id: int = Form(...), kind: str = Form(...), amount: str = Form(...),
                  description: str = Form(""), repeat: str = Form("nao"), until: str = Form(""),
                  db: Session = Depends(get_db)):
    mes = _month_key(happened_on)
    try:
        if kind not in KINDS or not db.get(Person, person_id):
            raise ValueError("Seleção inválida.")
        cents = parse_brl_to_cents(amount)
        clean_description = description.strip()
        if repeat == "nao":
            db.add(Income(person_id=person_id, kind=kind, happened_on=happened_on, amount_cents=cents,
                          description=clean_description, included_in_cashflow=not is_payroll_deduction(kind)))
            db.commit()
        elif repeat in ("ate", "sem_fim"):
            start_month = happened_on.replace(day=1)
            end_month = None
            if repeat == "ate":
                end_month = _parse_month_strict(until)
                if end_month < start_month:
                    raise ValueError("O mês final não pode ser anterior ao primeiro lançamento.")
            _check_overlap(db, person_id, kind, clean_description, start_month, end_month)
            db.add(RecurringIncome(person_id=person_id, kind=kind, amount_cents=cents, description=clean_description,
                                   day_of_month=happened_on.day, start_date=happened_on, end_month=end_month))
            db.commit()
            ensure_recurring_incomes(db, local_today())
        else:
            raise ValueError("Opção de repetição inválida.")
    except ValueError as exc:
        db.rollback()
        return _redirect(mes, str(exc))
    return _redirect(mes)


@router.get("/{income_id}/editar")
def edit_income_form(income_id: int, request: Request, db: Session = Depends(get_db)):
    income = db.get(Income, income_id)
    if not income:
        return _redirect(None)
    return page(request, db, "income_edit.html", active_nav="receitas", income=income, series=income.recurring,
                kinds=KINDS, mes=_month_key(income.happened_on))


@router.post("/{income_id}/editar")
def update_income(income_id: int, happened_on: date = Form(...), person_id: int = Form(...), kind: str = Form(...),
                  amount: str = Form(...), description: str = Form(""), scope: str = Form("este"),
                  end_mode: str = Form("manter"), until: str = Form(""), db: Session = Depends(get_db)):
    income = db.get(Income, income_id)
    if not income:
        return _redirect(None)
    try:
        if kind not in KINDS or not db.get(Person, person_id):
            raise ValueError("Seleção inválida.")
        cents = parse_brl_to_cents(amount)
        clean_description = description.strip()
        deduction = is_payroll_deduction(kind)
        series = income.recurring
        if series is None or scope == "este":
            # Só este lançamento: a série não reescreve meses já gerados.
            income.person_id, income.kind, income.happened_on = person_id, kind, happened_on
            income.amount_cents, income.description = cents, clean_description
            income.included_in_cashflow = not deduction
        elif scope == "proximos":
            occurrence = income.occurrence_month
            new_end = series.end_month
            if end_mode == "sem_fim":
                new_end = None
            elif end_mode == "ate":
                new_end = _parse_month_strict(until)
                if new_end < occurrence:
                    raise ValueError("O mês final não pode ser anterior a este lançamento.")
            elif end_mode != "manter":
                raise ValueError("Opção de término inválida.")
            _check_overlap(db, person_id, kind, clean_description, occurrence, new_end, ignore_id=series.id)
            series.person_id, series.kind, series.amount_cents = person_id, kind, cents
            series.description, series.day_of_month, series.end_month = clean_description, happened_on.day, new_end
            for row in db.scalars(select(Income).where(Income.recurring_income_id == series.id,
                                                       Income.occurrence_month >= occurrence)).all():
                if new_end is not None and row.occurrence_month > new_end:
                    db.delete(row)
                    continue
                row.person_id, row.kind, row.amount_cents, row.description = person_id, kind, cents, clean_description
                row.included_in_cashflow = not deduction
                row.happened_on = happened_on if row.id == income.id else add_months(row.occurrence_month, 0, happened_on.day)
            if new_end is not None and series.generated_until and series.generated_until > new_end:
                series.generated_until = new_end
        else:
            raise ValueError("Escolha se a alteração vale só para este mês ou também para os próximos.")
        db.commit()
        ensure_recurring_incomes(db, local_today())
    except ValueError as exc:
        db.rollback()
        return RedirectResponse(f"/receitas/{income_id}/editar?erro={quote_plus(str(exc))}", status_code=303)
    return _redirect(_month_key(happened_on))


@router.post("/{income_id}/excluir")
def delete_income(income_id: int, scope: str = Form("este"), db: Session = Depends(get_db)):
    income = db.get(Income, income_id)
    if not income:
        return _redirect(None)
    mes = _month_key(income.happened_on)
    series = income.recurring
    if series is None or scope == "este":
        # O generated_until da série impede que o mês excluído seja recriado.
        db.delete(income)
    elif scope == "proximos":
        occurrence = income.occurrence_month
        for row in db.scalars(select(Income).where(Income.recurring_income_id == series.id,
                                                   Income.occurrence_month >= occurrence)).all():
            db.delete(row)
        previous = add_months(occurrence, -1, 1)
        first = series.start_date.replace(day=1)
        series.end_month = previous
        series.generated_until = previous if previous >= first else None
        if previous < first:
            series.active = False
    elif scope == "serie":
        for row in db.scalars(select(Income).where(Income.recurring_income_id == series.id)).all():
            db.delete(row)
        db.flush()
        db.delete(series)
    else:
        return _redirect(mes, "Escopo de exclusão inválido.")
    db.commit()
    return _redirect(mes)
