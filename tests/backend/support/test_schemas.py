from uuid import UUID

import pytest
from pydantic import ValidationError

from backend.app.support.schemas import (
    ActionRequest,
    CommentCreate,
    TicketCreate,
    validate_attachment,
)


DEVICE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


def test_action_catalog_rejects_arbitrary_commands_and_extra_parameters() -> None:
    with pytest.raises(ValidationError):
        ActionRequest.model_validate(
            {
                "action_name": "run_shell",
                "parameters": {"command": "whoami"},
            }
        )

    with pytest.raises(ValidationError):
        ActionRequest.model_validate(
            {
                "action_name": "flush_dns",
                "parameters": {"command": "whoami"},
            }
        )


def test_action_parameters_are_strict_bounded_and_canonical() -> None:
    request = ActionRequest.model_validate(
        {
            "action_name": "collect_extended_diagnostics",
            "parameters": {"max_log_lines": 500, "include_logs": True},
        }
    )

    assert request.canonical_parameters == (
        '{"include_logs":true,"max_log_lines":500}'
    )

    with pytest.raises(ValidationError):
        ActionRequest.model_validate(
            {
                "action_name": "collect_extended_diagnostics",
                "parameters": {"max_log_lines": 1.5, "include_logs": True},
            }
        )


def test_text_models_forbid_extra_fields_and_control_characters() -> None:
    ticket = TicketCreate.model_validate(
        {
            "device_id": str(DEVICE_ID),
            "title": " Ticket ",
            "description": "Detail",
            "priority": "HIGH",
        }
    )
    assert ticket.device_id == DEVICE_ID
    assert ticket.title == "Ticket"

    with pytest.raises(ValidationError):
        TicketCreate.model_validate(
            {
                "title": "Ticket",
                "description": "Detail",
                "priority": "HIGH",
                "organization_id": str(UUID(int=1)),
            }
        )

    with pytest.raises(ValidationError):
        CommentCreate.model_validate({"content": "bad\u0000text"})

    with pytest.raises(ValidationError):
        CommentCreate.model_validate({"content": "   "})


def test_attachment_uses_magic_bytes_and_enforces_ten_megabytes() -> None:
    metadata = validate_attachment(
        original_name="screen.png",
        content=b"\x89PNG\r\n\x1a\n" + b"safe",
    )

    assert metadata.mime_type == "image/png"
    assert metadata.file_size == 12
    assert metadata.stored_filename.endswith(".png")
    assert "/" not in metadata.stored_filename

    sanitized = validate_attachment(
        original_name='bad";name.png',
        content=b"\x89PNG\r\n\x1a\n",
    )
    assert '"' not in sanitized.original_name
    assert ";" not in sanitized.original_name

    with pytest.raises(ValueError, match="Tipo de archivo no permitido"):
        validate_attachment(original_name="payload.png", content=b"MZ" + b"x")

    with pytest.raises(ValueError, match="10 MB"):
        validate_attachment(
            original_name="huge.pdf",
            content=b"%PDF-" + b"x" * (10 * 1024 * 1024),
        )
