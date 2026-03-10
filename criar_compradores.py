#!/usr/bin/env python3
"""
Script para criar compradores de exemplo em auth.json.
"""
from datetime import datetime

from auth import criar_hash_senha, storage
from storage import StorageError


def criar_compradores() -> None:
    """Cria compradores de exemplo no arquivo auth.json."""
    try:
        storage.initialize_files()
        usuarios = storage.list_users()
        compradores_existentes = [u for u in usuarios if u.get("tipo") == "comprador"]
        if compradores_existentes:
            print(f"Ja existem {len(compradores_existentes)} compradores cadastrados.")
            return

        compradores = [
            {"nome": "Maria Silva", "email": "maria@empresa.com", "senha": "123456"},
            {"nome": "Joao Santos", "email": "joao@empresa.com", "senha": "123456"},
            {"nome": "Ana Oliveira", "email": "ana@empresa.com", "senha": "123456"},
            {"nome": "Carlos Ferreira", "email": "carlos@empresa.com", "senha": "123456"},
            {"nome": "Fernanda Costa", "email": "fernanda@empresa.com", "senha": "123456"},
        ]

        agora = datetime.utcnow().isoformat(timespec="seconds")
        next_id = max((usuario.get("id", 0) for usuario in usuarios), default=0) + 1
        for comprador in compradores:
            usuarios.append(
                {
                    "id": next_id,
                    "nome": comprador["nome"],
                    "email": comprador["email"],
                    "senha_hash": criar_hash_senha(comprador["senha"]),
                    "tipo": "comprador",
                    "ativo": True,
                    "criado_em": agora,
                }
            )
            next_id += 1
            print(f"Criado: {comprador['nome']} ({comprador['email']})")

        storage.save_users(usuarios, "Cria compradores via script")
        print(f"\n{len(compradores)} compradores criados com sucesso!")
        print("\nCredenciais de acesso:")
        print("-" * 50)
        for comprador in compradores:
            print(f"Email: {comprador['email']}")
            print(f"Senha inicial: {comprador['senha']}")
            print("-" * 50)
    except StorageError as exc:
        print(f"Erro ao criar compradores: {exc}")


if __name__ == "__main__":
    print("Criando compradores de exemplo...")
    print("=" * 50)
    criar_compradores()
