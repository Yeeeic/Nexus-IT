import { useState } from "react";
import { actionsApi } from "@/api/actions";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { useNotification } from "@/context/NotificationContext";
import { ShieldAlert, CheckCircle } from "lucide-react";
import type { ActionResponse } from "@/types/actions";

export interface ActionApprovalModalProps {
  action: ActionResponse | null;
  isOpen: boolean;
  onClose: () => void;
  onProcessed: () => void;
}

export function ActionApprovalModal({
  action,
  isOpen,
  onClose,
  onProcessed,
}: ActionApprovalModalProps) {
  const { success, error: notifyError } = useNotification();
  const [isLoading, setIsLoading] = useState(false);

  if (!action) return null;

  const handleApprove = async () => {
    setIsLoading(true);
    try {
      await actionsApi.submitApproval(action.id);
      success(
        "Acción remota aprobada y firmada",
        `Comando: ${action.action_name}`
      );
      onProcessed();
      onClose();
    } catch (err: any) {
      notifyError("Error al procesar la aprobación", err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Aprobación de Acción Remota"
      description={`Dispositivo ID: ${action.device_id}`}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        <div
          style={{
            padding: "0.75rem 1rem",
            backgroundColor: "var(--status-warning-bg)",
            border: "1px solid var(--status-warning-border)",
            borderRadius: "var(--radius-md)",
            display: "flex",
            alignItems: "flex-start",
            gap: "0.75rem",
            color: "var(--status-warning)",
            fontSize: "var(--text-xs)",
          }}
        >
          <ShieldAlert size={18} style={{ flexShrink: 0, marginTop: "2px" }} />
          <div>
            Esta acción requiere autorización de administrador y será firmada asimétricamente con <strong>Ed25519</strong> en el servidor antes de ser despachada al agente de monitoreo.
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", fontSize: "var(--text-sm)" }}>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Acción solicitada:</span>{" "}
            <strong style={{ fontFamily: "var(--font-mono)", color: "var(--brand-primary)" }}>{action.action_name}</strong>
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>ID de Solicitud:</span>{" "}
            <strong style={{ fontFamily: "var(--font-mono)" }}>{action.id}</strong>
          </div>
          <div>
            <span style={{ color: "var(--text-muted)" }}>Parámetros:</span>
            <pre
              style={{
                marginTop: "0.25rem",
                padding: "0.5rem",
                backgroundColor: "var(--bg-input)",
                border: "1px solid var(--border-subtle)",
                borderRadius: "var(--radius-sm)",
                fontFamily: "var(--font-mono)",
                fontSize: "var(--text-2xs)",
              }}
            >
              {JSON.stringify(action.parameters, null, 2)}
            </pre>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "1rem" }}>
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
          >
            Cancelar
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={isLoading}
            onClick={handleApprove}
            leftIcon={<CheckCircle size={16} />}
          >
            Aprobar y Firmar Ed25519
          </Button>
        </div>
      </div>
    </Modal>
  );
}
