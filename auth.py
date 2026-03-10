"""
Sistema de autenticacao JWT.
"""
from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from config import ACCESS_TOKEN_EXPIRE_HOURS, ALGORITHM, SECRET_KEY
from storage import JsonStorage


storage = JsonStorage()
ROLE_ADMIN = "administrador"
ROLE_BUYER = "comprador"
ROLE_DEVELOPER = "desenvolvedor"

# Contexto para hash de senhas
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    """Verifica se a senha corresponde ao hash."""
    return pwd_context.verify(senha, senha_hash)


def criar_hash_senha(senha: str) -> str:
    """Cria um hash da senha."""
    return pwd_context.hash(senha)


def criar_token_acesso(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Cria um token JWT de acesso."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_token(token: str) -> Optional[dict[str, Any]]:
    """Decodifica um token JWT."""
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


async def get_usuario_atual(
    token: str = Depends(oauth2_scheme),
) -> dict[str, Any]:
    """Obtem o usuario atual a partir do token JWT."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nao foi possivel validar as credenciais",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decodificar_token(token)
    if payload is None:
        raise credentials_exception

    user_id = payload.get("uid")
    usuario = storage.find_user_by_id(user_id) if user_id else None
    if usuario is None:
        email = payload.get("sub")
        if not email:
            raise credentials_exception
        usuario = storage.find_user_by_email(email)
    if usuario is None:
        raise credentials_exception

    if not usuario.get("ativo", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo",
        )

    return usuario


async def get_comprador_atual(
    usuario: dict[str, Any] = Depends(get_usuario_atual),
) -> dict[str, Any]:
    """Verifica se o usuario atual e um comprador."""
    if usuario.get("tipo") != ROLE_BUYER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acesso restrito a compradores",
        )
    return usuario


def exigir_perfis(*perfis: str):
    async def dependency(usuario: dict[str, Any] = Depends(get_usuario_atual)) -> dict[str, Any]:
        if usuario.get("tipo") not in perfis:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Voce nao tem permissao para acessar este recurso",
            )
        return usuario

    return dependency


get_admin_ou_desenvolvedor_atual = exigir_perfis(ROLE_ADMIN, ROLE_DEVELOPER)
get_desenvolvedor_atual = exigir_perfis(ROLE_DEVELOPER)
