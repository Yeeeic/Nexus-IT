# Infrastructure

Docker Compose, database initialization, reverse-proxy configuration, and deployment assets live here.

Local services must bind only to loopback unless a reviewed deployment configuration explicitly changes that boundary.

## Local startup

Run these commands from the repository root in PowerShell:

```powershell
.\infra\initialize-local-env.ps1
docker compose --env-file .env -f infra\compose.yaml up --detach postgres redis
docker compose --env-file .env -f infra\compose.yaml --profile tools run --rm migrate
docker compose --env-file .env -f infra\compose.yaml --profile tools run --rm provision-runtime
docker compose --env-file .env -f infra\compose.yaml --profile tools run --rm seed-admin
docker compose --env-file .env -f infra\compose.yaml up --detach --build backend
docker compose --env-file .env -f infra\compose.yaml up --detach --build frontend
```

The initialization script creates `.env` only when it does not already exist. It never overwrites local secrets.

Verify the API at `http://127.0.0.1:8000/health`. PostgreSQL and Redis remain accessible only to the private container network.

Stop the services without removing containers, networks, or database data:

```powershell
docker compose --env-file .env -f infra\compose.yaml stop
```

The migration and provisioning containers receive the bootstrap database credential, perform one bounded task, then exit. Provisioning creates or rotates `nexus_runtime` for request traffic and `nexus_maintenance_runtime` for the scheduled metrics worker. Each has an independent password and non-owning roles. The API container never receives the bootstrap credential.

Before running `seed-admin`, set `NEXUS_SEED_ADMIN_EMAIL` and `NEXUS_SEED_ADMIN_PASSWORD` only in the local `.env` (minimum 12 characters, letters and digits). The seed command is a one-shot local bootstrap; it does not print the password and does not overwrite an existing user's password.
