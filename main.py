"""
Sistema de Agendamento - API principal.
"""
from datetime import date, datetime, timedelta
import logging
import secrets
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from auth import (
    ROLE_ADMIN,
    ROLE_BUYER,
    ROLE_DEVELOPER,
    criar_hash_senha,
    criar_token_acesso,
    get_admin_ou_desenvolvedor_atual,
    get_comprador_atual,
    get_usuario_atual,
    storage,
    verificar_senha,
)
from config import CORS_ORIGINS, HORARIO_FIM, HORARIO_INICIO, INTERVALO_MINUTOS
from config import MAIL_FROM_EMAIL, PASSWORD_RESET_EXPIRE_MINUTES
from email_service import EmailServiceError, send_password_reset_email
from schemas import (
    AgendamentoCreate,
    AgendamentoDetalhadoResponse,
    AgendamentoResponse,
    AgendamentoUpdate,
    CompradorListResponse,
    DisponibilidadeCreate,
    DisponibilidadeResponse,
    DisponibilidadeSlotResponse,
    HorarioDisponivel,
    PasswordResetConfirm,
    PasswordResetRequest,
    StatusResponse,
    Token,
    UsuarioCreate,
    UsuarioLogin,
    UsuarioProfileUpdate,
    UsuarioResponse,
    UsuarioUpdate,
    VendedorVisitaResponse,
    VisitaDesistenciaRequest,
)
from storage import StorageError


DEFAULT_DEVELOPER = {
    "nome": "Jeferson",
    "email": "djaxelf22@gmail.com",
    "senha": "873090As#",
    "tipo": ROLE_DEVELOPER,
}

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Sistema de Agendamento - Setor de Compras",
    description="API para agendamento de visitas entre vendedores e compradores",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event() -> None:
    """Inicializa os arquivos de dados e garante o usuario desenvolvedor inicial."""
    try:
        storage.initialize_files()
        _garantir_usuarios_iniciais()
    except StorageError as exc:
        print(f"Erro ao inicializar armazenamento: {exc}")


