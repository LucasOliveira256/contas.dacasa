"""Testes de descontos no saldo, receitas recorrentes, edição de cartões e migração do banco."""
import os
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app import database
from app.database import Base
from app.models import Category, CreditCard, FinancialTransaction, Income, Person, RecurringIncome
from app.routers import incomes as incomes_router
from app.routers.budgets import projection
from app.routers.dashboard import dashboard
from app.routers.registrations import registrations, update_card
from app.routers.reports import history_page
from app.routers.transactions import create_transaction
from app.seed import seed_database
from app.services.finance import (
    incomes_for_month, invoice_due_date, payroll_deductions_for_month, recalculate_card_cashflow,
)
from app.services.recurring import ensure_recurring_incomes

FIXED_TODAY = date(2026, 10, 29)


def fake_request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"",
                    "session": {}, "state": {}})


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine, expire_on_commit=False)
        seed_database(self.db)
        self.husband = self.db.scalar(select(Person).where(Person.name == "Marido"))
        self.category = self.db.scalar(select(Category).where(Category.parent_id.is_(None)))
        self.today_patch = patch("app.routers.incomes.local_today", return_value=FIXED_TODAY)
        self.today_patch.start()

    def tearDown(self):
        self.today_patch.stop()
        self.db.close()
        self.engine.dispose()

    def add_income(self, kind, cents, when, deduction=False):
        self.db.add(Income(person_id=self.husband.id, kind=kind, happened_on=when, amount_cents=cents,
                           included_in_cashflow=not deduction))
        self.db.commit()

    def create_series(self, kind="salario", amount="7200,00", start=date(2026, 11, 5), repeat="ate",
                      until="2027-05", description=""):
        return incomes_router.create_income(
            happened_on=start, person_id=self.husband.id, kind=kind, amount=amount, description=description,
            repeat=repeat, until=until, db=self.db)

    def month_rows(self, series_id):
        return list(self.db.scalars(select(Income).where(Income.recurring_income_id == series_id)
                                    .order_by(Income.occurrence_month)).all())


class PayrollDeductionsTests(BaseCase):
    def test_dashboard_balance_subtracts_deductions(self):
        self.add_income("salario", 720000, date(2026, 10, 5))
        for kind, cents in (("inss", 100000), ("ir", 120000), ("plano_saude", 80000), ("vale", 120000)):
            self.add_income(kind, cents, date(2026, 10, 5), deduction=True)
        context = dashboard(fake_request(), "2026-10", self.db).context
        self.assertEqual(context["income_total"], 720000)
        self.assertEqual(context["deductions_total"], 420000)
        self.assertEqual(context["expense_total"], 0)
        self.assertEqual(context["balance"], 300000)  # 7200 - 4200 = 3000

    def test_balance_also_subtracts_expenses(self):
        self.add_income("salario", 720000, date(2026, 10, 5))
        self.add_income("inss", 420000, date(2026, 10, 5), deduction=True)
        create_transaction(None, description="Mercado", amount="500,00", purchase_date=date(2026, 10, 10),
                           category_id=self.category.id, person_id=self.husband.id, account_id="", card_id="",
                           status="realizado", installments=1, db=self.db)
        context = dashboard(fake_request(), "2026-10", self.db).context
        self.assertEqual(context["expense_total"], 50000)
        self.assertEqual(context["balance"], 250000)  # 7200 - 4200 - 500 = 2500

    def test_previous_month_and_chart_use_deductions(self):
        self.add_income("salario", 720000, date(2026, 9, 5))
        self.add_income("inss", 420000, date(2026, 9, 5), deduction=True)
        context = dashboard(fake_request(), "2026-10", self.db).context
        self.assertEqual(context["prev_deductions"], 420000)
        self.assertEqual(context["prev_balance"], 300000)
        line = context["chart_payload"]["line"]["data"]
        bars = context["chart_payload"]["bars"]
        self.assertEqual(line[-2], 300000)  # setembro: saldo acumulado
        self.assertEqual(bars["expense"][-2], 420000)  # barras de saída incluem os descontos

    def test_projection_and_history_expose_deductions(self):
        today = date.today()
        self.add_income("salario", 720000, today.replace(day=1))
        self.add_income("ir", 420000, today.replace(day=1), deduction=True)
        first = projection(fake_request(), self.db).context["months"][0]
        self.assertEqual((first["income"], first["deductions"], first["balance"]), (720000, 420000, 300000))
        history = history_page(fake_request(), f"{today.year:04d}-{today.month:02d}", self.db).context
        self.assertEqual(history["deductions_total"], 420000)

    def test_screens_render_new_deductions_card(self):
        html = dashboard(fake_request(), "2026-10", self.db).body.decode()
        self.assertIn("Descontos", html)
        self.assertIn("metric-deduction", html)


