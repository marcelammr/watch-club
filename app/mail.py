from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import APP_BASE_URL, EMAIL_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER


def verification_url(token: str) -> str:
    return f"{APP_BASE_URL.rstrip('/')}/verificar-email?token={token}"


def _send_email(to_email: str, subject: str, body: str) -> None:
    print(f"[watch-club] {subject} para {to_email}")
    if not SMTP_HOST:
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = to_email
    message.set_content(body)
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)


def send_verification_email(to_email: str, url: str) -> None:
    body = (
        "Olá!\n\n"
        "Para ativar sua conta no Watch Club, abra este link:\n"
        f"{url}\n\n"
        "Se você não criou a conta, ignore este e-mail.\n"
    )
    print(f"[watch-club] e-mail de verificação para {to_email}: {url}")
    _send_email(to_email, "Ative sua conta no Watch Club", body)


def send_password_reset_email(to_email: str, code: str) -> None:
    body = (
        "Olá!\n\n"
        "Use este código para redefinir a senha no Watch Club:\n\n"
        f"    {code}\n\n"
        "Ele vale por 15 minutos. Se você não pediu a troca, ignore este e-mail.\n"
    )
    print(f"[watch-club] código de recuperação para {to_email}: {code}")
    _send_email(to_email, "Código para redefinir sua senha", body)
