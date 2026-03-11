"""
Servico de envio de emails transacionais via Brevo.
"""
from __future__ import annotations

import json
from typing import Any
from urllib import error, request

from config import (
    BREVO_API_BASE_URL,
    BREVO_API_KEY,
    BREVO_SANDBOX_MODE,
    MAIL_FROM_EMAIL,
    MAIL_FROM_NAME,
    PASSWORD_RESET_EXPIRE_MINUTES,
)


class EmailServiceError(RuntimeError):
    """Erro no envio de email."""


def _get_sender_email() -> str:
    sender_email = MAIL_FROM_EMAIL.strip()
    if not sender_email:
        raise EmailServiceError(
            "MAIL_FROM_EMAIL ou SMTP_FROM_EMAIL nao configurado com um remetente valido na Brevo"
        )

    if sender_email.lower().endswith("@smtp-brevo.com"):
        raise EmailServiceError(
            "MAIL_FROM_EMAIL invalido: use um remetente validado na Brevo, nao o login SMTP"
        )

    return sender_email


def _post_brevo(payload: dict[str, Any]) -> dict[str, Any]:
    if not BREVO_API_KEY:
        raise EmailServiceError("BREVO_API_KEY nao configurada")

    req = request.Request(
        f"{BREVO_API_BASE_URL}/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json",
        },
        method="POST",
    )

    if BREVO_SANDBOX_MODE:
        req.add_header("x-sib-sandbox", "drop")

    try:
        with request.urlopen(req, timeout=20) as response:
            raw_response = response.read()
            if not raw_response:
                return {}
            return json.loads(raw_response.decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise EmailServiceError(
            f"Falha ao enviar email pela Brevo: HTTP {exc.code} {detail}"
        ) from exc
    except error.URLError as exc:
        raise EmailServiceError("Falha de rede ao enviar email pela Brevo") from exc


def send_password_reset_email(
    destinatario_email: str,
    destinatario_nome: str,
    codigo: str,
) -> dict[str, Any]:
    sender_email = _get_sender_email()
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; background:#f6f8f6; padding:24px; color:#1a281d;">
            <div style="max-width:560px; margin:0 auto; background:#ffffff; border:1px solid #d8e1d8; border-radius:18px; padding:32px;">
                <h1 style="margin:0 0 12px; font-size:24px; color:#14532d;">Recuperacao de senha</h1>
                <p style="margin:0 0 16px;">Ola, {destinatario_nome}.</p>
                <p style="margin:0 0 16px;">
                    Recebemos uma solicitacao para redefinir sua senha no Sistema de Agendamento.
                </p>
                <p style="margin:0 0 12px;">Use o codigo abaixo para continuar:</p>
                <div style="margin:20px 0; padding:18px; border-radius:14px; background:#f1f8f3; border:1px solid #cfe2d3; text-align:center; font-size:28px; letter-spacing:0.3em; font-weight:700; color:#1f7a3f;">
                    {codigo}
                </div>
                <p style="margin:0 0 14px;">
                    Esse codigo expira em {PASSWORD_RESET_EXPIRE_MINUTES} minutos.
                </p>
                <p style="margin:0; color:#5f6f63; font-size:13px;">
                    Se voce nao solicitou essa alteracao, ignore este email.
                </p>
            </div>
        </body>
    </html>
    """

    payload = {
        "sender": {
            "email": sender_email,
            "name": MAIL_FROM_NAME,
        },
        "to": [{"email": destinatario_email, "name": destinatario_nome}],
        "subject": "Codigo de recuperacao de senha",
        "htmlContent": html,
    }

    return _post_brevo(payload)
