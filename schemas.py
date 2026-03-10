"""
Schemas Pydantic para validacao de dados.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


USER_TYPES = {"comprador", "administrador", "desenvolvedor"}
AGENDAMENTO_STATUS = {
    "pendente",
    "confirmado",
    "concluido",
    "cancelado",
    "desistiu",
    "nao_compareceu",
}


class UsuarioBase(BaseModel):
    nome: str
    email: EmailStr
    telefone: Optional[str] = None
    foto_url: Optional[str] = None
    mensagem_whatsapp: Optional[str] = None


class UsuarioCreate(UsuarioBase):
    senha: str
    tipo: str
    ativo: bool = True

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, value: str) -> str:
        if value not in USER_TYPES:
            raise ValueError('Tipo deve ser "comprador", "administrador" ou "desenvolvedor"')
        return value


class UsuarioUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[EmailStr] = None
    senha: Optional[str] = None
    tipo: Optional[str] = None
    ativo: Optional[bool] = None

    @field_validator("nome", "senha")
    @classmethod
    def validar_texto(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value not in USER_TYPES:
            raise ValueError('Tipo deve ser "comprador", "administrador" ou "desenvolvedor"')
        return value


class UsuarioLogin(BaseModel):
    email: EmailStr
    senha: str


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    email: EmailStr
    codigo: str
    nova_senha: str

    @field_validator("codigo")
    @classmethod
    def validar_codigo(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 4:
            raise ValueError("Codigo invalido")
        return value

    @field_validator("nova_senha")
    @classmethod
    def validar_nova_senha(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 6:
            raise ValueError("A nova senha deve ter pelo menos 6 caracteres")
        return value


class UsuarioProfileUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[EmailStr] = None
    telefone: Optional[str] = None
    foto_url: Optional[str] = None
    mensagem_whatsapp: Optional[str] = None
    senha_atual: Optional[str] = None
    nova_senha: Optional[str] = None

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("foto_url")
    @classmethod
    def validar_foto(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("mensagem_whatsapp")
    @classmethod
    def validar_mensagem_whatsapp(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class UsuarioResponse(UsuarioBase):
    id: int
    tipo: str
    ativo: bool
    criado_em: datetime


class CompradorListResponse(BaseModel):
    id: int
    nome: str
    email: str
    foto_url: Optional[str] = None


class AgendamentoBase(BaseModel):
    comprador_id: int
    data_hora: datetime
    nome_vendedor: str
    empresa_vendedor: Optional[str] = None
    telefone_vendedor: Optional[str] = None
    email_vendedor: EmailStr
    observacoes: Optional[str] = None


class AgendamentoCreate(AgendamentoBase):
    pass


class AgendamentoUpdate(BaseModel):
    status: Optional[str] = None
    observacoes: Optional[str] = None
    comentario_comprador: Optional[str] = None
    motivo_vendedor: Optional[str] = None

    @field_validator("status")
    @classmethod
    def validar_status(cls, value: Optional[str]) -> Optional[str]:
        if value and value not in AGENDAMENTO_STATUS:
            raise ValueError("Status invalido")
        return value

    @field_validator("comentario_comprador")
    @classmethod
    def validar_comentario(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @field_validator("motivo_vendedor")
    @classmethod
    def validar_motivo_vendedor(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class AgendamentoResponse(AgendamentoBase):
    id: int
    vendedor_id: Optional[int]
    status: str
    comentario_comprador: Optional[str] = None
    motivo_vendedor: Optional[str] = None
    criado_em: datetime
    atualizado_em: datetime


class AgendamentoDetalhadoResponse(AgendamentoResponse):
    nome_comprador: Optional[str] = None


class VendedorVisitaResponse(BaseModel):
    id: int
    nome_vendedor: str
    empresa_vendedor: Optional[str] = None
    telefone_vendedor: Optional[str] = None
    email_vendedor: EmailStr
    data_hora: datetime
    status: str
    observacoes: Optional[str] = None
    motivo_vendedor: Optional[str] = None
    nome_comprador: str


class VisitaDesistenciaRequest(BaseModel):
    telefone: str
    motivo: str

    @field_validator("telefone")
    @classmethod
    def validar_telefone(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Telefone obrigatorio")
        return value

    @field_validator("motivo")
    @classmethod
    def validar_motivo(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Informe o motivo da desistencia")
        return value


class Token(BaseModel):
    access_token: str
    token_type: str
    usuario: UsuarioResponse


class HorarioDisponivel(BaseModel):
    data_hora: datetime
    disponivel: bool


class DisponibilidadeResponse(BaseModel):
    comprador_id: int
    data: str
    horarios: list[HorarioDisponivel]


class DisponibilidadeCreate(BaseModel):
    data_hora: datetime


class DisponibilidadeSlotResponse(BaseModel):
    id: int
    comprador_id: int
    data_hora: datetime
    disponivel: bool
    ocupado: bool
    nome_vendedor: Optional[str] = None
    status_agendamento: Optional[str] = None
    criado_em: datetime


class StatusResponse(BaseModel):
    status: str
    mensagem: str
