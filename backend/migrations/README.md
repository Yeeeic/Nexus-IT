# Database migrations

Alembic owns versioned schema changes. Migrations connect with the private bootstrap credential, assume the non-login `nexus_admin` ownership role, create or alter objects, then reset the role before Alembic records the revision.

Runtime access uses `nexus_app_user`. This role is not a superuser, cannot bypass RLS, cannot create databases or roles, and cannot create objects in the `public` schema. It receives only explicit privileges required by each migration.

Run migrations through the isolated Compose tool container documented in `infra/README.md`. Never place database passwords in Alembic configuration or migration files.
