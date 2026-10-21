import csv
import io
import os
import sqlite3
import tempfile
from datetime import date
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse, FileResponse, RedirectResponse
from starlette.background import BackgroundTask
from sqlalchemy import select
from sqlalchemy.orm import Session
from ..database import get_db, engine, DATABASE_URL
from ..models import FinancialTransaction, Income
from ..services.finance import parse_month, month_start, month_end, category_name
from .common import page

router = APIRouter(tags=["relatórios"])

@router.get("/planejados")
def planned_page(request: Request, db: Session = Depends(get_db)):
    rows = list(db.scalars(select(FinancialTransaction).where(FinancialTransaction.status == "previsto")
                           .order_by(FinancialTransaction.cashflow_date, FinancialTransaction.id)).all())
    return page(request, db, "planned.html", active_nav="planejados", rows=rows)

@router.get("/historico")
def history_page(request: Request, mes: str | None = None, db: Session = Depends(get_db)):
    year, month = parse_month(mes)
    start, end = month_start(year, month), month_end(year, month)
    txs = list(db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= start, FinancialTransaction.purchase_date <= end,
        FinancialTransaction.status == "realizado")).all())
    incomes = list(db.scalars(select(Income).where(Income.happened_on >= start, Income.happened_on <= end)).all())
    category_totals, person_totals, card_totals = {}, {}, {}
    for t in txs:
        label = category_name(db, t.category_id)
        category_totals[label] = category_totals.get(label, 0) + t.amount_cents
        person_totals[t.person.name] = person_totals.get(t.person.name, 0) + t.amount_cents
        if t.card:
            card_totals[t.card.name] = card_totals.get(t.card.name, 0) + t.amount_cents
    summary = lambda mapping: sorted([{"name": k, "amount": v} for k, v in mapping.items()], key=lambda item: item["amount"], reverse=True)
    top_expenses = sorted(txs, key=lambda t: t.amount_cents, reverse=True)[:10]
    return page(request, db, "history.html", active_nav="historico", mes=f"{year:04d}-{month:02d}",
                category_totals=summary(category_totals), person_totals=summary(person_totals), card_totals=summary(card_totals),
                top_expenses=top_expenses, income_total=sum(i.amount_cents for i in incomes if i.included_in_cashflow),
                expense_total=sum(t.amount_cents for t in txs))

@router.get("/relatorios")
def reports_page(request: Request, db: Session = Depends(get_db)):
    return page(request, db, "reports.html", active_nav="relatorios", default_start=date.today().replace(day=1).isoformat(), default_end=date.today().isoformat())

@router.get("/exportar.csv")
def export_csv(inicio: date, fim: date, db: Session = Depends(get_db)):
    if fim < inicio:
        return RedirectResponse("/relatorios?erro=Período+inválido", status_code=303)
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["tipo", "data_compra_ou_receita", "data_fluxo_caixa", "descrição", "valor_centavos", "valor_brl", "categoria", "pessoa", "conta", "cartão", "status", "parcela"])
    txs = db.scalars(select(FinancialTransaction).where(
        FinancialTransaction.purchase_date >= inicio, FinancialTransaction.purchase_date <= fim,
    ).order_by(FinancialTransaction.purchase_date, FinancialTransaction.id)).all()
    for t in txs:
        writer.writerow(["despesa", t.purchase_date.isoformat(), t.cashflow_date.isoformat(), t.description, t.amount_cents,
                         f"{t.amount_cents // 100},{t.amount_cents % 100:02d}", category_name(db, t.category_id), t.person.name,
                         t.account.name if t.account else "", t.card.name if t.card else "", t.status,
                         f"{t.installment_number}/{t.installment_count}" if t.installment_number else ""])
    incomes = db.scalars(select(Income).where(Income.happened_on >= inicio, Income.happened_on <= fim).order_by(Income.happened_on)).all()
    kind_names = {"salario": "Salário", "extra": "Renda extra", "plano_saude": "Plano de saúde (desconto em folha)", "inss": "INSS (desconto em folha)", "ir": "IR (desconto em folha)", "vale": "Vale (desconto em folha)",
                  "outros_desconto": "Outros (desconto em folha)"}
    for income in incomes:
        writer.writerow(["receita" if income.included_in_cashflow else "desconto_informativo", income.happened_on.isoformat(), income.happened_on.isoformat(),
                         f"{kind_names.get(income.kind, income.kind)} — {income.description}", income.amount_cents,
                         f"{income.amount_cents // 100},{income.amount_cents % 100:02d}", "", income.person.name, "", "",
                         "incluído_no_fluxo" if income.included_in_cashflow else "informativo", ""])
    content = "\ufeff" + output.getvalue()
    filename = f"financeiro_{inicio.isoformat()}_{fim.isoformat()}.csv"
    return StreamingResponse(iter([content.encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@router.get("/backup.db")
def backup_database():
    if not DATABASE_URL.startswith("sqlite"):
        return RedirectResponse("/relatorios?erro=Backup+disponível+para+SQLite", status_code=303)
    fd, temp_path = tempfile.mkstemp(prefix="familia-financas-", suffix=".db")
    os.close(fd)
    source = engine.raw_connection()
    target = sqlite3.connect(temp_path)
    try:
        source.driver_connection.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return FileResponse(temp_path, media_type="application/x-sqlite3", filename=f"backup-financas-{date.today().isoformat()}.db",
                        background=BackgroundTask(lambda: os.path.exists(temp_path) and os.remove(temp_path)))