def _parse_datetime(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _serialize_usuario(usuario: dict) -> UsuarioResponse:
    return UsuarioResponse(
        id=usuario["id"],
        nome=usuario["nome"],
        email=usuario["email"],
        telefone=usuario.get("telefone"),
        foto_url=usuario.get("foto_url"),
        mensagem_whatsapp=usuario.get("mensagem_whatsapp"),
        tipo=usuario["tipo"],
        ativo=usuario.get("ativo", True),
        criado_em=_parse_datetime(usuario["criado_em"]),
    )


def _serialize_agendamento(agendamento: dict) -> AgendamentoResponse:
    return AgendamentoResponse(
        id=agendamento["id"],
        comprador_id=agendamento["comprador_id"],
        vendedor_id=agendamento.get("vendedor_id"),
        nome_vendedor=agendamento["nome_vendedor"],
        empresa_vendedor=agendamento.get("empresa_vendedor"),
        telefone_vendedor=agendamento.get("telefone_vendedor"),
        email_vendedor=agendamento["email_vendedor"],
        data_hora=_parse_datetime(agendamento["data_hora"]),
        status=agendamento["status"],
        observacoes=agendamento.get("observacoes"),
        comentario_comprador=agendamento.get("comentario_comprador"),
        motivo_vendedor=agendamento.get("motivo_vendedor"),
        criado_em=_parse_datetime(agendamento["criado_em"]),
        atualizado_em=_parse_datetime(agendamento["atualizado_em"]),
    )


def _serialize_agendamento_detalhado(
    agendamento: dict,
    nome_comprador: Optional[str] = None,
) -> AgendamentoDetalhadoResponse:
    base = _serialize_agendamento(agendamento)
    return AgendamentoDetalhadoResponse(**base.model_dump(), nome_comprador=nome_comprador)


def _mapear_agendamentos_ativos_por_data(
    agendamentos: list[dict],
    comprador_id: int,
) -> dict[datetime, dict]:
    return {
        _parse_datetime(item["data_hora"]): item
        for item in agendamentos
        if item["comprador_id"] == comprador_id and item["status"] in ["pendente", "confirmado"]
    }


def _serialize_disponibilidade(
    disponibilidade: dict,
    agendamento_ativo: Optional[dict] = None,
) -> DisponibilidadeSlotResponse:
    data_hora = _parse_datetime(disponibilidade["data_hora"])
    ocupado = agendamento_ativo is not None
    return DisponibilidadeSlotResponse(
        id=disponibilidade["id"],
        comprador_id=disponibilidade["comprador_id"],
        data_hora=data_hora,
        disponivel=(not ocupado) and data_hora > datetime.now(),
        ocupado=ocupado,
        nome_vendedor=agendamento_ativo["nome_vendedor"] if agendamento_ativo else None,
        status_agendamento=agendamento_ativo["status"] if agendamento_ativo else None,
        criado_em=_parse_datetime(disponibilidade["criado_em"]),
    )


def _storage_exception(exc: StorageError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Falha ao acessar armazenamento: {exc}",
    )


def _next_user_id(usuarios: list[dict]) -> int:
    return max((usuario.get("id", 0) for usuario in usuarios), default=0) + 1


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _normalizar_telefone(telefone: Optional[str]) -> str:
    if not telefone:
        return ""
    return "".join(char for char in telefone if char.isdigit())


def _montar_usuario(payload: dict, user_id: int) -> dict:
    return {
        "id": user_id,
        "nome": payload["nome"],
        "email": _normalizar_email(payload["email"]),
        "telefone": payload.get("telefone"),
        "foto_url": payload.get("foto_url"),
        "mensagem_whatsapp": payload.get("mensagem_whatsapp"),
        "senha_hash": criar_hash_senha(payload["senha"]),
        "reset_codigo_hash": None,
        "reset_codigo_expira_em": None,
        "tipo": payload["tipo"],
        "ativo": payload.get("ativo", True),
        "criado_em": datetime.utcnow().isoformat(timespec="seconds"),
    }


def _limpar_reset_senha(usuario: dict) -> None:
    usuario["reset_codigo_hash"] = None
    usuario["reset_codigo_expira_em"] = None


def _gerar_codigo_reset() -> str:
    return f"{secrets.randbelow(1000000):06d}"


def _garantir_usuarios_iniciais() -> None:
    """Garante apenas o usuario desenvolvedor inicial."""
    try:
        usuarios = storage.list_users()
        existentes_por_email = {
            _normalizar_email(usuario["email"]): usuario
            for usuario in usuarios
        }

        alterado = False
        next_id = _next_user_id(usuarios)

        dev_email = _normalizar_email(DEFAULT_DEVELOPER["email"])
        if dev_email not in existentes_por_email:
            usuarios.append(_montar_usuario(DEFAULT_DEVELOPER, next_id))
            alterado = True

        if alterado:
            storage.save_users(usuarios, "Atualiza usuario desenvolvedor inicial")
    except StorageError as exc:
        print(f"Erro ao criar dados iniciais: {exc}")


def _pode_criar_tipo(usuario_logado: dict, tipo_novo_usuario: str) -> bool:
    tipo_atual = usuario_logado.get("tipo")
    if tipo_atual == ROLE_DEVELOPER:
        return True
    if tipo_atual == ROLE_ADMIN and tipo_novo_usuario == ROLE_BUYER:
        return True
    return False


def _pode_gerenciar_usuario(usuario_logado: dict, usuario_alvo: dict) -> bool:
    if usuario_logado.get("tipo") == ROLE_DEVELOPER:
        return True
    return (
        usuario_logado.get("tipo") == ROLE_ADMIN
        and usuario_alvo.get("tipo") == ROLE_BUYER
    )


def _contar_desenvolvedores_ativos(usuarios: list[dict]) -> int:
    return sum(
        1
        for usuario in usuarios
        if usuario.get("tipo") == ROLE_DEVELOPER and usuario.get("ativo", True)
    )


def _usuario_possui_vinculos_operacionais(user_id: int) -> bool:
    if any(item.get("comprador_id") == user_id for item in storage.list_agendamentos()):
        return True
    if any(item.get("comprador_id") == user_id for item in storage.list_disponibilidades()):
        return True
    return False


def _validar_alteracao_desenvolvedor(
    usuarios: list[dict],
    usuario_alvo: dict,
    *,
    novo_tipo: Optional[str] = None,
    novo_ativo: Optional[bool] = None,
    excluindo: bool = False,
) -> None:
    era_desenvolvedor_ativo = (
        usuario_alvo.get("tipo") == ROLE_DEVELOPER and usuario_alvo.get("ativo", True)
    )
    continuara_desenvolvedor_ativo = (
        not excluindo
        and (novo_tipo or usuario_alvo.get("tipo")) == ROLE_DEVELOPER
        and (
            usuario_alvo.get("ativo", True)
            if novo_ativo is None
            else novo_ativo
        )
    )

    if era_desenvolvedor_ativo and not continuara_desenvolvedor_ativo:
        if _contar_desenvolvedores_ativos(usuarios) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nao e possivel remover ou desativar o ultimo desenvolvedor ativo",
            )


def _buscar_nome_comprador(comprador_id: int) -> str:
    comprador = storage.find_user_by_id(comprador_id)
    if not comprador:
        return "Comprador nao encontrado"
    return comprador["nome"]


