"""
Configuracoes do Sistema de Agendamento.
"""
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent

if load_dotenv:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(BASE_DIR / ".env")

# Configuracoes JWT
SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "sua-chave-secreta-muito-segura-mude-em-producao-2026",
)
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", "8"))

# Configuracoes CORS
_cors_env = os.getenv("CORS_ORIGINS", "")
if _cors_env.strip():
    CORS_ORIGINS = [origin.strip() for origin in _cors_env.split(",") if origin.strip()]
else:
    CORS_ORIGINS = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "https://popularatacarejo.github.io",
        "https://agendamento-web.onrender.com",
    ]

# Persistencia no GitHub
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GITHUB_REPO_OWNER = os.getenv("GITHUB_REPO_OWNER", "PopularAtacarejo")
GITHUB_REPO_NAME = os.getenv("GITHUB_REPO_NAME", "Agendamento-Compras")
GITHUB_REPO_BRANCH = os.getenv("GITHUB_REPO_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
AUTH_FILE_PATH = os.getenv("AUTH_FILE_PATH", "auth.json")
AGENDAMENTOS_FILE_PATH = os.getenv("AGENDAMENTOS_FILE_PATH", "agendamentos.json")

# Horarios de funcionamento
HORARIO_INICIO = int(os.getenv("HORARIO_INICIO", "8"))
HORARIO_FIM = int(os.getenv("HORARIO_FIM", "18"))
INTERVALO_MINUTOS = int(os.getenv("INTERVALO_MINUTOS", "30"))

# Email / recuperacao de senha
SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_LOGIN = os.getenv("SMTP_LOGIN", "")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_API_BASE_URL = os.getenv("BREVO_API_BASE_URL", "https://api.brevo.com/v3").rstrip("/")
BREVO_SANDBOX_MODE = os.getenv("BREVO_SANDBOX_MODE", "0") == "1"
MAIL_FROM_EMAIL = os.getenv("MAIL_FROM_EMAIL", SMTP_LOGIN)
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Popular Atacarejo")
PASSWORD_RESET_EXPIRE_MINUTES = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "15"))
