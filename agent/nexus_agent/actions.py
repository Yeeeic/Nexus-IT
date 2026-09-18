"""Durable at-most-once execution gate for allowlisted remote actions."""

from __future__ import annotations

import json
import base64
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Tuple
from uuid import UUID

from .compat import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .permissions import harden_directory, harden_file

UTC = timezone.utc


ACTION_CATALOG = frozenset(
    {
        "restart_service",
        "flush_dns",
        "collect_extended_diagnostics",
        "reboot_system",
    }
)
TERMINAL_STATES = frozenset(
    {"SUCCEEDED", "FAILED", "INTERRUPTED", "UNKNOWN"}
)
ActionHandler = Callable[[Dict[str, object]], Tuple[int, str]]


@dataclass(frozen=True, slots=True)
class AgentActionOrder:
    action_execution_id: UUID
    organization_id: UUID
    device_id: UUID
    nonce: UUID
    action_name: str
    action_version: int
    key_version: int
    issued_at: str
    expires_at: str
    order_digest: str
    signature: str
    parameters_canonical: str


def build_signing_payload(order: AgentActionOrder) -> bytes:
    return "\n".join(
        (
            "nexus-action:v1",
            str(order.action_execution_id),
            str(order.organization_id),
            str(order.device_id),
            order.action_name,
            str(order.nonce),
            str(order.key_version),
            order.issued_at,
            order.expires_at,
            order.parameters_canonical,
        )
    ).encode("utf-8")


