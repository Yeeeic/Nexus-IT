import { useState } from "react";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { actionsApi } from "@/api/actions";
import { useNotification } from "@/context/NotificationContext";
import { AlertTriangle, HardDrive, ShieldCheck, Zap } from "lucide-react";

export interface PendingRemediation {
  deviceId: string;
  hostname: string;
  diskPercent: number;
  message?: string;
}

export interface AutoRemediationPromptModalProps {
  remediation: PendingRemediation | null;
  onClose: () => void;
  onSuccess?: () => void;
}

export function AutoRemediationPromptModal({
  remediation,
  onClose,
  onSuccess,
}: AutoRemediationPromptModalProps) {
  const [isExecuting, setIsExecuting] = useState(false);
  const { success, error: notifyError } = useNotification();

  if (!remediation) return null;

  const handleAuthorizeAndExecute = async () => {
    setIsExecuting(true);
    try {
      // 1. Dispatch remote action
      const actionRes = await actionsApi.create(remediation.deviceId, {
        action_name: "collect_extended_diagnostics",
        parameters: { include_logs: true, max_log_lines: 1000 },
      });

      // 2. Submit approval if pending
      if (actionRes.status === "PENDING_APPROVAL") {
        await actionsApi.submitApproval(actionRes.id);
      }

      success(
        "Diagnóstico autorizado",
        `Se despachó la orden firmada 'collect_extended_diagnostics' al dispositivo ${remediation.hostname}. Registrado en auditoría.`
      );
      if (onSuccess) onSuccess();
      onClose();
    } catch (err: any) {
      notifyError("Error al ejecutar remediación", err.message || "No se pudo autorizar la acción.");
    } finally {
      setIsExecuting(false);
    }
  };

  return (
    <Modal
      isOpen={Boolean(remediation)}
      onClose={onClose}
      title="⚠️ Alerta Crítica & Solicitud de Auto-Remediación"
      maxWidth="540px"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        {/* Warning Banner */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            gap: "0.75rem",
            padding: "1rem",
            backgroundColor: "rgba(239, 68, 68, 0.1)",
            border: "1px solid var(--status-critical)",
            borderRadius: "var(--radius-lg)",
          }}
        >
          <AlertTriangle size={24} color="var(--status-critical)" style={{ flexShrink: 0, marginTop: "2px" }} />
          <div>
            <div style={{ fontWeight: 700, fontSize: "var(--text-sm)", color: "var(--status-critical)" }}>
              Capacidad de Almacenamiento Crítica (&gt; 95%)
            </div>
            <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem", lineHeight: 1.4 }}>
              El agente en el equipo <strong>{remediation.hostname}</strong> reporta un uso de disco de <strong>{remediation.diskPercent.toFixed(1)}%</strong>, superando el umbral de seguridad operacional.
            </p>
          </div>
        </div>

        {/* Proposed Action Card */}
        <div
          style={{
            padding: "1rem",
            backgroundColor: "var(--bg-surface-elevated)",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
            display: "flex",
            flexDirection: "column",
            gap: "0.5rem",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600, fontSize: "var(--text-sm)" }}>
              <HardDrive size={16} color="var(--brand-primary)" />
              <span>Acción Propuesta: <code>collect_extended_diagnostics</code></span>
            </div>
            <Badge variant="warning">Requiere Autorización</Badge>
          </div>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.4 }}>
            Esta acción recopila diagnóstico permitido para que un técnico determine la causa. No elimina archivos ni libera espacio automáticamente.
          </p>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "var(--text-2xs)", color: "var(--text-muted)", marginTop: "0.25rem" }}>
            <ShieldCheck size={12} color="var(--status-healthy)" />
            <span>Firmado con Ed25519 • Registro obligatorio en Audit Logs</span>
          </div>
        </div>

        {/* Action Buttons */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.75rem", marginTop: "0.5rem" }}>
          <Button variant="secondary" onClick={onClose} disabled={isExecuting}>
            Posponer / Descartar
          </Button>
          <Button
            variant="primary"
            onClick={handleAuthorizeAndExecute}
            isLoading={isExecuting}
            leftIcon={<Zap size={14} />}
          >
            Autorizar y Ejecutar Ahora
          </Button>
        </div>
      </div>
    </Modal>
  );
}