def _validar_data_hora_disponibilidade(data_hora: datetime) -> None:
    if data_hora <= datetime.now():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O horario livre deve estar no futuro",
        )

    if data_hora.weekday() >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Os horarios livres devem ser cadastrados em dias uteis",
        )

    if data_hora.hour < HORARIO_INICIO or data_hora.hour >= HORARIO_FIM:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Os horarios livres devem ser entre {HORARIO_INICIO}:00 e {HORARIO_FIM}:00",
        )

    if data_hora.minute % INTERVALO_MINUTOS != 0 or data_hora.second != 0 or data_hora.microsecond != 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Os horarios livres devem seguir intervalos de {INTERVALO_MINUTOS} minutos",
        )


@app.get("/", response_model=StatusResponse)
async def root() -> StatusResponse:
    return StatusResponse(
        status="online",
        mensagem="Sistema de Agendamento - API funcionando corretamente",
    )


@app.get("/health", response_model=StatusResponse)
async def health_check() -> StatusResponse:
    return StatusResponse(
        status="healthy",
        mensagem="Servidor esta funcionando normalmente",
    )


@app.post("/auth/login", response_model=Token)
async def login(request: Request) -> Token:
    """Autentica um usuario ativo e retorna um token JWT."""
    content_type = request.headers.get("content-type", "")
    remember_me = False
    if "application/json" in content_type:
        payload = await request.json()
        raw_email = payload.get("email")
        raw_senha = payload.get("senha")
        remember_me = bool(payload.get("remember_me"))
    else:
        form = await request.form()
        raw_email = form.get("email") or form.get("username")
        raw_senha = form.get("senha") or form.get("password")
        remember_raw = form.get("remember_me")
        remember_me = str(remember_raw).lower() in {"true", "1", "on", "yes"}

    try:
        credentials = UsuarioLogin.model_validate({"email": raw_email, "senha": raw_senha})
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(),
        ) from exc

    try:
        usuario = storage.find_user_by_email(credentials.email)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if not usuario or not verificar_senha(credentials.senha, usuario["senha_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not usuario.get("ativo", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo. Entre em contato com o administrador.",
        )

    expires_delta = timedelta(hours=24) if remember_me else None
    token = criar_token_acesso(
        data={"sub": usuario["email"], "uid": usuario["id"], "tipo": usuario["tipo"]},
        expires_delta=expires_delta,
    )
    return Token(
        access_token=token,
        token_type="bearer",
        usuario=_serialize_usuario(usuario),
    )


@app.post("/auth/esqueci-senha", response_model=StatusResponse)
async def esqueci_minha_senha(payload: PasswordResetRequest) -> StatusResponse:
    try:
        usuarios = storage.list_users()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    email_normalizado = _normalizar_email(str(payload.email))

    usuario = next(
        (item for item in usuarios if _normalizar_email(item.get("email", "")) == email_normalizado),
        None,
    )

    if not usuario or not usuario.get("ativo", True):
        logger.warning(
            "Recuperacao de senha ignorada para email desconhecido ou inativo: %s",
            email_normalizado,
        )
        return StatusResponse(
            status="ok",
            mensagem="Se o email estiver cadastrado, enviaremos um codigo de recuperacao.",
        )

    codigo = _gerar_codigo_reset()
    usuario["reset_codigo_hash"] = criar_hash_senha(codigo)
    usuario["reset_codigo_expira_em"] = (
        datetime.utcnow() + timedelta(minutes=PASSWORD_RESET_EXPIRE_MINUTES)
    ).isoformat(timespec="seconds")

    try:
        storage.save_users(usuarios, f"Gera codigo de reset para usuario #{usuario['id']}")
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    try:
        logger.info(
            "Enviando email de recuperacao para usuario_id=%s email=%s remetente=%s",
            usuario["id"],
            usuario["email"],
            MAIL_FROM_EMAIL,
        )
        brevo_response = send_password_reset_email(usuario["email"], usuario["nome"], codigo)
        logger.info(
            "Brevo aceitou email de recuperacao para usuario_id=%s email=%s message_id=%s",
            usuario["id"],
            usuario["email"],
            brevo_response.get("messageId", "desconhecido"),
        )
    except EmailServiceError as exc:
        _limpar_reset_senha(usuario)
        try:
            storage.save_users(usuarios, f"Limpa codigo de reset usuario #{usuario['id']}")
        except StorageError:
            pass
        logger.exception(
            "Falha ao enviar email de recuperacao para usuario_id=%s email=%s",
            usuario["id"],
            usuario["email"],
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Falha ao enviar email de recuperacao: {exc}",
        ) from exc

    return StatusResponse(
        status="ok",
        mensagem="Se o email estiver cadastrado, enviaremos um codigo de recuperacao.",
    )


@app.post("/auth/redefinir-senha", response_model=StatusResponse)
async def redefinir_senha(payload: PasswordResetConfirm) -> StatusResponse:
    try:
        usuarios = storage.list_users()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    usuario = next(
        (item for item in usuarios if _normalizar_email(item.get("email", "")) == _normalizar_email(str(payload.email))),
        None,
    )

    if not usuario or not usuario.get("ativo", True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido ou expirado",
        )

    codigo_hash = usuario.get("reset_codigo_hash")
    expira_em = usuario.get("reset_codigo_expira_em")
    if not codigo_hash or not expira_em:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido ou expirado",
        )

    try:
        expiracao = _parse_datetime(expira_em)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido ou expirado",
        ) from exc

    if expiracao <= datetime.utcnow() or not verificar_senha(payload.codigo, codigo_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido ou expirado",
        )

    usuario["senha_hash"] = criar_hash_senha(payload.nova_senha)
    _limpar_reset_senha(usuario)

    try:
        storage.save_users(usuarios, f"Redefine senha do usuario #{usuario['id']}")
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return StatusResponse(
        status="ok",
        mensagem="Senha redefinida com sucesso. Voce ja pode entrar com a nova senha.",
    )


