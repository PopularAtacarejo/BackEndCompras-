"""
Persistencia em JSON com sincronizacao opcional no GitHub.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from urllib import error, request

from config import (
    AGENDAMENTOS_FILE_PATH,
    AUTH_FILE_PATH,
    GITHUB_API_URL,
    GITHUB_REPO_BRANCH,
    GITHUB_REPO_NAME,
    GITHUB_REPO_OWNER,
    GITHUB_TOKEN,
    REPO_ROOT,
)


class StorageError(RuntimeError):
    """Erro de persistencia."""


class JsonStorage:
    def __init__(self) -> None:
        self.github_enabled = bool(
            GITHUB_TOKEN and GITHUB_REPO_OWNER and GITHUB_REPO_NAME
        )
        self.auth_local_path = self._resolve_local_path(AUTH_FILE_PATH)
        self.agendamentos_local_path = self._resolve_local_path(AGENDAMENTOS_FILE_PATH)
        self.auth_remote_path = self._normalize_remote_path(AUTH_FILE_PATH)
        self.agendamentos_remote_path = self._normalize_remote_path(AGENDAMENTOS_FILE_PATH)
        self._lock = Lock()

    def initialize_files(self) -> None:
        self._initialize_file(
            self.auth_local_path,
            self.auth_remote_path,
            {"usuarios": []},
            "Inicializa auth.json",
        )
        self._initialize_file(
            self.agendamentos_local_path,
            self.agendamentos_remote_path,
            {"agendamentos": [], "disponibilidades": []},
            "Inicializa agendamentos.json",
        )

    def list_users(self) -> list[dict[str, Any]]:
        payload = self._normalize_auth_payload(self._read_payload(
            self.auth_local_path,
            self.auth_remote_path,
            {"usuarios": []},
        ))
        usuarios = payload.get("usuarios", [])
        return usuarios if isinstance(usuarios, list) else []

    def save_users(
        self,
        users: list[dict[str, Any]],
        commit_message: str = "Atualiza auth.json",
    ) -> None:
        self._write_payload(
            self.auth_local_path,
            self.auth_remote_path,
            {"usuarios": users},
            commit_message,
        )

    def list_agendamentos(self) -> list[dict[str, Any]]:
        payload = self._read_agendamentos_payload()
        agendamentos = payload.get("agendamentos", [])
        return agendamentos if isinstance(agendamentos, list) else []

    def save_agendamentos(
        self,
        agendamentos: list[dict[str, Any]],
        commit_message: str = "Atualiza agendamentos.json",
    ) -> None:
        payload = self._read_agendamentos_payload()
        payload["agendamentos"] = agendamentos
        payload.setdefault("disponibilidades", [])
        self._write_agendamentos_payload(payload, commit_message)

    def list_disponibilidades(self) -> list[dict[str, Any]]:
        payload = self._read_agendamentos_payload()
        disponibilidades = payload.get("disponibilidades", [])
        return disponibilidades if isinstance(disponibilidades, list) else []

    def save_disponibilidades(
        self,
        disponibilidades: list[dict[str, Any]],
        commit_message: str = "Atualiza disponibilidades",
    ) -> None:
        payload = self._read_agendamentos_payload()
        payload.setdefault("agendamentos", [])
        payload["disponibilidades"] = disponibilidades
        self._write_agendamentos_payload(payload, commit_message)

    def find_user_by_email(self, email: str) -> Optional[dict[str, Any]]:
        email_normalized = email.strip().lower()
        for user in self.list_users():
            if user.get("email", "").strip().lower() == email_normalized:
                return user
        return None

    def find_user_by_id(self, user_id: int) -> Optional[dict[str, Any]]:
        for user in self.list_users():
            if user.get("id") == user_id:
                return user
        return None

    def next_user_id(self) -> int:
        users = self.list_users()
        if not users:
            return 1
        return max(user.get("id", 0) for user in users) + 1

    def find_agendamento_by_id(self, agendamento_id: int) -> Optional[dict[str, Any]]:
        for agendamento in self.list_agendamentos():
            if agendamento.get("id") == agendamento_id:
                return agendamento
        return None

    def next_agendamento_id(self) -> int:
        agendamentos = self.list_agendamentos()
        if not agendamentos:
            return 1
        return max(agendamento.get("id", 0) for agendamento in agendamentos) + 1

    def next_disponibilidade_id(self) -> int:
        disponibilidades = self.list_disponibilidades()
        if not disponibilidades:
            return 1
        return max(disponibilidade.get("id", 0) for disponibilidade in disponibilidades) + 1

    def _read_agendamentos_payload(self) -> dict[str, Any]:
        payload = self._normalize_agendamentos_payload(self._read_payload(
            self.agendamentos_local_path,
            self.agendamentos_remote_path,
            {"agendamentos": [], "disponibilidades": []},
        ))
        return payload

    def _write_agendamentos_payload(
        self,
        payload: dict[str, Any],
        commit_message: str,
    ) -> None:
        payload.setdefault("agendamentos", [])
        payload.setdefault("disponibilidades", [])
        self._write_payload(
            self.agendamentos_local_path,
            self.agendamentos_remote_path,
            payload,
            commit_message,
        )

    def _initialize_file(
        self,
        local_path: Path,
        remote_path: str,
        default_payload: dict[str, Any],
        commit_message: str,
    ) -> None:
        with self._lock:
            if self.github_enabled:
                remote_payload = self._download_from_github(remote_path)
                if remote_payload is None:
                    payload_to_publish = (
                        self._read_local_file(local_path, default_payload)
                        if local_path.exists()
                        else default_payload
                    )
                    self._upload_to_github(remote_path, payload_to_publish, commit_message)
                    remote_payload = payload_to_publish
                self._write_local_file(local_path, remote_payload)
                return

            if not local_path.exists():
                self._write_local_file(local_path, default_payload)

    def _read_payload(
        self,
        local_path: Path,
        remote_path: str,
        default_payload: dict[str, Any],
    ) -> Any:
        with self._lock:
            if self.github_enabled:
                remote_payload = self._download_from_github(remote_path)
                if remote_payload is not None:
                    self._write_local_file(local_path, remote_payload)
                    return remote_payload

            if not local_path.exists():
                self._write_local_file(local_path, default_payload)
                return default_payload

            return self._read_local_file(local_path, default_payload)

    def _write_payload(
        self,
        local_path: Path,
        remote_path: str,
        payload: dict[str, Any],
        commit_message: str,
    ) -> None:
        with self._lock:
            if self.github_enabled:
                self._upload_to_github(remote_path, payload, commit_message)
            self._write_local_file(local_path, payload)

    def _normalize_auth_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            usuarios = payload.get("usuarios", [])
            return {
                "usuarios": usuarios if isinstance(usuarios, list) else [],
            }

        if isinstance(payload, list):
            return {"usuarios": payload}

        return {"usuarios": []}

    def _normalize_agendamentos_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            agendamentos = payload.get("agendamentos", [])
            disponibilidades = payload.get("disponibilidades", [])
            return {
                "agendamentos": agendamentos if isinstance(agendamentos, list) else [],
                "disponibilidades": disponibilidades if isinstance(disponibilidades, list) else [],
            }

        if isinstance(payload, list):
            return {
                "agendamentos": payload,
                "disponibilidades": [],
            }

        return {
            "agendamentos": [],
            "disponibilidades": [],
        }

    def _download_from_github(self, remote_path: str) -> Optional[Any]:
        try:
            response = self._github_request("GET", self._read_contents_url(remote_path))
        except error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise StorageError(f"Falha ao ler {remote_path} no GitHub: HTTP {exc.code}") from exc
        except error.URLError as exc:
            raise StorageError(f"Falha de rede ao ler {remote_path} no GitHub") from exc

        content = response.get("content", "")
        if not content:
            return None

        decoded = base64.b64decode(content).decode("utf-8")
        return json.loads(decoded)

    def _upload_to_github(
        self,
        remote_path: str,
        payload: dict[str, Any],
        commit_message: str,
    ) -> None:
        existing_sha = None
        try:
            response = self._github_request("GET", self._read_contents_url(remote_path))
            existing_sha = response.get("sha")
        except error.HTTPError as exc:
            if exc.code != 404:
                raise StorageError(
                    f"Falha ao preparar escrita de {remote_path} no GitHub: HTTP {exc.code}"
                ) from exc
        except error.URLError as exc:
            raise StorageError(f"Falha de rede ao preparar escrita de {remote_path} no GitHub") from exc

        raw_payload = json.dumps(payload, ensure_ascii=False, indent=2)
        request_payload = {
            "message": commit_message,
            "content": base64.b64encode(raw_payload.encode("utf-8")).decode("utf-8"),
            "branch": GITHUB_REPO_BRANCH,
        }
        if existing_sha:
            request_payload["sha"] = existing_sha

        try:
            self._github_request(
                "PUT",
                self._write_contents_url(remote_path),
                data=request_payload,
            )
        except error.HTTPError as exc:
            raise StorageError(
                f"Falha ao gravar {remote_path} no GitHub: HTTP {exc.code}"
            ) from exc
        except error.URLError as exc:
            raise StorageError(f"Falha de rede ao gravar {remote_path} no GitHub") from exc

    def _github_request(
        self,
        method: str,
        url: str,
        data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")

        req = request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if body is not None:
            req.add_header("Content-Type", "application/json")

        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _read_contents_url(self, remote_path: str) -> str:
        return (
            f"{GITHUB_API_URL}/repos/"
            f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{remote_path}"
            f"?ref={GITHUB_REPO_BRANCH}"
        )

    def _write_contents_url(self, remote_path: str) -> str:
        return (
            f"{GITHUB_API_URL}/repos/"
            f"{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{remote_path}"
        )

    def _read_local_file(
        self,
        local_path: Path,
        default_payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            return json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            self._write_local_file(local_path, default_payload)
            return default_payload

    def _write_local_file(self, local_path: Path, payload: dict[str, Any]) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _resolve_local_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        return (REPO_ROOT / path).resolve()

    def _normalize_remote_path(self, file_path: str) -> str:
        return file_path.replace("\\", "/").lstrip("/")
