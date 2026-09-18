import { TenantSelector } from "./TenantSelector";
import { UserMenu } from "./UserMenu";
import { useTheme } from "@/context/ThemeContext";
import type { WebSocketStatus } from "@/realtime/useWebSocket";
import { Sun, Moon, Radio } from "lucide-react";

export interface HeaderProps {
  currentTabName: string;
  wsStatus: WebSocketStatus;
  isStreamPaused?: boolean;
  onToggleStream?: () => void;
}

export function Header({ currentTabName, wsStatus, isStreamPaused, onToggleStream }: HeaderProps) {
  const { theme, toggleTheme } = useTheme();

  const getWsIndicator = () => {
    if (isStreamPaused) {
      return { color: "var(--status-warning)", label: "Stream pausado (Clic para reanudar)" };
    }
    switch (wsStatus) {
      case "CONNECTED":
        return { color: "var(--status-healthy)", label: "Tiempo real activo (Clic para pausar)" };
      case "CONNECTING":
        return { color: "var(--status-warning)", label: "Conectando stream..." };
      case "DISCONNECTED":
        return { color: "var(--status-offline)", label: "Stream desconectado (Clic para reconectar)" };
      case "ERROR":
        return { color: "var(--status-critical)", label: "Error en tiempo real (Clic para reintentar)" };
    }
  };

  const wsInfo = getWsIndicator();

  return (
    <header
      style={{
        height: "64px",
        backgroundColor: "var(--bg-app)",
        borderBottom: "1px solid var(--border-subtle)",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "0 var(--space-8)",
        zIndex: "var(--z-header)",
      }}
    >
      {/* Title / Section name */}
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <h1 style={{ fontSize: "var(--text-lg)", fontWeight: 600 }}>{currentTabName}</h1>
      </div>

      {/* Right controls: Tenant, WS Pulse, Theme, User */}
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        {/* Real-time WebSocket toggle indicator */}
        <button
          onClick={onToggleStream}
          title={wsInfo.label}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.375rem",
            padding: "0.25rem 0.625rem",
            backgroundColor: "var(--bg-surface-elevated)",
            borderRadius: "var(--radius-full)",
            border: isStreamPaused ? "1px dashed var(--status-warning)" : "1px solid var(--border-subtle)",
            fontSize: "var(--text-2xs)",
            color: "var(--text-secondary)",
            cursor: onToggleStream ? "pointer" : "default",
            transition: "all var(--transition-fast)",
          }}
        >
          <span
            className={wsStatus === "CONNECTED" && !isStreamPaused ? "status-dot healthy pulse" : "status-dot offline"}
            style={{ width: "6px", height: "6px" }}
          />
          <Radio size={12} color={wsInfo.color} />
          <span style={{ display: "inline-block", maxWidth: "140px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontWeight: 500 }}>
            {isStreamPaused ? "Pausado" : wsStatus === "CONNECTED" ? "En vivo" : wsStatus}
          </span>
        </button>

        {/* Tenant Selector */}
        <TenantSelector />

        {/* Theme Toggle */}
        <button
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Cambiar a tema claro" : "Cambiar a tema oscuro"}
          style={{
            background: "transparent",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-md)",
            padding: "0.5rem",
            color: "var(--text-muted)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>

        {/* User Menu */}
        <UserMenu />
      </div>
    </header>
  );
}
