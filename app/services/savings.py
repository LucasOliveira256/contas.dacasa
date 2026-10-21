from sqlalchemy import select
from sqlalchemy.orm import Session
from ..models import SavingsAccount, SavingsMovement


def savings_balance(db: Session, account: SavingsAccount) -> int:
    """Saldo sempre em centavos: depósitos/juros somam e retiradas subtraem."""
    movements = db.scalars(select(SavingsMovement).where(SavingsMovement.account_id == account.id)).all()
    balance = account.initial_balance_cents
    for movement in movements:
        if movement.kind in ("deposito", "juros"):
            balance += movement.amount_cents
        elif movement.kind == "retirada":
            balance -= movement.amount_cents
    return balance
