import { useState } from "react";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { useNotification } from "@/context/NotificationContext";
import { Terminal, Copy, Check, Shield, Cpu, HardDrive } from "lucide-react";

export interface QuickInstallerModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function QuickInstallerModal({ isOpen, onClose }: QuickInstallerModalProps) {
  const [platform, setPlatform] = useState<"windows" | "linux">("windows");
  const [copied, setCopied] = useState(false);
  const { success } = useNotification();

  const apiOrigin = typeof window !== "undefined" ? window.location.origin : "https://nexus.example.com";
  const allowInsecurePowerShell = apiOrigin.startsWith("http://") ? " -AllowInsecureHttp" : "";
  const allowInsecureLinux = apiOrigin.startsWith("http://") ? "true" : "false";
  const publicKeysPlaceholder = '{"1":"<CLAVE_PUBLICA_ED25519_BASE64>"}';
  const windowsPackageVersion = "1.0.0";
  const windowsPackageSha256 = "a447aad4d54c541aca7966dd9eab07116ac4fdcf38514131f824332fdc98f534";

  const windowsScript = `# Windows 10, 11 y Windows Server:
# Descarga primero el instalador. Verifica su origen antes de ejecutarlo.
$InstallerPath = Join-Path $env:TEMP "nexus-install-agent.ps1"
Invoke-WebRequest "${apiOrigin}/install-agent.ps1" -OutFile $InstallerPath

# El instalador solicitara el token de forma segura; no lo pongas en este comando.
powershell -ExecutionPolicy Bypass -File $InstallerPath -ServerUrl "${apiOrigin}" -ArtifactBaseUrl "${apiOrigin}" -PackageVersion "${windowsPackageVersion}" -DeviceId "<UUID_DEL_DISPOSITIVO>" -PublicKeysJson '${publicKeysPlaceholder}' -ExpectedSha256 "${windowsPackageSha256}"${allowInsecurePowerShell}`;

  const linuxScript = `# Ubuntu / Debian / Linux (configura servicio systemd automatico):
PUBLIC_KEYS_JSON='${publicKeysPlaceholder}'
curl -sSL ${apiOrigin}/install-agent.sh | sudo bash -s -- "${apiOrigin}" "<UUID_DEL_DISPOSITIVO>" "<TOKEN_DEL_DISPOSITIVO>" "$PUBLIC_KEYS_JSON" "${apiOrigin}" "${allowInsecureLinux}"`;

  const activeScript = platform === "windows" ? windowsScript : linuxScript;

  const handleCopy = () => {
    navigator.clipboard.writeText(activeScript);
    setCopied(true);
    success("Comando copiado", "El comando de instalación fue copiado al portapapeles.");
    setTimeout(() => setCopied(false), 3000);
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Instalador del Agente de Monitoreo"
      maxWidth="650px"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", lineHeight: 1.5 }}>
          Prepara la instalación del agente en plataformas objetivo. Reemplaza el UUID y las claves públicas; la versión y el hash del paquete están fijados, y el token se solicita de forma segura durante la instalación.
        </p>

        {/* Platform Selector */}
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button
            onClick={() => setPlatform("windows")}
            style={{
              flex: 1,
              padding: "0.75rem",
              borderRadius: "var(--radius-md)",
              border: platform === "windows" ? "2px solid var(--brand-primary)" : "1px solid var(--border-subtle)",
              backgroundColor: platform === "windows" ? "var(--bg-surface-elevated)" : "var(--bg-surface)",
              color: platform === "windows" ? "var(--text-primary)" : "var(--text-muted)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "0.5rem",
              fontWeight: 600,
              fontSize: "var(--text-sm)",
            }}
          >
            <Cpu size={16} color={platform === "windows" ? "var(--brand-primary)" : "currentColor"} />
            <span>Windows (PowerShell)</span>
          </button>

          <button
            onClick={() => setPlatform("linux")}
            style={{
              flex: 1,
              padding: "0.75rem",
              borderRadius: "var(--radius-md)",
              border: platform === "linux" ? "2px solid var(--brand-primary)" : "1px solid var(--border-subtle)",
              backgroundColor: platform === "linux" ? "var(--bg-surface-elevated)" : "var(--bg-surface)",
              color: platform === "linux" ? "var(--text-primary)" : "var(--text-muted)",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "0.5rem",
              fontWeight: 600,
              fontSize: "var(--text-sm)",
            }}
          >
            <Terminal size={16} color={platform === "linux" ? "var(--brand-primary)" : "currentColor"} />
            <span>Linux & WSL 2 (Bash)</span>
          </button>
        </div>

        {/* Script Code Block with Copy Button */}
        <div
          style={{
            position: "relative",
            backgroundColor: "#0d1117",
            borderRadius: "var(--radius-md)",
            border: "1px solid var(--border-subtle)",
            padding: "1rem",
          }}
        >
          <pre
            style={{
              margin: 0,
              color: "#58a6ff",
              fontSize: "var(--text-xs)",
              fontFamily: "var(--font-mono)",
              lineHeight: 1.5,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {activeScript}
          </pre>

          <div style={{ position: "absolute", top: "0.5rem", right: "0.5rem" }}>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleCopy}
              leftIcon={copied ? <Check size={14} color="var(--status-healthy)" /> : <Copy size={14} />}
            >
              {copied ? "¡Copiado!" : "Copiar"}
            </Button>
          </div>
        </div>

        {/* Security & Feature Badges */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", padding: "0.75rem", backgroundColor: "var(--bg-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-2xs)", color: "var(--text-secondary)" }}>
            <Shield size={12} color="var(--status-healthy)" />
            <span>HTTPS obligatorio fuera de desarrollo local</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-2xs)", color: "var(--text-secondary)" }}>
            <HardDrive size={12} color="var(--brand-primary)" />
            <span>Buffer offline seguro en SQLite WAL</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-2xs)", color: "var(--text-secondary)" }}>
            <Cpu size={12} color="var(--brand-secondary)" />
            <span>Sin credenciales humanas en el agente</span>
          </div>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Button variant="secondary" onClick={onClose}>
            Cerrar
          </Button>
        </div>
      </div>
    </Modal>
  );
}