class RecurringIncomeTests(BaseCase):
    def test_until_month_creates_one_row_per_month(self):
        response = self.create_series()
        self.assertEqual(response.status_code, 303)
        series = self.db.scalar(select(RecurringIncome))
        rows = self.month_rows(series.id)
        self.assertEqual(len(rows), 7)  # nov/2026 a mai/2027
        self.assertEqual(rows[0].happened_on, date(2026, 11, 5))
        self.assertEqual(rows[-1].happened_on, date(2027, 5, 5))
        self.assertTrue(all(r.amount_cents == 720000 and r.included_in_cashflow for r in rows))

    def test_generation_is_idempotent_and_deleted_month_stays_deleted(self):
        self.create_series()
        series = self.db.scalar(select(RecurringIncome))
        self.assertEqual(ensure_recurring_incomes(self.db, FIXED_TODAY), 0)
        december = next(r for r in self.month_rows(series.id) if r.occurrence_month == date(2026, 12, 1))
        incomes_router.delete_income(december.id, scope="este", db=self.db)
        self.assertEqual(ensure_recurring_incomes(self.db, FIXED_TODAY), 0)
        self.assertEqual(len(self.month_rows(series.id)), 6)

    def test_open_ended_series_fills_12_months_ahead_and_grows_with_time(self):
        self.create_series(repeat="sem_fim", until="")
        series = self.db.scalar(select(RecurringIncome))
        self.assertIsNone(series.end_month)
        self.assertEqual(len(self.month_rows(series.id)), 12)  # nov/2026 a out/2027
        created = ensure_recurring_incomes(self.db, date(2026, 12, 15))
        self.assertEqual(created, 2)  # nov/2027 e dez/2027
        self.assertEqual(ensure_recurring_incomes(self.db, date(2026, 12, 15)), 0)

    def test_day_31_falls_on_last_day_of_shorter_months(self):
        self.create_series(start=date(2026, 12, 31), until="2027-03")
        series = self.db.scalar(select(RecurringIncome))
        dates = [r.happened_on for r in self.month_rows(series.id)]
        self.assertEqual(dates, [date(2026, 12, 31), date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)])

    def test_salary_and_deductions_series_leave_3000_each_month(self):
        self.create_series()
        for kind, amount in (("inss", "1000,00"), ("ir", "1200,00"), ("plano_saude", "800,00"), ("vale", "1200,00")):
            self.create_series(kind=kind, amount=amount)
        for year, month in ((2026, 11), (2027, 2), (2027, 5)):
            income = sum(i.amount_cents for i in incomes_for_month(self.db, year, month) if i.included_in_cashflow)
            deductions = payroll_deductions_for_month(self.db, year, month)
            self.assertEqual(income - deductions, 300000)
        self.assertEqual(payroll_deductions_for_month(self.db, 2027, 6), 0)

    def test_duplicate_series_is_rejected_but_new_series_after_end_is_allowed(self):
        self.create_series()
        response = self.create_series()
        self.assertIn("erro=", response.headers["location"])
        self.assertEqual(len(self.db.scalars(select(RecurringIncome)).all()), 1)
        # Reajuste: relança a partir de junho, depois do fim da série anterior.
        response = self.create_series(start=date(2027, 6, 5), amount="7600,00", until="2027-12")
        self.assertNotIn("erro=", response.headers["location"])
        self.assertEqual(len(self.db.scalars(select(RecurringIncome)).all()), 2)

    def test_invalid_end_month_is_rejected(self):
        response = self.create_series(until="2026-01")
        self.assertIn("erro=", response.headers["location"])
        response = self.create_series(until="")
        self.assertIn("erro=", response.headers["location"])
        self.assertEqual(self.db.scalar(select(RecurringIncome.id)), None)

    def test_edit_this_and_next_rewrites_following_months_only(self):
        self.create_series(repeat="sem_fim", until="")
        series = self.db.scalar(select(RecurringIncome))
        june = next(r for r in self.month_rows(series.id) if r.occurrence_month == date(2027, 6, 1))
        incomes_router.update_income(june.id, happened_on=date(2027, 6, 5), person_id=self.husband.id, kind="salario",
                                     amount="7600,00", description="", scope="proximos", end_mode="manter",
                                     until="", db=self.db)
        rows = self.month_rows(series.id)
        self.assertTrue(all(r.amount_cents == 720000 for r in rows if r.occurrence_month < date(2027, 6, 1)))
        self.assertTrue(all(r.amount_cents == 760000 for r in rows if r.occurrence_month >= date(2027, 6, 1)))
        self.db.refresh(series)
        self.assertEqual(series.amount_cents, 760000)
        # Meses novos gerados depois já saem com o valor reajustado.
        ensure_recurring_incomes(self.db, date(2027, 1, 10))
        self.assertEqual(self.month_rows(series.id)[-1].amount_cents, 760000)

    def test_edit_only_this_month_keeps_series_and_survives_regeneration(self):
        self.create_series()
        series = self.db.scalar(select(RecurringIncome))
        january = next(r for r in self.month_rows(series.id) if r.occurrence_month == date(2027, 1, 1))
        incomes_router.update_income(january.id, happened_on=date(2027, 1, 8), person_id=self.husband.id, kind="salario",
                                     amount="7500,00", description="bônus", scope="este", end_mode="manter",
                                     until="", db=self.db)
        ensure_recurring_incomes(self.db, FIXED_TODAY)
        self.db.refresh(january)
        self.assertEqual((january.amount_cents, january.happened_on), (750000, date(2027, 1, 8)))
        others = [r for r in self.month_rows(series.id) if r.id != january.id]
        self.assertTrue(all(r.amount_cents == 720000 for r in others))

    def test_edit_next_can_shorten_series_and_drops_later_rows(self):
        self.create_series()
        series = self.db.scalar(select(RecurringIncome))
        rows = self.month_rows(series.id)
        incomes_router.update_income(rows[0].id, happened_on=rows[0].happened_on, person_id=self.husband.id,
                                     kind="salario", amount="7200,00", description="", scope="proximos",
                                     end_mode="ate", until="2027-02", db=self.db)
        self.assertEqual(len(self.month_rows(series.id)), 4)  # nov, dez, jan, fev
        self.assertEqual(ensure_recurring_incomes(self.db, FIXED_TODAY), 0)
        incomes_router.update_income(rows[0].id, happened_on=rows[0].happened_on, person_id=self.husband.id,
                                     kind="salario", amount="7200,00", description="", scope="proximos",
                                     end_mode="sem_fim", until="", db=self.db)
        self.assertEqual(len(self.month_rows(series.id)), 12)

    def test_edit_changing_kind_to_deduction_changes_cashflow_flag(self):
        self.create_series(kind="extra", amount="100,00", until="2026-12")
        series = self.db.scalar(select(RecurringIncome))
        first = self.month_rows(series.id)[0]
        incomes_router.update_income(first.id, happened_on=first.happened_on, person_id=self.husband.id, kind="inss",
                                     amount="100,00", description="", scope="proximos", end_mode="manter", until="",
                                     db=self.db)
        self.assertTrue(all(not r.included_in_cashflow for r in self.month_rows(series.id)))

    def test_delete_this_and_next_ends_series_and_is_not_regenerated(self):
        self.create_series(repeat="sem_fim", until="")
        series = self.db.scalar(select(RecurringIncome))
        march = next(r for r in self.month_rows(series.id) if r.occurrence_month == date(2027, 3, 1))
        incomes_router.delete_income(march.id, scope="proximos", db=self.db)
        self.db.refresh(series)
        self.assertEqual(series.end_month, date(2027, 2, 1))
        self.assertEqual(len(self.month_rows(series.id)), 4)
        self.assertEqual(ensure_recurring_incomes(self.db, date(2028, 1, 1)), 0)

    def test_delete_from_first_month_deactivates_series(self):
        self.create_series()
        series = self.db.scalar(select(RecurringIncome))
        first = self.month_rows(series.id)[0]
        incomes_router.delete_income(first.id, scope="proximos", db=self.db)
        self.db.refresh(series)
        self.assertFalse(series.active)
        self.assertEqual(self.month_rows(series.id), [])

    def test_delete_whole_series(self):
        self.create_series()
        series = self.db.scalar(select(RecurringIncome))
        some = self.month_rows(series.id)[3]
        incomes_router.delete_income(some.id, scope="serie", db=self.db)
        self.assertIsNone(self.db.scalar(select(RecurringIncome.id)))
        self.assertIsNone(self.db.scalar(select(Income.id)))

    def test_single_income_keeps_working_without_recurrence(self):
        response = self.create_series(repeat="nao", until="")
        self.assertNotIn("erro=", response.headers["location"])
        income = self.db.scalar(select(Income))
        self.assertIsNone(income.recurring_income_id)
        incomes_router.delete_income(income.id, scope="este", db=self.db)
        self.assertIsNone(self.db.scalar(select(Income.id)))

    def test_pages_render_recurrence_controls(self):
        self.create_series()
        html = incomes_router.incomes_page(fake_request(), "2026-12", self.db).body.decode()
        self.assertIn('name="repeat"', html)
        self.assertIn("Repete todo mês até 05/2027", html)
        self.assertIn('name="scope"', html)
        income = self.db.scalar(select(Income))
        edit = incomes_router.edit_income_form(income.id, fake_request(), self.db).body.decode()
        self.assertIn("Este e os próximos meses", edit)


