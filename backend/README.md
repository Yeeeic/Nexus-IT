# Backend

Antigravity and coding-agent instructions: [`backend/AGENTS.md`](AGENTS.md).
Current resume state: [`tasks/checkpoint-2026-08-24.md`](../tasks/checkpoint-2026-08-24.md).

FastAPI modular monolith. Public endpoints are versioned under `/api/v1`.

Authentication foundations use Argon2id, opaque browser sessions, strict schemas,
minimum-privilege PostgreSQL roles, and forced RLS. Runtime database access must use
the dedicated `nexus_runtime` principal provisioned by `infra/provision-runtime`;
bootstrap credentials are migration-only.

Implemented public routes:

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/context`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/password-reset/confirm`
- `GET /api/v1/users` (`users:manage`)

Private requests derive user, organization, and RBAC permissions from the opaque
server-side session. Cookie-authenticated mutations require double-submit CSRF.
Password-reset confirmation uses a rate-limited opaque token, consumes it under
`SELECT ... FOR UPDATE`, and atomically revokes all other reset tokens and sessions.
