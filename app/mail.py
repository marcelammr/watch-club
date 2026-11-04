from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.config import APP_BASE_URL, EMAIL_FROM, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

MAIL_ERROR_MESSAGE = "Não foi possível enviar o e-mail agora. Tente de novo em alguns minutos."


class MailDeliveryError(Exception):
    """Falha ao entregar e-mail via SMTP ou rede."""


def verification_url(token: str) -> str:
    return f"{APP_BASE_URL.rstrip('/')}/verificar-email?token={token}"


def login_url() -> str:
    return f"{APP_BASE_URL.rstrip('/')}/auth/login"


def _send_email(to_email: str, subject: str, body: str) -> None:
    print(f"[watch-club] {subject} para {to_email}")
    if not SMTP_HOST:
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = EMAIL_FROM
    message["To"] = to_email
    message.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.starttls()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        print(f"[watch-club] falha ao enviar e-mail para {to_email}: {exc.__class__.__name__}")
        raise MailDeliveryError(MAIL_ERROR_MESSAGE) from exc


def send_verification_email(to_email: str, url: str) -> None:
    body = (
        "Olá!\n\n"
        "Para ativar sua conta no Watch Club, abra este link:\n"
        f"{url}\n\n"
        "Se você não criou a conta, ignore este e-mail.\n"
    )
    print(f"[watch-club] e-mail de verificação para {to_email}: {url}")
    _send_email(to_email, "Ative sua conta no Watch Club", body)


def send_registration_approved_email(to_email: str, name: str) -> None:
    url = login_url()
    display = (name or "").strip() or "olá"
    body = (
        f"Olá, {display}!\n\n"
        "Seu acesso ao Watch Club foi aprovado.\n\n"
        "Agora você já pode entrar na sua conta e aproveitar o Watch Club.\n\n"
        f"Entrar no Watch Club:\n{url}\n\n"
        "Até logo,\n"
        "Watch Club\n"
    )
    _send_email(to_email, "Seu acesso ao Watch Club foi aprovado", body)


def send_registration_rejected_email(to_email: str, name: str) -> None:
    display = (name or "").strip() or "olá"
    body = (
        f"Olá, {display}.\n\n"
        "Sua solicitação de acesso ao Watch Club não foi aprovada neste momento.\n\n"
        "Se precisar, você poderá solicitar uma revisão pelo próprio Watch Club.\n\n"
        "Até logo,\n"
        "Watch Club\n"
    )
    _send_email(to_email, "Sobre sua solicitação de acesso ao Watch Club", body)


def send_password_reset_email(to_email: str, code: str) -> None:
    body = (
        "Olá!\n\n"
        "Use este código para redefinir a senha no Watch Club:\n\n"
        f"    {code}\n\n"
        "Ele vale por 15 minutos. Se você não pediu a troca, ignore este e-mail.\n"
    )
    print(f"[watch-club] código de recuperação para {to_email}: {code}")
    _send_email(to_email, "Código para redefinir sua senha", body)