@app.get("/auth/me", response_model=UsuarioResponse)
async def get_me(usuario: dict = Depends(get_usuario_atual)) -> UsuarioResponse:
    return _serialize_usuario(usuario)


@app.patch("/usuarios/me", response_model=UsuarioResponse)
async def atualizar_meu_perfil(
    dados: UsuarioProfileUpdate,
    usuario_atual: dict = Depends(get_usuario_atual),
) -> UsuarioResponse:
    try:
        usuarios = storage.list_users()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    usuario = next((item for item in usuarios if item["id"] == usuario_atual["id"]), None)
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario nao encontrado",
        )

    if dados.email is not None:
        novo_email = _normalizar_email(str(dados.email))
        if any(
            item["id"] != usuario["id"] and _normalizar_email(item["email"]) == novo_email
            for item in usuarios
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um usuario com este email",
            )
        usuario["email"] = novo_email

    if dados.nome is not None:
        usuario["nome"] = dados.nome.strip()

    if dados.telefone is not None:
        usuario["telefone"] = dados.telefone

    if dados.foto_url is not None:
        usuario["foto_url"] = dados.foto_url

    if "mensagem_whatsapp" in dados.model_fields_set:
        usuario["mensagem_whatsapp"] = dados.mensagem_whatsapp

    if dados.nova_senha is not None:
        if not dados.senha_atual:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe a senha atual para definir uma nova senha",
            )
        if not verificar_senha(dados.senha_atual, usuario["senha_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Senha atual incorreta",
            )
        usuario["senha_hash"] = criar_hash_senha(dados.nova_senha)
        _limpar_reset_senha(usuario)

    try:
        storage.save_users(usuarios, f"Atualiza perfil usuario #{usuario['id']}")
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return _serialize_usuario(usuario)


@app.get("/usuarios", response_model=list[UsuarioResponse])
async def listar_usuarios(
    usuario_atual: dict = Depends(get_admin_ou_desenvolvedor_atual),
) -> list[UsuarioResponse]:
    try:
        usuarios = storage.list_users()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if usuario_atual["tipo"] == ROLE_ADMIN:
        usuarios = [usuario for usuario in usuarios if usuario.get("tipo") == ROLE_BUYER]

    usuarios.sort(key=lambda item: (item.get("tipo", ""), item.get("nome", "").lower()))
    return [_serialize_usuario(usuario) for usuario in usuarios]


@app.post("/usuarios", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
async def criar_usuario(
    novo_usuario: UsuarioCreate,
    usuario_atual: dict = Depends(get_admin_ou_desenvolvedor_atual),
) -> UsuarioResponse:
    if not _pode_criar_tipo(usuario_atual, novo_usuario.tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este perfil nao pode criar usuarios desse tipo",
        )

    try:
        usuarios = storage.list_users()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    email = _normalizar_email(str(novo_usuario.email))
    if any(_normalizar_email(usuario["email"]) == email for usuario in usuarios):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ja existe um usuario com este email",
        )

    usuario_dict = _montar_usuario(
        {
            "nome": novo_usuario.nome,
            "email": email,
            "telefone": novo_usuario.telefone,
            "foto_url": novo_usuario.foto_url,
            "mensagem_whatsapp": novo_usuario.mensagem_whatsapp,
            "senha": novo_usuario.senha,
            "tipo": novo_usuario.tipo,
            "ativo": novo_usuario.ativo,
        },
        _next_user_id(usuarios),
    )
    usuarios.append(usuario_dict)

    commit_message = f"Cria usuario {usuario_dict['tipo']} #{usuario_dict['id']}"
    try:
        storage.save_users(usuarios, commit_message)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return _serialize_usuario(usuario_dict)


@app.patch("/usuarios/{usuario_id}", response_model=UsuarioResponse)
async def atualizar_usuario(
    usuario_id: int,
    dados: UsuarioUpdate,
    usuario_atual: dict = Depends(get_admin_ou_desenvolvedor_atual),
) -> UsuarioResponse:
    try:
        usuarios = storage.list_users()
        usuario = next((item for item in usuarios if item["id"] == usuario_id), None)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario nao encontrado",
        )

    if usuario["id"] == usuario_atual["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Use a tela de perfil para alterar sua propria conta",
        )

    if not _pode_gerenciar_usuario(usuario_atual, usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voce nao pode editar este usuario",
        )

    novo_tipo = dados.tipo if dados.tipo is not None else usuario.get("tipo")
    if dados.tipo is not None and not _pode_criar_tipo(usuario_atual, dados.tipo):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este perfil nao pode definir esse tipo de usuario",
        )

    try:
        possui_vinculos_operacionais = _usuario_possui_vinculos_operacionais(usuario_id)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if (
        dados.tipo is not None
        and dados.tipo != usuario.get("tipo")
        and possui_vinculos_operacionais
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nao e possivel alterar o perfil de um usuario com agendamentos ou disponibilidades vinculadas",
        )

    _validar_alteracao_desenvolvedor(
        usuarios,
        usuario,
        novo_tipo=novo_tipo,
        novo_ativo=dados.ativo,
    )

    if dados.email is not None:
        novo_email = _normalizar_email(str(dados.email))
        if any(
            item["id"] != usuario["id"] and _normalizar_email(item["email"]) == novo_email
            for item in usuarios
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ja existe um usuario com este email",
            )
        usuario["email"] = novo_email

    if dados.nome is not None:
        usuario["nome"] = dados.nome

    if dados.tipo is not None:
        usuario["tipo"] = dados.tipo

    if dados.ativo is not None:
        usuario["ativo"] = dados.ativo

    if dados.senha is not None:
        usuario["senha_hash"] = criar_hash_senha(dados.senha)
        _limpar_reset_senha(usuario)

    try:
        storage.save_users(usuarios, f"Atualiza usuario #{usuario['id']}")
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return _serialize_usuario(usuario)


