"""
Modelos do Banco de Dados - Sistema de Agendamento
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Enum, Boolean
from sqlalchemy.orm import relationship, declarative_base
import enum

Base = declarative_base()


class TipoUsuario(enum.Enum):
    COMPRADOR = "comprador"
    VENDEDOR = "vendedor"


class StatusAgendamento(enum.Enum):
    PENDENTE = "pendente"
    CONFIRMADO = "confirmado"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"


class Usuario(Base):
    __tablename__ = "usuarios"
    
    id = Column(Integer, primary_key=True, index=True)
    nome = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    senha_hash = Column(String(255), nullable=False)
    tipo = Column(String(20), nullable=False)  # comprador ou vendedor
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    
    # Relacionamentos
    agendamentos_como_comprador = relationship("Agendamento", back_populates="comprador", foreign_keys="Agendamento.comprador_id")
    agendamentos_como_vendedor = relationship("Agendamento", back_populates="vendedor", foreign_keys="Agendamento.vendedor_id")


class Agendamento(Base):
    __tablename__ = "agendamentos"
    
    id = Column(Integer, primary_key=True, index=True)
    comprador_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False)
    vendedor_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    nome_vendedor = Column(String(100), nullable=False)
    empresa_vendedor = Column(String(100), nullable=True)
    telefone_vendedor = Column(String(20), nullable=True)
    email_vendedor = Column(String(100), nullable=False)
    data_hora = Column(DateTime, nullable=False)
    status = Column(String(20), default="pendente")
    observacoes = Column(String(500), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow)
    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relacionamentos
    comprador = relationship("Usuario", back_populates="agendamentos_como_comprador", foreign_keys=[comprador_id])
    vendedor = relationship("Usuario", back_populates="agendamentos_como_vendedor", foreign_keys=[vendedor_id])
