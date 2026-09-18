import os
import sys
from uuid import UUID
import psycopg

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))
from app.auth.passwords import hash_password

def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Required environment variable is missing: {name}")
    return value

def main():
    db_password = required_env("NEXUS_POSTGRES_PASSWORD")
    conn = psycopg.connect(
        host="127.0.0.1",
        port=5432,
        user="nexus_bootstrap",
        password=db_password,
        dbname="nexus_it",
        autocommit=True,
    )
    cur = conn.cursor()

    user_id = "55555555-5555-4555-8555-555555555555"
    email = required_env("NEXUS_SEED_CLIENT_EMAIL").lower()
    plain_pass = required_env("NEXUS_SEED_CLIENT_PASSWORD")
    if len(plain_pass) < 12 or not any(c.isalpha() for c in plain_pass) or not any(c.isdigit() for c in plain_pass):
        raise RuntimeError("NEXUS_SEED_CLIENT_PASSWORD must contain at least 12 characters, a letter, and a digit")
    hashed = hash_password(plain_pass)
    org_id = "433c3bff-ad15-4e34-bc3a-d5d10becf08f"
    role_id = "10000000-0000-4000-8000-000000000003" # READER
    device_id = "6879aae6-8b6f-4396-be01-7b19cffb73a8" # carlos device
    admin_id = "473f764a-6f32-41b2-abd3-9377855b29a8"

    # Insert / update user
    cur.execute("""
        INSERT INTO users (id, email, password_hash, full_name, is_active)
        VALUES (%s, %s, %s, %s, true)
        ON CONFLICT (email) DO NOTHING;
    """, (user_id, email, hashed, "Carlos (Usuario Monitoreado)"))

    # Membership
    cur.execute("""
        INSERT INTO organization_memberships (user_id, organization_id, is_active)
        VALUES (%s, %s, true)
        ON CONFLICT (user_id, organization_id) DO NOTHING;
    """, (user_id, org_id))

    # Role
    cur.execute("""
        INSERT INTO user_roles (user_id, role_id, organization_id)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, role_id, organization_id) DO NOTHING;
    """, (user_id, role_id, org_id))

    # Device assignment
    cur.execute("""
        INSERT INTO device_assignments (device_id, user_id, organization_id, assigned_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (device_id) DO UPDATE SET user_id = EXCLUDED.user_id;
    """, (device_id, user_id, org_id, admin_id))

    conn.close()
    print("[+] Usuario cliente creado con exito:")
    print(f"    Email:        {email}")
    print("    Contrasena:   configurada mediante variable de entorno; no se muestra")
    print(f"    Rol:          READER (Portal de Usuario)")
    print(f"    Dispositivo:  carlos (ID: {device_id})")

if __name__ == "__main__":
    main()