@app.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluir_usuario(
    usuario_id: int,
    usuario_atual: dict = Depends(get_admin_ou_desenvolvedor_atual),
) -> Response:
    try:
        usuarios = storage.list_users()
        usuario = next((item for item in usuarios if item["id"] == usuario_id), None)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario nao encontrado",
        )

    if usuario["id"] == usuario_atual["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Nao e permitido excluir a propria conta por esta tela",
        )

    if not _pode_gerenciar_usuario(usuario_atual, usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Voce nao pode excluir este usuario",
        )

    _validar_alteracao_desenvolvedor(usuarios, usuario, excluindo=True)

    try:
        possui_vinculos_operacionais = _usuario_possui_vinculos_operacionais(usuario_id)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if possui_vinculos_operacionais:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Nao e possivel excluir um usuario com agendamentos ou disponibilidades vinculadas",
        )

    usuarios = [item for item in usuarios if item["id"] != usuario_id]

    try:
        storage.save_users(usuarios, f"Exclui usuario #{usuario_id}")
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/compradores", response_model=list[CompradorListResponse])
async def listar_compradores(ativo: bool = True) -> list[CompradorListResponse]:
    try:
        compradores = [
            CompradorListResponse(
                id=usuario["id"],
                nome=usuario["nome"],
                email=usuario["email"],
                foto_url=usuario.get("foto_url"),
            )
            for usuario in storage.list_users()
            if usuario.get("tipo") == ROLE_BUYER and usuario.get("ativo", True) == ativo
        ]
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return compradores


@app.post("/agendamentos", response_model=AgendamentoResponse, status_code=status.HTTP_201_CREATED)
async def criar_agendamento(agendamento: AgendamentoCreate) -> AgendamentoResponse:
    try:
        comprador = storage.find_user_by_id(agendamento.comprador_id)
        if (
            not comprador
            or comprador.get("tipo") != ROLE_BUYER
            or not comprador.get("ativo", True)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comprador nao encontrado ou inativo",
            )

        if agendamento.data_hora <= datetime.now():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A data e hora do agendamento deve ser futura",
            )

        disponibilidades = storage.list_disponibilidades()
        horario_liberado = next(
            (
                item
                for item in disponibilidades
                if item["comprador_id"] == agendamento.comprador_id
                and _parse_datetime(item["data_hora"]) == agendamento.data_hora
            ),
            None,
        )
        if not horario_liberado:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este horario nao foi liberado pelo comprador",
            )

        agendamentos = storage.list_agendamentos()
        for item in agendamentos:
            if (
                item["comprador_id"] == agendamento.comprador_id
                and _parse_datetime(item["data_hora"]) == agendamento.data_hora
                and item["status"] in ["pendente", "confirmado"]
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Este horario ja esta agendado para este comprador",
                )

        agora = datetime.utcnow().isoformat(timespec="seconds")
        novo_agendamento = {
            "id": storage.next_agendamento_id(),
            "comprador_id": agendamento.comprador_id,
            "vendedor_id": None,
            "nome_vendedor": agendamento.nome_vendedor,
            "empresa_vendedor": agendamento.empresa_vendedor,
            "telefone_vendedor": agendamento.telefone_vendedor,
            "email_vendedor": str(agendamento.email_vendedor),
            "data_hora": agendamento.data_hora.isoformat(timespec="seconds"),
            "status": "pendente",
            "observacoes": agendamento.observacoes,
            "comentario_comprador": None,
            "motivo_vendedor": None,
            "criado_em": agora,
            "atualizado_em": agora,
        }

        agendamentos.append(novo_agendamento)
        storage.save_agendamentos(agendamentos, f"Cria agendamento #{novo_agendamento['id']}")
        return _serialize_agendamento(novo_agendamento)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


