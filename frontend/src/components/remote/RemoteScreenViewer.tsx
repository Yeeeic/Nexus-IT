import { useState, useRef } from "react";
import { Button } from "@/components/common/Button";
import { useNotification } from "@/context/NotificationContext";
import {
  Monitor,
  Play,
  Pause,
  Camera,
  Maximize2,
  Minimize2,
  Shield,
  MousePointer,
} from "lucide-react";

export interface RemoteScreenViewerProps {
  deviceId: string;
  hostname: string;
  isOnline: boolean;
}

export function RemoteScreenViewer({ deviceId, hostname, isOnline }: RemoteScreenViewerProps) {
  const [isStreaming, setIsStreaming] = useState(true);
  const [resolution, setResolution] = useState<"1080p" | "720p" | "480p">("1080p");
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [inputControlEnabled, setInputControlEnabled] = useState(false);
  const [screenshotCount, setScreenshotCount] = useState(0);

  const containerRef = useRef<HTMLDivElement>(null);
  const { success, info } = useNotification();

  const handleTakeScreenshot = () => {
    setScreenshotCount((c) => c + 1);
    success(
      "Captura simulada",
      `Vista previa #${screenshotCount + 1} de ${hostname}. No se guardó ni se capturó una pantalla real.`
    );
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!isFullscreen) {
      if (containerRef.current.requestFullscreen) {
        containerRef.current.requestFullscreen();
      }
      setIsFullscreen(true);
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
      setIsFullscreen(false);
    }
  };

  if (!isOnline) {
    return (
      <div
        className="nexus-card"
        style={{
          padding: "3rem 1.5rem",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          textAlign: "center",
          gap: "1rem",
          backgroundColor: "#050505",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-lg)",
        }}
      >
        <div
          style={{
            width: "56px",
            height: "56px",
            borderRadius: "var(--radius-full)",
            backgroundColor: "rgba(255,255,255,0.05)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "var(--text-muted)",
          }}
        >
          <Monitor size={28} />
        </div>
        <div>
          <h3 style={{ fontSize: "var(--text-base)", fontWeight: 600 }}>Dispositivo Fuera de Línea</h3>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem", maxWidth: "420px" }}>
            <strong>{hostname}</strong> está desconectado. Esta sección es una vista previa visual y no ofrece acceso remoto real.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: "0.75rem",
        backgroundColor: "#080b11",
        borderRadius: "var(--radius-xl)",
        padding: "1rem",
        border: "1px solid rgba(255, 255, 255, 0.08)",
        boxShadow: "0 20px 40px -15px rgba(0,0,0,0.7)",
      }}
    >
      {/* Top Remote Control Header & Telemetry Bar */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: "0.75rem",
          paddingBottom: "0.75rem",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <Monitor size={18} color="var(--brand-primary)" />
            <span style={{ fontSize: "var(--text-sm)", fontWeight: 700 }}>
              Vista previa de pantalla: {hostname}
            </span>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.375rem",
              padding: "0.2rem 0.5rem",
              borderRadius: "var(--radius-full)",
              backgroundColor: isStreaming ? "rgba(16, 185, 129, 0.1)" : "rgba(255,255,255,0.05)",
              border: isStreaming ? "1px solid rgba(16, 185, 129, 0.3)" : "1px solid rgba(255,255,255,0.1)",
              fontSize: "var(--text-2xs)",
              color: isStreaming ? "var(--status-healthy)" : "var(--text-muted)",
            }}
          >
            <span className={isStreaming ? "status-dot healthy pulse" : "status-dot offline"} style={{ width: "6px", height: "6px" }} />
            <span>{isStreaming ? "Demo animada" : "Demo pausada"}</span>
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.375rem",
              fontSize: "var(--text-2xs)",
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
            }}
          >
            <span>Datos simulados</span>
            <span>•</span>
            <span>Sin conexión remota</span>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap" }}>
          {/* Quality selector */}
          <select
            value={resolution}
            onChange={(e) => setResolution(e.target.value as any)}
            style={{
              padding: "0.25rem 0.5rem",
              fontSize: "var(--text-xs)",
              backgroundColor: "#131823",
              color: "var(--text-primary)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "var(--radius-sm)",
              cursor: "pointer",
            }}
          >
            <option value="1080p">1080p (FHD)</option>
            <option value="720p">720p (HD)</option>
            <option value="480p">480p (Ahorro)</option>
          </select>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setIsStreaming(!isStreaming)}
            leftIcon={isStreaming ? <Pause size={14} /> : <Play size={14} />}
          >
            {isStreaming ? "Pausar demo" : "Reanudar demo"}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={handleTakeScreenshot}
            leftIcon={<Camera size={14} />}
            title="Simular una captura en la vista previa"
          >
            Captura
          </Button>

          <Button
            variant={inputControlEnabled ? "primary" : "secondary"}
            size="sm"
            onClick={() => {
              setInputControlEnabled(!inputControlEnabled);
              if (!inputControlEnabled) {
                info("Interacción simulada", "Este control solo cambia la demostración; no envía teclado ni ratón al equipo.");
              }
            }}
            leftIcon={<MousePointer size={14} />}
            title="Alternar el modo interactivo de la demostración"
          >
            {inputControlEnabled ? "Demo interactiva" : "Demo observador"}
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={toggleFullscreen}
            leftIcon={isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
            title="Pantalla Completa"
          />
        </div>
      </div>

      {/* Screen Canvas Container with Double-Bezel Hardware Frame */}
      <div
        style={{
          position: "relative",
          width: "100%",
          minHeight: "440px",
          backgroundColor: "#030407",
          borderRadius: "var(--radius-lg)",
          overflow: "hidden",
          border: "1px solid rgba(255, 255, 255, 0.05)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {/* Simulated Remote Screen Wallpaper & Interactive Desktop Preview */}
        <div
          style={{
            position: "absolute",
            inset: 0,
            background: "radial-gradient(ellipse at center, #111d33 0%, #060911 100%)",
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            padding: "1.5rem",
          }}
        >
          {/* Top Info Bar on Remote Desktop */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
            <div
              style={{
                backgroundColor: "rgba(0,0,0,0.6)",
                backdropFilter: "blur(8px)",
                padding: "0.5rem 0.75rem",
                borderRadius: "var(--radius-md)",
                border: "1px solid rgba(255,255,255,0.1)",
                color: "#e2e8f0",
              }}
            >
              <div style={{ fontSize: "var(--text-xs)", fontWeight: 700 }}>{hostname}</div>
              <div style={{ fontSize: "var(--text-2xs)", color: "var(--brand-primary)", marginTop: "2px" }}>
                Prototipo NEXUS IT • Resolución visual: {resolution}
              </div>
            </div>

            <div
              style={{
                backgroundColor: "rgba(0,0,0,0.6)",
                backdropFilter: "blur(8px)",
                padding: "0.375rem 0.625rem",
                borderRadius: "var(--radius-md)",
                border: "1px solid rgba(255,255,255,0.1)",
                fontSize: "var(--text-2xs)",
                fontFamily: "var(--font-mono)",
                color: "var(--text-secondary)",
              }}
            >
              VISTA PREVIA LOCAL • SIN WEBRTC
            </div>
          </div>

          {/* Center Graphic */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.75rem", opacity: 0.85 }}>
            <div
              style={{
                width: "64px",
                height: "64px",
                borderRadius: "var(--radius-xl)",
                backgroundColor: "rgba(59, 130, 246, 0.15)",
                border: "1px solid rgba(59, 130, 246, 0.4)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--brand-primary)",
              }}
            >
              <Monitor size={32} />
            </div>
            <div style={{ textAlign: "center" }}>
              <div style={{ fontSize: "var(--text-sm)", fontWeight: 600, color: "#fff" }}>
                Demostración de escritorio remoto
              </div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", marginTop: "0.25rem" }}>
                {inputControlEnabled
                  ? "Modo interactivo simulado: ningún evento sale del navegador"
                  : "Modo observador simulado: no existe transmisión de pantalla"}
              </div>
            </div>
          </div>

          {/* Remote Taskbar Mockup */}
          <div
            style={{
              backgroundColor: "rgba(10, 15, 25, 0.8)",
              backdropFilter: "blur(12px)",
              borderRadius: "var(--radius-md)",
              padding: "0.5rem 1rem",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              border: "1px solid rgba(255,255,255,0.08)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
              <div style={{ width: "12px", height: "12px", backgroundColor: "var(--brand-primary)", borderRadius: "2px" }} />
              <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>NEXUS IT UI Prototype</span>
              <span style={{ fontSize: "var(--text-2xs)", color: "var(--status-healthy)", backgroundColor: "rgba(16,185,129,0.1)", padding: "1px 6px", borderRadius: "4px" }}>
                DEMO
              </span>
            </div>
            <div style={{ fontSize: "var(--text-2xs)", fontFamily: "var(--font-mono)", color: "var(--text-muted)" }}>
              {new Date().toLocaleTimeString()}
            </div>
          </div>
        </div>
      </div>

      {/* Footer Security Badge */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "var(--text-2xs)", color: "var(--text-muted)", padding: "0 0.25rem" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "0.375rem" }}>
          <Shield size={12} color="var(--status-healthy)" />
          <span>Prototipo local: no transmite, no controla y no guarda capturas reales</span>
        </div>
        <span>Dispositivo de referencia: {deviceId.substring(0, 12)}...</span>
      </div>
    </div>
  );
}
