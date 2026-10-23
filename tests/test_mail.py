import smtplib
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.invites import STATUS_AVAILABLE, create_invite, format_invite_code, normalize_invite_code
from app.mail import MAIL_ERROR_MESSAGE, MailDeliveryError, _send_email
from app.main import app
from app.models import AccountInvite, EmailToken, User
from tests.test_app import register_active
from tests.test_invites import _closed

client = TestClient(app)


class _FakeSMTP:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def starttls(self):
        return None

    def login(self, *args):
        return None

    def send_message(self, *args, **kwargs):
        raise smtplib.SMTPRecipientsRefused({"dest@example.com": (550, b"denied")})


@pytest.fixture
def deny_smtp(monkeypatch):
    monkeypatch.setattr("app.mail.SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("app.mail.smtplib.SMTP", _FakeSMTP)


def test_send_email_wraps_smtp_550(deny_smtp):
    try:
        _send_email("dest@example.com", "Assunto", "corpo")
        raise AssertionError("expected MailDeliveryError")
    except MailDeliveryError as exc:
        assert MAIL_ERROR_MESSAGE in str(exc)


def test_open_register_smtp_failure_does_not_create_user(deny_smtp):
    response = TestClient(app).post(
        "/register",
        data={
            "name": "Mail Fail",
            "username": "mail_fail_open",
            "email": "mail.fail.open@example.com",
            "password": "segredo",
        },
    )
    assert response.status_code == 400
    assert MAIL_ERROR_MESSAGE in response.text
    assert "mail.fail.open@example.com" in response.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "mail.fail.open@example.com")) is None
    finally:
        db.close()


def test_closed_register_smtp_failure_keeps_invite_available(monkeypatch, deny_smtp):
    _closed(monkeypatch)
    db = SessionLocal()
    try:
        invite = create_invite(db)
        db.commit()
        code = format_invite_code(invite.code)
        canonical = invite.code
    finally:
        db.close()
    response = TestClient(app).post(
        "/register",
        data={
            "name": "Mail Fail",
            "username": "mail_fail_closed",
            "email": "mail.fail.closed@example.com",
            "password": "segredo",
            "invite_code": code,
        },
    )
    assert response.status_code == 400
    assert MAIL_ERROR_MESSAGE in response.text
    db = SessionLocal()
    try:
        assert db.scalar(select(User).where(User.email == "mail.fail.closed@example.com")) is None
        row = db.scalar(select(AccountInvite).where(AccountInvite.code == canonical))
        assert row.status == STATUS_AVAILABLE
        assert row.used_by_user_id is None
        assert normalize_invite_code(code) == canonical
    finally:
        db.close()


def test_resend_and_inactive_login_smtp_failure(monkeypatch):
    pending = TestClient(app)
    created = pending.post(
        "/register",
        data={
            "name": "Pendente Mail",
            "username": "pendente_mail",
            "email": "pendente.mail@example.com",
            "password": "segredo",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    monkeypatch.setattr("app.mail.SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("app.mail.smtplib.SMTP", _FakeSMTP)
    resend = pending.post(
        "/verificar-email/reenviar",
        data={"email": "pendente.mail@example.com"},
        follow_redirects=False,
    )
    login = pending.post(
        "/login",
        data={"email": "pendente.mail@example.com", "password": "segredo"},
    )
    assert resend.status_code == 303
    assert MAIL_ERROR_MESSAGE in unquote(resend.headers["location"])
    assert login.status_code == 400
    assert MAIL_ERROR_MESSAGE in login.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == "pendente.mail@example.com"))
        assert user is not None
        assert user.is_active is False
        assert db.scalar(select(EmailToken).where(EmailToken.user_id == user.id)) is not None
    finally:
        db.close()


def test_forgot_password_smtp_failure(monkeypatch):
    register_active(client, "reset_mail", "reset.mail@example.com")
    monkeypatch.setattr("app.mail.SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("app.mail.smtplib.SMTP", _FakeSMTP)
    response = TestClient(app).post("/recuperar-senha", data={"email": "reset.mail@example.com"})
    assert response.status_code == 400
    assert MAIL_ERROR_MESSAGE in response.text
    assert "reset.mail@example.com" in response.text


def test_profile_email_change_smtp_failure_does_not_set_pending(monkeypatch):
    person = TestClient(app)
    register_active(person, "troca_mail", "troca.mail@example.com")
    monkeypatch.setattr("app.mail.SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr("app.mail.smtplib.SMTP", _FakeSMTP)
    response = person.post(
        "/conta/perfil",
        data={"name": "Troca Mail", "username": "troca_mail", "email": "novo.troca.mail@example.com", "bio": ""},
    )
    assert response.status_code == 400
    assert MAIL_ERROR_MESSAGE in response.text
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username_key == "troca_mail"))
        assert user.email == "troca.mail@example.com"
        assert user.pending_email is None
    finally:
        db.close()