@app.get("/minhas-disponibilidades", response_model=list[DisponibilidadeSlotResponse])
async def listar_minhas_disponibilidades(
    mes: Optional[str] = Query(None, description="Mes no formato YYYY-MM"),
    comprador: dict = Depends(get_comprador_atual),
) -> list[DisponibilidadeSlotResponse]:
    try:
        disponibilidades = [
            item
            for item in storage.list_disponibilidades()
            if item["comprador_id"] == comprador["id"]
        ]
        agendamentos_ativos = _mapear_agendamentos_ativos_por_data(
            storage.list_agendamentos(),
            comprador["id"],
        )
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if mes:
        try:
            ano, mes_numero = (int(parte) for parte in mes.split("-", 1))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de mes invalido. Use YYYY-MM",
            ) from exc

        disponibilidades = [
            item
            for item in disponibilidades
            if _parse_datetime(item["data_hora"]).year == ano
            and _parse_datetime(item["data_hora"]).month == mes_numero
        ]

    disponibilidades.sort(key=lambda item: _parse_datetime(item["data_hora"]))
    return [
        _serialize_disponibilidade(item, agendamentos_ativos.get(_parse_datetime(item["data_hora"])))
        for item in disponibilidades
    ]


@app.post(
    "/minhas-disponibilidades",
    response_model=DisponibilidadeSlotResponse,
    status_code=status.HTTP_201_CREATED,
)
async def criar_minha_disponibilidade(
    dados: DisponibilidadeCreate,
    comprador: dict = Depends(get_comprador_atual),
) -> DisponibilidadeSlotResponse:
    _validar_data_hora_disponibilidade(dados.data_hora)

    try:
        disponibilidades = storage.list_disponibilidades()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if any(
        item["comprador_id"] == comprador["id"] and _parse_datetime(item["data_hora"]) == dados.data_hora
        for item in disponibilidades
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este horario livre ja foi cadastrado",
        )

    nova_disponibilidade = {
        "id": storage.next_disponibilidade_id(),
        "comprador_id": comprador["id"],
        "data_hora": dados.data_hora.isoformat(timespec="seconds"),
        "criado_em": datetime.utcnow().isoformat(timespec="seconds"),
    }
    disponibilidades.append(nova_disponibilidade)

    try:
        storage.save_disponibilidades(
            disponibilidades,
            f"Cria disponibilidade #{nova_disponibilidade['id']}",
        )
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    return _serialize_disponibilidade(nova_disponibilidade)


