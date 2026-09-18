import { useState } from "react";
import { devicesApi } from "@/api/devices";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { useNotification } from "@/context/NotificationContext";
import { Copy, Check, Terminal, ShieldAlert } from "lucide-react";

export interface DeviceEnrollModalProps {
  deviceId: string | null;
  deviceHostname?: string;
  initialToken?: string | undefined;
  isOpen: boolean;
  onClose: () => void;
}

export function DeviceEnrollModal({
  deviceId,
  deviceHostname,
  initialToken,
  isOpen,
  onClose,
}: DeviceEnrollModalProps) {
  const { success, error: notifyError } = useNotification();
  const [tokenValue, setTokenValue] = useState<string | null>(initialToken || null);
  const [isLoading, setIsLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const handleGenerate = async () => {
    if (!deviceId) return;
    setIsLoading(true);
    try {
      const resp = await devicesApi.createToken(deviceId);
      setTokenValue(resp.token);
      success("Token generado exitosamente", "Utilice este token para aprovisionar el agente.");
    } catch (err: any) {
      notifyError("Error al generar token de agente", err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleCopy = () => {
    if (!tokenValue) return;
    navigator.clipboard.writeText(tokenValue);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    success("Token copiado al portapapeles");
  };

  const handleClose = () => {
    setTokenValue(null);
    setCopied(false);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title="Aprovisionamiento de Agente de Monitoreo"
      description={`Dispositivo: ${deviceHostname || "Equipo Seleccionado"}`}
      footer={
        <Button variant="secondary" onClick={handleClose}>
          Cerrar
        </Button>
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        {!tokenValue ? (
          <div style={{ textAlign: "center", padding: "1.5rem 0" }}>
            <Terminal size={40} color="var(--brand-primary)" style={{ margin: "0 auto 1rem" }} />
            <p style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)", marginBottom: "1.5rem" }}>
              Se generará un token criptográfico de máquina para autenticar el agente Python en este equipo.
            </p>
            <Button
              variant="primary"
              onClick={handleGenerate}
              isLoading={isLoading}
            >
              Generar Token de Agente
            </Button>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
            <div
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "0.5rem",
                padding: "0.75rem 1rem",
                backgroundColor: "var(--status-warning-bg)",
                border: "1px solid var(--status-warning-border)",
                borderRadius: "var(--radius-md)",
                fontSize: "var(--text-xs)",
                color: "var(--status-warning)",
              }}
            >
              <ShieldAlert size={16} style={{ flexShrink: 0, marginTop: "2px" }} />
              <div>
                Copie este token ahora. Por motivos de seguridad (HMAC con pepper en servidor), no podrá ser visualizado nuevamente una vez cerrada esta ventana.
              </div>
            </div>

            <div>
              <label style={{ fontSize: "var(--text-xs)", fontWeight: 500, color: "var(--text-secondary)" }}>
                Token de Agente (Bearer Token)
              </label>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "0.5rem",
                  marginTop: "0.375rem",
                  padding: "0.75rem",
                  backgroundColor: "var(--bg-input)",
                  border: "1px solid var(--border-default)",
                  borderRadius: "var(--radius-md)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-xs)",
                  wordBreak: "break-all",
                }}
              >
                <span style={{ flex: 1, color: "var(--brand-primary)" }}>{tokenValue}</span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCopy}
                  leftIcon={copied ? <Check size={14} /> : <Copy size={14} />}
                >
                  {copied ? "Copiado" : "Copiar"}
                </Button>
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
              <label style={{ fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--text-secondary)" }}>
                Comando para iniciar el agente en la máquina / terminal:
              </label>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: "0.5rem",
                  padding: "0.75rem",
                  backgroundColor: "var(--bg-sidebar)",
                  border: "1px solid var(--border-subtle)",
                  borderRadius: "var(--radius-md)",
                  fontFamily: "var(--font-mono)",
                  fontSize: "var(--text-2xs)",
                  overflowX: "auto",
                }}
              >
                <code style={{ color: "var(--text-primary)", whiteSpace: "nowrap" }}>
                  python -m agent.run_agent
                </code>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    navigator.clipboard.writeText("python -m agent.run_agent");
                    success("Comando copiado al portapapeles");
                  }}
                  leftIcon={<Copy size={13} />}
                >
                  Copiar Comando
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
}
