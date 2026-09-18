import {
  LayoutDashboard,
  Server,
  AlertOctagon,
  LifeBuoy,
  Terminal,
  Database,
  Users,
  ShieldCheck,
  ChevronLeft,
  ChevronRight,
  Headphones,
} from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export type NavigationTab =
  | "dashboard"
  | "devices"
  | "portal"
  | "alerts"
  | "tickets"
  | "actions"
  | "dlq"
  | "admin";

export interface SidebarProps {
  currentTab: NavigationTab;
  onSelectTab: (tab: NavigationTab) => void;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({
  currentTab,
  onSelectTab,
  isCollapsed,
  onToggleCollapse,
}: SidebarProps) {
  const { hasPermission } = useAuth();
  const isTechnicianOrAdmin = hasPermission("devices:read_all");

  const navItems: Array<{
    id: NavigationTab;
    label: string;
    icon: React.ReactNode;
    permission?: string;
    requiresTech?: boolean;
  }> = [
    {
      id: "dashboard",
      label: "Dashboard",
      icon: <LayoutDashboard size={18} />,
      requiresTech: true,
    },
    {
      id: "devices",
      label: "Dispositivos",
      icon: <Server size={18} />,
      requiresTech: true,
    },
    {
      id: "portal",
      label: "Portal de Usuario",
      icon: <Headphones size={18} />,
    },
    {
      id: "alerts",
      label: "Alertas & Reglas",
      icon: <AlertOctagon size={18} />,
      requiresTech: true,
    },
    {
      id: "tickets",
      label: "Mesa de Ayuda",
      icon: <LifeBuoy size={18} />,
    },
    {
      id: "actions",
      label: "Acciones Remotas",
      icon: <Terminal size={18} />,
      permission: "actions:request_exec",
      requiresTech: true,
    },
    {
      id: "dlq",
      label: "Monitor DLQ",
      icon: <Database size={18} />,
      permission: "metrics:decide_dlq",
      requiresTech: true,
    },
    {
      id: "admin",
      label: "Administración",
      icon: <Users size={18} />,
      permission: "users:manage",
      requiresTech: true,
    },
  ];

  return (
    <aside
      style={{
        width: isCollapsed ? "68px" : "240px",
        height: "100%",
        backgroundColor: "var(--bg-sidebar)",
        borderRight: "1px solid var(--border-subtle)",
        display: "flex",
        flexDirection: "column",
        transition: "width var(--transition-normal)",
        userSelect: "none",
        zIndex: "var(--z-sticky)",
      }}
    >
      {/* Brand Header */}
      <div
        style={{
          padding: "1.25rem 1rem",
          display: "flex",
          alignItems: "center",
          gap: "0.75rem",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div
          style={{
            width: "32px",
            height: "32px",
            borderRadius: "var(--radius-md)",
            background: "linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#ffffff",
            flexShrink: 0,
            boxShadow: "var(--shadow-glow-cyan)",
          }}
        >
          <ShieldCheck size={20} />
        </div>
        {!isCollapsed && (
          <div style={{ overflow: "hidden", whiteSpace: "nowrap" }}>
            <div style={{ fontWeight: 700, fontSize: "var(--text-base)", letterSpacing: "0.02em", color: "var(--text-primary)" }}>
              NEXUS <span style={{ color: "var(--brand-primary)" }}>IT</span>
            </div>
            <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              Monitoreo & Soporte
            </div>
          </div>
        )}
      </div>

      {/* Navigation List */}
      <nav style={{ flex: 1, padding: "0.75rem 0.5rem", display: "flex", flexDirection: "column", gap: "0.25rem" }}>
        {navItems.map((item) => {
          if (item.requiresTech && !isTechnicianOrAdmin) {
            return null;
          }
          if (item.permission && !hasPermission(item.permission)) {
            return null;
          }
          const isActive = currentTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onSelectTab(item.id)}
              title={isCollapsed ? item.label : undefined}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.75rem",
                padding: "0.625rem 0.75rem",
                borderRadius: "var(--radius-md)",
                backgroundColor: isActive ? "var(--brand-glow)" : "transparent",
                color: isActive ? "var(--brand-primary)" : "var(--text-secondary)",
                border: "none",
                fontSize: "var(--text-sm)",
                fontWeight: isActive ? 600 : 500,
                cursor: "pointer",
                textAlign: "left",
                width: "100%",
                transition: "all var(--transition-fast)",
                justifyContent: isCollapsed ? "center" : "flex-start",
              }}
            >
              <div style={{ flexShrink: 0 }}>{item.icon}</div>
              {!isCollapsed && <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{item.label}</span>}
            </button>
          );
        })}
      </nav>

      {/* Collapse Toggle Footer */}
      <div style={{ padding: "0.75rem", borderTop: "1px solid var(--border-subtle)", display: "flex", justifyContent: isCollapsed ? "center" : "flex-end" }}>
        <button
          onClick={onToggleCollapse}
          aria-label={isCollapsed ? "Expandir barra lateral" : "Colapsar barra lateral"}
          style={{
            background: "transparent",
            border: "1px solid var(--border-subtle)",
            borderRadius: "var(--radius-sm)",
            color: "var(--text-muted)",
            padding: "0.375rem",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          {isCollapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
        </button>
      </div>
    </aside>
  );
}