@app.delete("/minhas-disponibilidades/{disponibilidade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def excluir_minha_disponibilidade(
    disponibilidade_id: int,
    comprador: dict = Depends(get_comprador_atual),
) -> Response:
    try:
        disponibilidades = storage.list_disponibilidades()
        disponibilidade = next(
            (
                item
                for item in disponibilidades
                if item["id"] == disponibilidade_id and item["comprador_id"] == comprador["id"]
            ),
            None,
        )
        if not disponibilidade:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Horario livre nao encontrado",
            )

        data_hora = _parse_datetime(disponibilidade["data_hora"])
        possui_agendamento_ativo = any(
            item["comprador_id"] == comprador["id"]
            and _parse_datetime(item["data_hora"]) == data_hora
            and item["status"] in ["pendente", "confirmado"]
            for item in storage.list_agendamentos()
        )
        if possui_agendamento_ativo:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Nao e possivel remover um horario que ja possui visita pendente ou confirmada",
            )

        disponibilidades = [item for item in disponibilidades if item["id"] != disponibilidade_id]
        storage.save_disponibilidades(
            disponibilidades,
            f"Remove disponibilidade #{disponibilidade_id}",
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


@app.get("/gestao/agendamentos", response_model=list[AgendamentoDetalhadoResponse])
async def listar_agendamentos_gerenciais(
    status: Optional[str] = Query(None),
    comprador_id: Optional[int] = Query(None),
    usuario_atual: dict = Depends(get_admin_ou_desenvolvedor_atual),
) -> list[AgendamentoDetalhadoResponse]:
    try:
        agendamentos = storage.list_agendamentos()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if status:
        agendamentos = [item for item in agendamentos if item["status"] == status]

    if comprador_id is not None:
        agendamentos = [item for item in agendamentos if item["comprador_id"] == comprador_id]

    agendamentos.sort(key=lambda item: _parse_datetime(item["data_hora"]), reverse=True)
    return [
        _serialize_agendamento_detalhado(item, _buscar_nome_comprador(item["comprador_id"]))
        for item in agendamentos
    ]


@app.get("/minhas-visitas", response_model=list[VendedorVisitaResponse])
async def listar_visitas_do_vendedor(
    telefone: str = Query(..., description="Telefone do vendedor para busca das visitas"),
) -> list[VendedorVisitaResponse]:
    telefone_normalizado = _normalizar_telefone(telefone)
    if len(telefone_normalizado) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe um telefone valido com DDD",
        )

    try:
        agendamentos = storage.list_agendamentos()
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    visitas = [
        item
        for item in agendamentos
        if _normalizar_telefone(item.get("telefone_vendedor")) == telefone_normalizado
    ]
    visitas.sort(key=lambda item: _parse_datetime(item["data_hora"]), reverse=True)

    return [
        VendedorVisitaResponse(
            id=item["id"],
            nome_vendedor=item["nome_vendedor"],
            empresa_vendedor=item.get("empresa_vendedor"),
            telefone_vendedor=item.get("telefone_vendedor"),
            email_vendedor=item["email_vendedor"],
            data_hora=_parse_datetime(item["data_hora"]),
            status=item["status"],
            observacoes=item.get("observacoes"),
            motivo_vendedor=item.get("motivo_vendedor"),
            nome_comprador=_buscar_nome_comprador(item["comprador_id"]),
        )
        for item in visitas
    ]


@app.post("/minhas-visitas/{agendamento_id}/desistir", response_model=AgendamentoResponse)
async def desistir_visita_do_vendedor(
    agendamento_id: int,
    dados: VisitaDesistenciaRequest,
) -> AgendamentoResponse:
    telefone_normalizado = _normalizar_telefone(dados.telefone)
    if len(telefone_normalizado) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe um telefone valido com DDD",
        )

    try:
        agendamentos = storage.list_agendamentos()
        agendamento = next(
            (
                item
                for item in agendamentos
                if item["id"] == agendamento_id
                and _normalizar_telefone(item.get("telefone_vendedor")) == telefone_normalizado
            ),
            None,
        )
        if not agendamento:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Visita nao encontrada para este telefone",
            )

        if agendamento["status"] not in ["pendente", "confirmado"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A visita nao pode mais ser marcada como desistida",
            )

        agendamento["status"] = "desistiu"
        agendamento["motivo_vendedor"] = dados.motivo
        agendamento["atualizado_em"] = datetime.utcnow().isoformat(timespec="seconds")
        storage.save_agendamentos(agendamentos, f"Vendedor desiste da visita #{agendamento_id}")
        return _serialize_agendamento(agendamento)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


@app.get("/agendamentos", response_model=list[AgendamentoDetalhadoResponse])
async def listar_agendamentos(
    status: Optional[str] = Query(None),
    data_inicio: Optional[str] = Query(None),
    data_fim: Optional[str] = Query(None),
    comprador: dict = Depends(get_comprador_atual),
) -> list[AgendamentoDetalhadoResponse]:
    try:
        agendamentos = [
            item
            for item in storage.list_agendamentos()
            if item["comprador_id"] == comprador["id"]
        ]
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if status:
        agendamentos = [item for item in agendamentos if item["status"] == status]

    if data_inicio:
        try:
            dt_inicio = datetime.strptime(data_inicio, "%Y-%m-%d")
            agendamentos = [
                item for item in agendamentos if _parse_datetime(item["data_hora"]) >= dt_inicio
            ]
        except ValueError:
            pass

    if data_fim:
        try:
            dt_fim = datetime.strptime(data_fim, "%Y-%m-%d") + timedelta(days=1)
            agendamentos = [
                item for item in agendamentos if _parse_datetime(item["data_hora"]) < dt_fim
            ]
        except ValueError:
            pass

    agendamentos.sort(key=lambda item: _parse_datetime(item["data_hora"]))
    return [_serialize_agendamento_detalhado(item, comprador["nome"]) for item in agendamentos]