class CardEditingTests(BaseCase):
    def make_card(self, kind="credito", closing=10, due=17, limit=500000):
        card = CreditCard(name="Visa", owner_id=self.husband.id, kind=kind, closing_day=closing if kind == "credito" else 0,
                          due_day=due if kind == "credito" else 0, limit_cents=limit)
        self.db.add(card)
        self.db.commit()
        return card

    def buy(self, card, when, amount="300,00", installments=1, status="realizado"):
        create_transaction(None, description="Compra", amount=amount, purchase_date=when, category_id=self.category.id,
                           person_id=self.husband.id, account_id="", card_id=str(card.id), status=status,
                           installments=installments, db=self.db)

    def cashflows(self, card):
        rows = self.db.scalars(select(FinancialTransaction).where(FinancialTransaction.card_id == card.id)
                               .order_by(FinancialTransaction.id)).all()
        return [r.cashflow_date for r in rows]

    def test_changing_due_day_recalculates_every_purchase_including_past_and_installments(self):
        card = self.make_card()
        self.buy(card, date(2026, 10, 20))                       # fecha dia 10: vence 17/11
        self.buy(card, date(2026, 3, 5))                         # compra antiga, já realizada
        self.buy(card, date(2026, 10, 20), "900,00", 3)          # parcelas 17/11, 17/12, 17/01
        self.assertEqual(self.cashflows(card), [date(2026, 11, 17), date(2026, 3, 17), date(2026, 11, 17),
                                                date(2026, 12, 17), date(2027, 1, 17)])
        response = update_card(card.id, last_four_digits="", limit="8.000,00", closing_day=10, due_day=20, db=self.db)
        self.assertEqual(response.headers["location"], "/cadastros?ok=1")
        self.db.refresh(card)
        self.assertEqual((card.closing_day, card.due_day, card.limit_cents), (10, 20, 800000))
        self.assertEqual(self.cashflows(card), [date(2026, 11, 20), date(2026, 3, 20), date(2026, 11, 20),
                                                date(2026, 12, 20), date(2027, 1, 20)])

    def test_changing_closing_day_moves_purchase_to_other_invoice(self):
        card = self.make_card()
        self.buy(card, date(2026, 10, 12))
        # Fecha dia 10: a compra de 12/10 entra na fatura de novembro, que vence em 17/11.
        self.assertEqual(self.cashflows(card), [date(2026, 11, 17)])
        update_card(card.id, last_four_digits="", limit="5000,00", closing_day=15, due_day=17, db=self.db)
        # Fecha dia 15: a mesma compra passa para a fatura de outubro, que vence em 17/10.
        self.assertEqual(self.cashflows(card), [date(2026, 10, 17)])
        update_card(card.id, last_four_digits="", limit="5000,00", closing_day=5, due_day=17, db=self.db)
        self.assertEqual(self.cashflows(card), [date(2026, 11, 17)])

    def test_unchanged_cycle_does_not_touch_existing_dates(self):
        card = self.make_card()
        self.buy(card, date(2026, 10, 20))
        row = self.db.scalar(select(FinancialTransaction))
        row.cashflow_date = date(2026, 11, 30)  # ajuste manual que não deve ser sobrescrito
        self.db.commit()
        update_card(card.id, last_four_digits="1234", limit="9000,00", closing_day=10, due_day=17, db=self.db)
        self.db.refresh(row)
        self.assertEqual(row.cashflow_date, date(2026, 11, 30))
        self.db.refresh(card)
        self.assertEqual((card.last_four_digits, card.limit_cents), ("1234", 900000))

    def test_invalid_days_and_limit_are_rejected_without_changes(self):
        card = self.make_card()
        self.buy(card, date(2026, 10, 20))
        for kwargs in ({"closing_day": 32, "due_day": 17, "limit": "100,00"},
                       {"closing_day": 0, "due_day": 17, "limit": "100,00"},
                       {"closing_day": 10, "due_day": 17, "limit": "abc"},
                       {"closing_day": 10, "due_day": 17, "limit": "-5,00"}):
            response = update_card(card.id, last_four_digits="", db=self.db, **kwargs)
            self.assertIn("erro=", response.headers["location"], kwargs)
        self.db.refresh(card)
        self.assertEqual((card.closing_day, card.due_day, card.limit_cents), (10, 17, 500000))
        self.assertEqual(self.cashflows(card), [date(2026, 11, 17)])

    def test_debit_and_meal_voucher_only_edit_limit(self):
        for kind in ("debito", "vale_alimentacao"):
            card = self.make_card(kind=kind, limit=0)
            update_card(card.id, last_four_digits="4321", limit="1.500,00", closing_day=12, due_day=25, db=self.db)
            self.db.refresh(card)
            self.assertEqual((card.closing_day, card.due_day, card.limit_cents, card.last_four_digits),
                             (0, 0, 150000, "4321"))

    def test_recalculate_service_ignores_non_credit_cards(self):
        card = self.make_card(kind="debito")
        self.assertEqual(recalculate_card_cashflow(self.db, card), 0)

    def test_registration_page_shows_cycle_fields_only_for_credit_cards(self):
        credit = self.make_card()
        debit = self.make_card(kind="debito")
        html = registrations(fake_request(), self.db).body.decode()
        self.assertIn(f'action="/cadastros/cartoes/{credit.id}/editar"', html)
        credit_form = html.split(f'action="/cadastros/cartoes/{credit.id}/editar"')[1].split("</form>")[0]
        debit_form = html.split(f'action="/cadastros/cartoes/{debit.id}/editar"')[1].split("</form>")[0]
        self.assertIn('name="closing_day"', credit_form)
        self.assertIn('name="due_day"', credit_form)
        self.assertIn('value="5000,00"', credit_form)
        self.assertNotIn('name="closing_day"', debit_form)
        self.assertIn('name="limit"', debit_form)

    def test_invoice_due_date_still_follows_new_cycle(self):
        card = self.make_card()
        update_card(card.id, last_four_digits="", limit="5000,00", closing_day=10, due_day=20, db=self.db)
        self.db.refresh(card)
        self.assertEqual(invoice_due_date(card, date(2026, 10, 20)), date(2026, 11, 20))


