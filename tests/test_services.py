import unittest
from datetime import date
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import Person, Category, CreditCard, FixedExpense, FinancialTransaction, SavingsAccount, SavingsMovement
from app.seed import seed_database
from app.services.finance import parse_brl_to_cents, brl, invoice_due_date
from app.services.recurring import ensure_fixed_transactions
from app.services.finance import cashflow_date_for
from app.services.savings import savings_balance

class FinanceServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        seed_database(self.db)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_parse_and_format_brl_without_float(self):
        self.assertEqual(parse_brl_to_cents("1.234,56"), 123456)
        self.assertEqual(parse_brl_to_cents("1234.56"), 123456)
        self.assertEqual(brl(123456), "R$ 1.234,56")


    def test_seed_has_lazer_and_savings_without_old_motorcycle_categories(self):
        roots = set(self.db.scalars(select(Category.name).where(Category.parent_id.is_(None), Category.active.is_(True))).all())
        self.assertIn("Lazer", roots)
        self.assertIn("Poupança", roots)
        self.assertNotIn("Lazer/Moto", roots)
        self.assertEqual(self.db.scalar(select(Category.id).where(Category.name == "Lazer/Moto")), None)

    def test_legacy_motorcycle_categories_are_inactivated(self):
        legacy = Category(name="Lazer/Moto")
        self.db.add(legacy)
        self.db.flush()
        child = Category(name="Equipamentos Moto", parent_id=legacy.id)
        self.db.add(child)
        self.db.commit()
        seed_database(self.db)
        self.db.refresh(legacy)
        self.db.refresh(child)
        self.assertFalse(legacy.active)
        self.assertFalse(child.active)
        self.assertIsNotNone(self.db.scalar(select(Category.id).where(Category.name == "Lazer", Category.parent_id.is_(None), Category.active.is_(True))))

    def test_card_purchase_after_close_moves_to_next_cycle(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Marido"))
        card = CreditCard(name="Visa", owner_id=owner.id, closing_day=10, due_day=17, limit_cents=500000)
        self.db.add(card)
        self.db.commit()
        self.assertEqual(invoice_due_date(card, date(2026, 10, 9)), date(2026, 10, 17))
        self.assertEqual(invoice_due_date(card, date(2026, 10, 20)), date(2026, 11, 17))


    def test_debit_and_meal_voucher_use_purchase_date_without_invoice(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Marido"))
        for kind in ("debito", "vale_alimentacao"):
            card = CreditCard(name=f"Cartão {kind}", owner_id=owner.id, kind=kind, closing_day=0, due_day=0, limit_cents=0)
            self.db.add(card)
            self.db.flush()
            self.assertEqual(cashflow_date_for(self.db, card.id, date(2026, 10, 20)), date(2026, 10, 20))

    def test_savings_deposits_interest_and_withdrawal_change_capital_in_cents(self):
        owner = self.db.scalar(select(Person).where(Person.name == "Esposa"))
        category = self.db.scalar(select(Category).where(Category.name == "Poupança", Category.parent_id.is_(None)))
        account = SavingsAccount(name="Reserva", person_id=owner.id, category_id=category.id, initial_balance_cents=10000)
        self.db.add(account)
        self.db.flush()
        self.db.add_all([
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 1), kind="deposito", amount_cents=2500),
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 2), kind="juros", amount_cents=37),
            SavingsMovement(account_id=account.id, happened_on=date(2026, 10, 3), kind="retirada", amount_cents=1200),
        ])
        self.db.commit()
        self.assertEqual(savings_balance(self.db, account), 11337)

    def test_recurring_occurrences_are_idempotent_and_monthly(self):
        family = self.db.scalar(select(Person).where(Person.name == "Família"))
        category = self.db.scalar(select(Category).where(Category.name == "Mensalidade"))
        fixed = FixedExpense(name="Colégio", amount_cents=125000, day_of_month=10, category_id=category.id,
                             person_id=family.id, start_date=date(2026, 10, 1), active=True)
        self.db.add(fixed)
        self.db.commit()
        first_count = ensure_fixed_transactions(self.db, date(2026, 10, 20), months_ahead=2)
        second_count = ensure_fixed_transactions(self.db, date(2026, 10, 20), months_ahead=2)
        rows = list(self.db.scalars(select(FinancialTransaction).where(FinancialTransaction.fixed_expense_id == fixed.id)).all())
        self.assertEqual(first_count, 3)
        self.assertEqual(second_count, 0)
        self.assertEqual(len(rows), 3)
        self.assertEqual([row.occurrence_month.month for row in sorted(rows, key=lambda row: row.occurrence_month)], [10, 11, 12])

if __name__ == "__main__":
    unittest.main()
