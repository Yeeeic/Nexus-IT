import React, { useState, useCallback } from "react";
import { Sidebar, type NavigationTab } from "./Sidebar";
import { Header } from "./Header";
import { ErrorBoundary } from "../common/ErrorBoundary";
import { useWebSocket, type RealtimeEvent } from "@/realtime/useWebSocket";
import { useNotification } from "@/context/NotificationContext";
import { AutoRemediationPromptModal, type PendingRemediation } from "../remediation/AutoRemediationPromptModal";

export interface AppShellProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  children: React.ReactNode;
}

export function AppShell({ currentTab, onSelectTab, children }: AppShellProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [pendingRemediation, setPendingRemediation] = useState<PendingRemediation | null>(null);
  const { info, warning, error: notifyError } = useNotification();

  // Listen to global WebSocket events (alerts, device status, high disk trigger)
  const handleRealtimeEvent = useCallback((event: RealtimeEvent) => {
    if (event.type === "alert") {
      const alert = event as any;
      if (alert.severity === "CRITICAL") {
        notifyError(`Alerta Crítica: ${alert.message || "Incidente detectado"}`, `Dispositivo: ${alert.device_id}`);
        // If alert is about storage/disk > 95%, trigger auto-remediation prompt
        if (alert.message?.toLowerCase().includes("disk") || alert.message?.toLowerCase().includes("disco")) {
          setPendingRemediation({
            deviceId: alert.device_id,
            hostname: alert.hostname || "Dispositivo Remoto",
            diskPercent: 96.5,
            message: alert.message,
          });
        }
      } else {
        warning(`Alerta: ${alert.message || "Incidente detectado"}`, `Dispositivo: ${alert.device_id}`);
      }
    } else if (event.type === "device_status") {
      const dev = event as any;
      info(`Estado de equipo actualizado`, `${dev.hostname || "Dispositivo"}: ${dev.status}`);
    }
  }, [notifyError, warning, info]);

  const { status: wsStatus, isManualPaused, toggleConnection } = useWebSocket({
    enabled: true,
    onEvent: handleRealtimeEvent,
  });

  const getTabTitle = (): string => {
    switch (currentTab) {
      case "dashboard":
        return "Panel Operativo de Infraestructura";
      case "devices":
        return "Inventario & Monitoreo de Dispositivos";
      case "portal":
        return "Portal de Autoservicio & Soporte";
      case "alerts":
        return "Centro de Alertas & Umbrales";
      case "tickets":
        return "Mesa de Ayuda & Soporte Técnico";
      case "actions":
        return "Consola de Acciones Remotas";
      case "dlq":
        return "Monitor de Cola DLQ";
      case "admin":
        return "Administración & Auditoría";
    }
  };

  return (
    <div className="app-container">
      <Sidebar
        currentTab={currentTab}
        onSelectTab={onSelectTab}
        isCollapsed={isCollapsed}
        onToggleCollapse={() => setIsCollapsed(!isCollapsed)}
      />
      <div className="main-content">
        <Header
          currentTabName={getTabTitle()}
          wsStatus={wsStatus}
          isStreamPaused={isManualPaused}
          onToggleStream={toggleConnection}
        />
        <main className="page-wrapper" role="main">
          <ErrorBoundary fallbackTitle={`Error en ${getTabTitle()}`}>
            {children}
          </ErrorBoundary>
        </main>
      </div>

      <AutoRemediationPromptModal
        remediation={pendingRemediation}
        onClose={() => setPendingRemediation(null)}
      />
    </div>
  );
}