@app.get("/agendamentos/{agendamento_id}", response_model=AgendamentoDetalhadoResponse)
async def obter_agendamento(
    agendamento_id: int,
    comprador: dict = Depends(get_comprador_atual),
) -> AgendamentoDetalhadoResponse:
    try:
        agendamento = storage.find_agendamento_by_id(agendamento_id)
    except StorageError as exc:
        raise _storage_exception(exc) from exc

    if not agendamento or agendamento["comprador_id"] != comprador["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento nao encontrado",
        )

    return _serialize_agendamento_detalhado(agendamento, comprador["nome"])


@app.patch("/agendamentos/{agendamento_id}", response_model=AgendamentoResponse)
async def atualizar_agendamento(
    agendamento_id: int,
    dados: AgendamentoUpdate,
    comprador: dict = Depends(get_comprador_atual),
) -> AgendamentoResponse:
    try:
        agendamentos = storage.list_agendamentos()
        agendamento = next(
            (
                item
                for item in agendamentos
                if item["id"] == agendamento_id and item["comprador_id"] == comprador["id"]
            ),
            None,
        )
        if not agendamento:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento nao encontrado",
            )

        if dados.status:
            status_atual = agendamento["status"]
            novo_status = dados.status
            transicoes_validas = {
                "pendente": ["confirmado", "cancelado"],
                "confirmado": ["concluido", "cancelado", "nao_compareceu"],
                "concluido": [],
                "cancelado": [],
                "desistiu": [],
                "nao_compareceu": [],
            }
            if novo_status not in transicoes_validas.get(status_atual, []):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Nao e possivel alterar status de '{status_atual}' para '{novo_status}'",
                )
            agendamento["status"] = novo_status

        if dados.observacoes is not None:
            agendamento["observacoes"] = dados.observacoes

        if "comentario_comprador" in dados.model_fields_set:
            agendamento["comentario_comprador"] = dados.comentario_comprador

        if "motivo_vendedor" in dados.model_fields_set:
            agendamento["motivo_vendedor"] = dados.motivo_vendedor

        agendamento["atualizado_em"] = datetime.utcnow().isoformat(timespec="seconds")
        storage.save_agendamentos(agendamentos, f"Atualiza agendamento #{agendamento_id}")
        return _serialize_agendamento(agendamento)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


@app.delete("/agendamentos/{agendamento_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancelar_agendamento(
    agendamento_id: int,
    comprador: dict = Depends(get_comprador_atual),
) -> Response:
    try:
        agendamentos = storage.list_agendamentos()
        agendamento = next(
            (
                item
                for item in agendamentos
                if item["id"] == agendamento_id and item["comprador_id"] == comprador["id"]
            ),
            None,
        )
        if not agendamento:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento nao encontrado",
            )

        if agendamento["status"] in ["concluido", "cancelado"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Este agendamento nao pode ser cancelado",
            )

        agendamento["status"] = "cancelado"
        agendamento["atualizado_em"] = datetime.utcnow().isoformat(timespec="seconds")
        storage.save_agendamentos(agendamentos, f"Cancela agendamento #{agendamento_id}")
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


@app.get("/disponibilidade/{comprador_id}", response_model=DisponibilidadeResponse)
async def verificar_disponibilidade(
    comprador_id: int,
    data: str = Query(..., description="Data no formato YYYY-MM-DD"),
) -> DisponibilidadeResponse:
    try:
        comprador = storage.find_user_by_id(comprador_id)
        if (
            not comprador
            or comprador.get("tipo") != ROLE_BUYER
            or not comprador.get("ativo", True)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Comprador nao encontrado",
            )

        try:
            data_obj = datetime.strptime(data, "%Y-%m-%d").date()
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Formato de data invalido. Use YYYY-MM-DD",
            ) from exc

        if data_obj < date.today():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A data deve ser hoje ou uma data futura",
            )

        inicio_dia = datetime.combine(data_obj, datetime.min.time())
        fim_dia = inicio_dia + timedelta(days=1)
        agendamentos = [
            item
            for item in storage.list_agendamentos()
            if item["comprador_id"] == comprador_id
            and item["status"] in ["pendente", "confirmado"]
            and inicio_dia <= _parse_datetime(item["data_hora"]) < fim_dia
        ]
        disponibilidades = [
            item
            for item in storage.list_disponibilidades()
            if item["comprador_id"] == comprador_id
            and inicio_dia <= _parse_datetime(item["data_hora"]) < fim_dia
        ]

        horarios_ocupados = {_parse_datetime(item["data_hora"]) for item in agendamentos}
        horarios = []
        for disponibilidade in sorted(disponibilidades, key=lambda item: _parse_datetime(item["data_hora"])):
            data_hora = _parse_datetime(disponibilidade["data_hora"])
            disponivel = data_hora not in horarios_ocupados and data_hora > datetime.now()
            horarios.append(HorarioDisponivel(data_hora=data_hora, disponivel=disponivel))

        return DisponibilidadeResponse(comprador_id=comprador_id, data=data, horarios=horarios)
    except StorageError as exc:
        raise _storage_exception(exc) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