class MigrationTests(unittest.TestCase):
    def test_old_incomes_table_gets_recurrence_columns_and_keeps_rows(self):
        path = os.path.join(tempfile.mkdtemp(prefix="migracao-"), "antigo.db")
        engine = create_engine(f"sqlite:///{path}", future=True)
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE people (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE, active BOOLEAN NOT NULL DEFAULT 1)"))
            connection.execute(text("""CREATE TABLE incomes (
                id INTEGER PRIMARY KEY, person_id INTEGER NOT NULL REFERENCES people(id), kind VARCHAR(30) NOT NULL,
                happened_on DATE NOT NULL, amount_cents INTEGER NOT NULL, description VARCHAR(240) NOT NULL DEFAULT '',
                included_in_cashflow BOOLEAN NOT NULL DEFAULT 1)"""))
            connection.execute(text("INSERT INTO people (id, name) VALUES (1, 'Marido')"))
            connection.execute(text("INSERT INTO incomes (person_id, kind, happened_on, amount_cents) VALUES (1, 'salario', '2026-10-05', 720000)"))
        with patch.object(database, "engine", engine), patch.object(database, "DATABASE_URL", f"sqlite:///{path}"):
            database.migrate_database()
            database.migrate_database()  # idempotente
        inspector = inspect(engine)
        columns = {c["name"] for c in inspector.get_columns("incomes")}
        self.assertTrue({"recurring_income_id", "occurrence_month"} <= columns)
        self.assertIn("recurring_incomes", inspector.get_table_names())
        self.assertIn("uq_income_recurring_occurrence", {i["name"] for i in inspector.get_indexes("incomes")})
        with Session(engine) as session:
            row = session.scalar(select(Income))
            self.assertEqual((row.amount_cents, row.recurring_income_id, row.occurrence_month), (720000, None, None))
            # Várias linhas antigas (NULL, NULL) não conflitam com o índice único.
            session.add(Income(person_id=1, kind="extra", happened_on=date(2026, 10, 6), amount_cents=100))
            session.commit()
        engine.dispose()


class TemplateMarkupTests(unittest.TestCase):
    def test_stylesheet_and_script_tags_have_balanced_quotes(self):
        """Uma aspa faltando em <link> faz o navegador ignorar o CSS e o layout inteiro desmonta."""
        templates = Path(__file__).resolve().parent.parent / "app" / "templates"
        link = re.compile(r'<link rel="stylesheet" href="[^"\s>]+">')
        for path in templates.rglob("*.html"):
            for number, line in enumerate(path.read_text().splitlines(), 1):
                if re.match(r"\s*<(link|meta|script[^>]*\bsrc)\b", line):
                    self.assertEqual(line.count('"') % 2, 0, f"{path.name}:{number} tem aspas desbalanceadas: {line.strip()}")
                if "stylesheet" in line:
                    self.assertRegex(line, link, f"{path.name}:{number}")


if __name__ == "__main__":
    unittest.main()
