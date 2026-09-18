"""Seed script to create the initial administrative organization and user."""

import asyncio
import os
from uuid import uuid4
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import URL, text
from backend.app.auth.passwords import hash_password

def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value

async def main() -> None:
    db_host = os.getenv("NEXUS_POSTGRES_HOST", os.getenv("NEXUS_DATABASE_HOST", "postgres"))
    db_port = os.getenv("NEXUS_POSTGRES_PORT", os.getenv("NEXUS_DATABASE_PORT", "5432"))
    db_name = os.getenv("NEXUS_POSTGRES_DB", "nexus_it")
    db_user = os.getenv("NEXUS_POSTGRES_USER", "nexus_bootstrap")
    db_pass = required_env("NEXUS_POSTGRES_PASSWORD")

    database_url = URL.create("postgresql+psycopg", username=db_user, password=db_pass, host=db_host, port=int(db_port), database=db_name)
    print(f"Connecting to database: {db_host}:{db_port}/{db_name} ...")
    engine = create_async_engine(database_url)

    org_id = uuid4()
    user_id = uuid4()
    email = required_env("NEXUS_SEED_ADMIN_EMAIL").lower()
    raw_password = required_env("NEXUS_SEED_ADMIN_PASSWORD")
    if len(raw_password) < 12 or not any(c.isalpha() for c in raw_password) or not any(c.isdigit() for c in raw_password):
        raise RuntimeError("NEXUS_SEED_ADMIN_PASSWORD must contain at least 12 characters, a letter, and a digit")
    hashed_pwd = hash_password(raw_password)
    full_name = "Administrador Principal"

    async with engine.begin() as conn:
        # Check if organization already exists
        res = await conn.execute(text("SELECT id FROM public.organizations WHERE slug = 'nexus-corp' LIMIT 1"))
        row = res.mappings().first()
        if row:
            org_id = row["id"]
            print(f"Organization 'nexus-corp' already exists with ID: {org_id}")
        else:
            await conn.execute(
                text(
                    """
                    INSERT INTO public.organizations (id, name, slug, is_active)
                    VALUES (:id, :name, :slug, true)
                    """
                ),
                {"id": org_id, "name": "Nexus IT Corporativo", "slug": "nexus-corp"}
            )
            print(f"Created organization 'Nexus IT Corporativo' with ID: {org_id}")

        # Check if user already exists
        res_u = await conn.execute(text("SELECT id FROM public.users WHERE email = :email LIMIT 1"), {"email": email})
        row_u = res_u.mappings().first()
        if row_u:
            user_id = row_u["id"]
            print(f"User '{email}' already exists; password was not changed.")
        else:
            await conn.execute(
                text(
                    """
                    INSERT INTO public.users (id, email, password_hash, full_name, is_active)
                    VALUES (:id, :email, :pwd, :name, true)
                    """
                ),
                {"id": user_id, "email": email, "pwd": hashed_pwd, "name": full_name}
            )
            print(f"Created user '{email}' with ID: {user_id}")

        # Ensure membership
        await conn.execute(
            text(
                """
                INSERT INTO public.organization_memberships (organization_id, user_id, is_active)
                VALUES (:org_id, :user_id, true)
                ON CONFLICT (organization_id, user_id) DO UPDATE SET is_active = true
                """
            ),
            {"org_id": org_id, "user_id": user_id}
        )
        print("Ensured organization membership.")

        # Assign ADMIN role
        res_role = await conn.execute(text("SELECT id, scope_id FROM public.roles WHERE name = 'ADMIN' AND is_system = true LIMIT 1"))
        role_row = res_role.mappings().first()
        if role_row:
            role_id = role_row["id"]
            role_scope_id = role_row["scope_id"]
            await conn.execute(
                text(
                    """
                    INSERT INTO public.user_roles (organization_id, user_id, role_scope_id, role_id)
                    VALUES (:org_id, :user_id, :role_scope_id, :role_id)
                    ON CONFLICT (organization_id, user_id, role_id) DO NOTHING
                    """
                ),
                {"org_id": org_id, "user_id": user_id, "role_scope_id": role_scope_id, "role_id": role_id}
            )
            print(f"Assigned ADMIN role ({role_id}) to user.")

    await engine.dispose()
    print("\n========================================================")
    print("  CUENTA DE ADMINISTRADOR CREADA / LISTA")
    print("========================================================")
    print(f"  Organización: Nexus IT Corporativo")
    print(f"  Usuario:      {email}")
    print("  Contraseña:   configurada mediante variable de entorno; no se muestra")
    print("========================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
