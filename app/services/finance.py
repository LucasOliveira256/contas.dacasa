import calendar
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..models import CreditCard, Category, FinancialTransaction, Income


# Tipos de receita lançados como desconto em folha (included_in_cashflow=False).
PAYROLL_DEDUCTION_KINDS = ("plano_saude", "inss", "ir", "vale", "outros_desconto")


def is_payroll_deduction(kind: str) -> bool:
    return kind in PAYROLL_DEDUCTION_KINDS


def parse_brl_to_cents(value: str | int | None) -> int:
    """Converte entrada BR/decimal para centavos sem aritmética monetária em float."""
    if value is None or str(value).strip() == "":
        return 0
    text = str(value).strip().replace("R$", "").replace(" ", "")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        amount = Decimal(text).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Informe um valor válido, por exemplo 123,45.") from exc
    if amount < 0:
        raise ValueError("O valor não pode ser negativo.")
    return int(amount * 100)


def brl(cents: int | None) -> str:
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    integer, decimal = divmod(cents, 100)
    whole = f"{integer:,}".replace(",", ".")
    return f"{sign}R$ {whole},{decimal:02d}"


def date_br(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else "—"


def month_start(year: int, month: int) -> date:
    return date(year, month, 1)


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(value: date, count: int, day: int | None = None) -> date:
    zero_based = value.month - 1 + count
    year = value.year + zero_based // 12
    month = zero_based % 12 + 1
    target_day = day if day is not None else value.day
    return date(year, month, min(target_day, calendar.monthrange(year, month)[1]))


def parse_month(value: str | None, default: date | None = None) -> tuple[int, int]:
    fallback = default or date.today()
    if not value:
        return fallback.year, fallback.month
    try:
        year, month = (int(part) for part in value.split("-", 1))
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except (ValueError, TypeError):
        return fallback.year, fallback.month


def month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def invoice_due_date(card: CreditCard, purchase_date: date) -> date:
    """Calcula vencimento apenas para cartão de crédito."""
    if card.kind != "credito":
        return purchase_date
    close_date = date(purchase_date.year, purchase_date.month,
                      min(card.closing_day, calendar.monthrange(purchase_date.year, purchase_date.month)[1]))
    closing_month = purchase_date if purchase_date <= close_date else add_months(purchase_date, 1, card.closing_day)
    # Se o vencimento ocorre antes/no dia do fechamento, a fatura vence no mês seguinte.
    due_month_offset = 0 if card.due_day > card.closing_day else 1
    return add_months(closing_month, due_month_offset, card.due_day)


def category_name(db: Session, category_id: int | None) -> str:
    if not category_id:
        return "Sem categoria"
    category = db.get(Category, category_id)
    if not category:
        return "Sem categoria"
    return f"{category.parent.name} / {category.name}" if category.parent else category.name


def cashflow_date_for(db: Session, card_id: int | None, purchase_date: date) -> date:
    if card_id:
        card = db.get(CreditCard, card_id)
        if not card:
            raise ValueError("Cartão não encontrado.")
        return invoice_due_date(card, purchase_date) if card.kind == "credito" else purchase_date
    return purchase_date


def incomes_for_month(db: Session, year: int, month: int) -> list[Income]:
    start, end = month_start(year, month), month_end(year, month)
    return list(db.scalars(select(Income).where(Income.happened_on >= start, Income.happened_on <= end).order_by(Income.happened_on.desc())).all())


def active_transactions_for_month(db: Session, year: int, month: int, by_cashflow: bool = True) -> list[FinancialTransaction]:
    start, end = month_start(year, month), month_end(year, month)
    column = FinancialTransaction.cashflow_date if by_cashflow else FinancialTransaction.purchase_date
    return list(db.scalars(select(FinancialTransaction).where(
        column >= start, column <= end, FinancialTransaction.status != "cancelado"
    ).order_by(column.desc(), FinancialTransaction.id.desc())).all())


def payroll_deductions_for_month(db: Session, year: int, month: int) -> int:
    """Soma dos descontos em folha do mês (receitas fora do fluxo de caixa), em centavos."""
    total = db.scalar(select(func.coalesce(func.sum(Income.amount_cents), 0)).where(
        Income.happened_on >= month_start(year, month),
        Income.happened_on <= month_end(year, month),
        Income.included_in_cashflow.is_(False),
    ))
    return int(total or 0)


def recalculate_card_cashflow(db: Session, card: CreditCard) -> int:
    """Recalcula cashflow_date de todas as compras do cartão de crédito conforme fechamento/vencimento atuais.

    Parcelas seguem a mesma regra de routers/transactions.py::create_transaction. Não faz commit.
    """
    if card.kind != "credito":
        return 0
    changed = 0
    for item in db.scalars(select(FinancialTransaction).where(FinancialTransaction.card_id == card.id)).all():
        due = invoice_due_date(card, item.purchase_date)
        new_date = add_months(due, item.installment_number - 1, due.day) if item.installment_number else due
        if item.cashflow_date != new_date:
            item.cashflow_date = new_date
            changed += 1
    return changed
