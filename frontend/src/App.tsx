import { useState, useEffect } from "react";
import { useAuth } from "./context/AuthContext";
import { AppShell } from "./components/layout/AppShell";
import type { NavigationTab } from "./components/layout/Sidebar";
import { LoginView } from "./views/auth/LoginView";
import { OrgSelectView } from "./views/auth/OrgSelectView";
import { PasswordResetView } from "./views/auth/PasswordResetView";
import { DashboardView } from "./views/dashboard/DashboardView";
import { DevicesListView } from "./views/devices/DevicesListView";
import { AlertsView } from "./views/alerts/AlertsView";
import { TicketsListView } from "./views/tickets/TicketsListView";
import { ActionsConsoleView } from "./views/actions/ActionsConsoleView";
import { DlqMonitorView } from "./views/dlq/DlqMonitorView";
import { AdminView } from "./views/admin/AdminView";
import { ClientPortalView } from "./views/portal/ClientPortalView";
import { ShieldCheck } from "lucide-react";

export function App() {
  const { isLoading, isAuthenticated, requiresOrgSelection, hasPermission } = useAuth();
  const [currentTab, setCurrentTab] = useState<NavigationTab>("dashboard");
  const [isResetPassword, setIsResetPassword] = useState(false);

  const isClientOnly = isAuthenticated && !hasPermission("devices:read_all");
  const effectiveTab =
    isClientOnly &&
    (currentTab === "dashboard" ||
      currentTab === "devices" ||
      currentTab === "alerts" ||
      currentTab === "actions" ||
      currentTab === "dlq" ||
      currentTab === "admin")
      ? "portal"
      : currentTab;

  useEffect(() => {
    if (isClientOnly && currentTab !== effectiveTab) {
      setCurrentTab(effectiveTab);
    }
  }, [isClientOnly, currentTab, effectiveTab]);

  // 1. Initial Authentication Loading State
  if (isLoading) {
    return (
      <div
        style={{
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "var(--bg-app)",
          gap: "1rem",
        }}
      >
        <div
          style={{
            width: "48px",
            height: "48px",
            borderRadius: "var(--radius-lg)",
            background: "linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#ffffff",
            boxShadow: "var(--shadow-glow-cyan)",
            animation: "pulse-glow 1.5s infinite ease-in-out",
          }}
        >
          <ShieldCheck size={28} />
        </div>
        <div style={{ fontSize: "var(--text-sm)", color: "var(--text-secondary)", fontWeight: 500 }}>
          Verificando sesión segura...
        </div>
      </div>
    );
  }

  // 2. Organization Selection View (Multi-Tenant Login Context)
  if (requiresOrgSelection) {
    return <OrgSelectView />;
  }

  // 3. Password Reset View
  if (isResetPassword) {
    return <PasswordResetView onBackToLogin={() => setIsResetPassword(false)} />;
  }

  // 4. Login View (Unauthenticated)
  if (!isAuthenticated) {
    return <LoginView onForgotPassword={() => setIsResetPassword(true)} />;
  }

  // 5. Authenticated Operational Application
  return (
    <AppShell currentTab={effectiveTab} onSelectTab={setCurrentTab}>
      {effectiveTab === "dashboard" && <DashboardView onNavigate={setCurrentTab} />}
      {effectiveTab === "devices" && <DevicesListView />}
      {effectiveTab === "portal" && <ClientPortalView />}
      {effectiveTab === "alerts" && <AlertsView />}
      {effectiveTab === "tickets" && <TicketsListView />}
      {effectiveTab === "actions" && <ActionsConsoleView />}
      {effectiveTab === "dlq" && <DlqMonitorView />}
      {effectiveTab === "admin" && <AdminView />}
    </AppShell>
  );
}

export default App;
