"""Teste integrado de login, troca obrigatória de senha e controle de CSRF."""
import os
import re
import tempfile
import unittest
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="casa-em-ordem-auth-test-"))
os.environ["DATABASE_URL"] = f"sqlite:////{str(_TEST_ROOT / 'test.db').lstrip('/')}"
os.environ["SESSION_SECRET_FILE"] = str(_TEST_ROOT / "session_secret.key")
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Person, CreditCard, User  # noqa: E402


def csrf_token(html: str) -> str:
    match = re.search(r'name="_csrf" value="([^"]+)"', html)
    if not match:
        raise AssertionError("Token CSRF não encontrado no formulário")
    return match.group(1)


class AuthenticationFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_admin_login_password_rotation_csrf_and_new_user(self):
        # A aplicação exige autenticação antes de exibir o dashboard.
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login"))

        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/login", data={
            "username": "Admin", "password": "admin", "next_url": "/", "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/alterar-senha", response.headers["location"])

        response = self.client.get("/alterar-senha")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/alterar-senha", data={
            "current_password": "admin",
            "new_password": "SenhaSeguraCasa2026!",
            "confirm_password": "SenhaSeguraCasa2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/?ok=1")
        dashboard = self.client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn('id="chart-cashflow"', dashboard.text)
        self.assertIn('class="sidebar"', dashboard.text)
        self.assertIn('data-theme="dark"', dashboard.text)
        self.assertRegex(dashboard.text, r'(Bom dia|Boa tarde|Boa noite), família')

        # O cadastro armazena apenas os quatro últimos dígitos, exibidos no cartão visual.
        db = SessionLocal()
        try:
            husband = db.query(Person).filter(Person.name == "Marido").first()
            husband_id = husband.id
        finally:
            db.close()
        registration = self.client.get("/cadastros")
        token = csrf_token(registration.text)
        response = self.client.post("/cadastros/cartoes", data={
            "_csrf": token, "name": "Nubank Roxinho", "owner_id": str(husband_id),
            "kind": "credito", "closing_day": "10", "due_day": "17",
            "limit": "1500,00", "last_four_digits": "4821", "payment_account_id": "",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        card_page = self.client.get("/cartoes")
        self.assertEqual(card_page.status_code, 200)
        self.assertIn("bank-card-nubank", card_page.text)
        self.assertIn("4821", card_page.text)
        self.assertIn("Entradas x saídas", dashboard.text)

        # Um POST sem token CSRF é bloqueado mesmo com uma sessão autenticada.
        response = self.client.post("/usuarios", data={
            "username": "sem-token", "password": "SenhaSeguraUsuario2026!",
            "confirm_password": "SenhaSeguraUsuario2026!",
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 403)

        response = self.client.get("/usuarios")
        self.assertEqual(response.status_code, 200)
        token = csrf_token(response.text)
        response = self.client.post("/usuarios", data={
            "username": "esposa",
            "password": "PrimeiraSenha2026!",
            "confirm_password": "PrimeiraSenha2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/usuarios?ok=criado", response.headers["location"])

        # Admin pode redefinir a senha de outro usuário e força a troca no próximo login.
        db = SessionLocal()
        try:
            wife_user_id = db.scalar(__import__("sqlalchemy").select(User.id).where(User.username_key == "esposa"))
        finally:
            db.close()
        users_page = self.client.get("/usuarios")
        self.assertIn(f'action="/usuarios/{wife_user_id}/senha"', users_page.text)
        token = csrf_token(users_page.text)
        response = self.client.post(f"/usuarios/{wife_user_id}/senha", data={
            "new_password": "SenhaProvisoriaNova2026!",
            "confirm_password": "SenhaProvisoriaNova2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/usuarios?ok=senha", response.headers["location"])
        db = SessionLocal()
        try:
            wife_user = db.get(User, wife_user_id)
            self.assertTrue(wife_user.must_change_password)
            self.assertGreaterEqual(wife_user.session_version, 1)
        finally:
            db.close()

        response = self.client.post("/logout", data={"_csrf": token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.get("/login")
        token = csrf_token(response.text)
        response = self.client.post("/login", data={
            "username": "esposa", "password": "SenhaProvisoriaNova2026!", "next_url": "/", "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/alterar-senha", response.headers["location"])
        response = self.client.get("/alterar-senha")
        token = csrf_token(response.text)
        response = self.client.post("/alterar-senha", data={
            "current_password": "SenhaProvisoriaNova2026!",
            "new_password": "OutraSenhaSegura2026!",
            "confirm_password": "OutraSenhaSegura2026!",
            "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.get("/usuarios", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/?erro="))


if __name__ == "__main__":
    unittest.main()
