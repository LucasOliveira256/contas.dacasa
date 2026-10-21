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
        self.assertEqual(self.client.get("/").status_code, 200)

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
        self.assertIn("/usuarios?ok=1", response.headers["location"])

        response = self.client.post("/logout", data={"_csrf": token}, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        response = self.client.get("/login")
        token = csrf_token(response.text)
        response = self.client.post("/login", data={
            "username": "esposa", "password": "PrimeiraSenha2026!", "next_url": "/", "_csrf": token,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIn("/alterar-senha", response.headers["location"])
        response = self.client.get("/alterar-senha")
        token = csrf_token(response.text)
        response = self.client.post("/alterar-senha", data={
            "current_password": "PrimeiraSenha2026!",
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