def verify_order_signature(
    order: AgentActionOrder,
    *,
    public_keys: Mapping[int, bytes],
    now: datetime,
    clock_skew_seconds: int = 60,
) -> datetime:
    if now.tzinfo is None:
        raise ValueError("Reloj local sin zona horaria")
    try:
        issued_at = datetime.strptime(
            order.issued_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
        expires_at = datetime.strptime(
            order.expires_at, "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=UTC)
    except ValueError:
        raise ValueError("Timestamp de acción inválido") from None
    effective_now = now.astimezone(UTC)
    skew = timedelta(seconds=clock_skew_seconds)
    if (
        expires_at <= issued_at
        or expires_at - issued_at > timedelta(minutes=5)
        or issued_at > effective_now + skew
        or expires_at < effective_now - skew
    ):
        raise ValueError("Acción expirada o fuera de tolerancia")
    public_key = public_keys.get(order.key_version)
    if public_key is None or len(public_key) != 32:
        raise ValueError("Versión de clave desconocida")
    try:
        signature = base64.urlsafe_b64decode(order.signature + "==")
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature, build_signing_payload(order)
        )
    except (ValueError, InvalidSignature):
        raise ValueError("Firma de acción inválida") from None
    return expires_at


class SQLiteActionStore:
    def __init__(self, database_path: Path) -> None:
        if not database_path.is_absolute():
            raise ValueError("La ruta SQLite debe ser absoluta")
        self._database_path = database_path
        harden_directory(database_path.parent)
        self._initialize()
        harden_file(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self._database_path,
            timeout=5,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                PRAGMA synchronous = FULL;
                CREATE TABLE IF NOT EXISTS consumed_nonces (
                    nonce TEXT PRIMARY KEY,
                    expires_at_with_skew INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS action_states (
                    action_execution_id TEXT PRIMARY KEY,
                    organization_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    nonce TEXT UNIQUE NOT NULL,
                    action_name TEXT NOT NULL,
                    action_version INTEGER NOT NULL DEFAULT 1,
                    key_version INTEGER NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    order_digest TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    parameters_canonical TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (
                        status IN (
                            'ACCEPTED','EXECUTING','SUCCEEDED','FAILED',
                            'INTERRUPTED','UNKNOWN'
                        )
                    ),
                    exit_code INTEGER NULL,
                    output_summary TEXT NULL,
                    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                    updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                    FOREIGN KEY (nonce) REFERENCES consumed_nonces(nonce)
                );
                """
            )

    @staticmethod
    def validate_order(order: AgentActionOrder) -> dict[str, object]:
        if order.action_name not in ACTION_CATALOG:
            raise ValueError("Acción no permitida")
        for identifier in (
            order.action_execution_id,
            order.organization_id,
            order.device_id,
            order.nonce,
        ):
            if identifier.version != 4 or str(identifier) != str(identifier).lower():
                raise ValueError("Identificador de acción inválido")
        if order.action_version != 1 or order.key_version < 1:
            raise ValueError("Versión de acción inválida")
        try:
            parameters = json.loads(order.parameters_canonical)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("Parámetros inválidos") from None
        if not isinstance(parameters, dict):
            raise ValueError("Parámetros inválidos")
        if any(
            not isinstance(value, (str, bool, int)) or isinstance(value, float)
            for value in parameters.values()
        ):
            raise ValueError("Parámetros inválidos")
        canonical = json.dumps(
            parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical != order.parameters_canonical:
            raise ValueError("Parámetros no canónicos")
        digest = hashlib.sha256(build_signing_payload(order)).hexdigest()
        if order.order_digest != digest:
            raise ValueError("Digest de acción inválido")
        return parameters

    def verify_and_accept(
        self,
        order: AgentActionOrder,
        *,
        public_keys: Mapping[int, bytes],
        now: datetime,
    ) -> bool:
        expires_at = verify_order_signature(
            order, public_keys=public_keys, now=now
        )
        return self.accept(
            order,
            expires_at_with_skew=int(expires_at.timestamp()) + 60,
        )

    def accept(self, order: AgentActionOrder, *, expires_at_with_skew: int) -> bool:
        self.validate_order(order)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO consumed_nonces (nonce, expires_at_with_skew) "
                "VALUES (?, ?)",
                (str(order.nonce), expires_at_with_skew),
            )
            connection.execute(
                """
                INSERT INTO action_states (
                    action_execution_id, organization_id, device_id, nonce,
                    action_name, action_version, key_version, issued_at,
                    expires_at, order_digest, signature,
                    parameters_canonical, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED')
                """,
                (
                    str(order.action_execution_id),
                    str(order.organization_id),
                    str(order.device_id),
                    str(order.nonce),
                    order.action_name,
                    order.action_version,
                    order.key_version,
                    order.issued_at,
                    order.expires_at,
                    order.order_digest,
                    order.signature,
                    order.parameters_canonical,
                ),
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError:
            connection.rollback()
            return False
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim(self, action_execution_id: UUID) -> bool:
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE action_states
                SET status = 'EXECUTING', updated_at = strftime('%s', 'now')
                WHERE action_execution_id = ? AND status = 'ACCEPTED'
                """,
                (str(action_execution_id),),
            )
            return result.rowcount == 1

    def status(self, action_execution_id: UUID) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status FROM action_states WHERE action_execution_id = ?",
                (str(action_execution_id),),
            ).fetchone()
            return row["status"] if row is not None else None

    def _load_execution(
        self, action_execution_id: UUID
    ) -> tuple[str, dict[str, object]] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT action_name, parameters_canonical
                FROM action_states
                WHERE action_execution_id = ?
                """,
                (str(action_execution_id),),
            ).fetchone()
        if row is None:
            return None
        return row["action_name"], json.loads(row["parameters_canonical"])

    def _finish(
        self,
        action_execution_id: UUID,
        *,
        status: str,
        exit_code: int | None,
        output_summary: str,
    ) -> None:
        if status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("Estado terminal inválido")
        with self._connect() as connection:
            result = connection.execute(
                """
                UPDATE action_states
                SET status = ?, exit_code = ?, output_summary = ?,
                    updated_at = strftime('%s', 'now')
                WHERE action_execution_id = ? AND status = 'EXECUTING'
                """,
                (
                    status,
                    exit_code,
                    output_summary[:2000],
                    str(action_execution_id),
                ),
            )
            if result.rowcount != 1:
                raise RuntimeError("Estado de acción cambió")

    def execute_once(
        self,
        action_execution_id: UUID,
        handlers: Mapping[str, ActionHandler],
    ) -> bool:
        execution = self._load_execution(action_execution_id)
        if execution is None:
            return False
        action_name, parameters = execution
        if action_name not in ACTION_CATALOG or action_name not in handlers:
            raise ValueError("Acción sin manejador autorizado")
        if not self.claim(action_execution_id):
            return False
        try:
            exit_code, summary = handlers[action_name](parameters)
        except Exception as error:
            self._finish(
                action_execution_id,
                status="FAILED",
                exit_code=None,
                output_summary=type(error).__name__,
            )
            return True
        self._finish(
            action_execution_id,
            status="SUCCEEDED" if exit_code == 0 else "FAILED",
            exit_code=exit_code,
            output_summary=summary,
        )
        return True

    def reconcile_after_restart(self, *, now_epoch: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE action_states
                SET status = 'UNKNOWN', updated_at = strftime('%s', 'now')
                WHERE status = 'EXECUTING'
                """
            )
            connection.execute(
                """
                UPDATE action_states
                SET status = 'INTERRUPTED', updated_at = strftime('%s', 'now')
                WHERE status = 'ACCEPTED'
                  AND nonce IN (
                      SELECT nonce FROM consumed_nonces
                      WHERE expires_at_with_skew <= ?
                  )
                """,
                (now_epoch,),
            )
