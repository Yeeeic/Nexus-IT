import { useState } from "react";
import { UsersAdminView } from "./UsersAdminView";
import { RolesAdminView } from "./RolesAdminView";
import { AuditLogsView } from "./AuditLogsView";
import { Tabs } from "@/components/common/Tabs";
import { Users, Shield, FileText } from "lucide-react";

export function AdminView() {
  const [activeTab, setActiveTab] = useState("users");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
      <div>
        <h2 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>Administración & Seguridad</h2>
        <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
          Control de acceso basado en roles (RBAC), miembros de la empresa y auditoría inmutable
        </p>
      </div>

      <Tabs
        activeTab={activeTab}
        onChange={setActiveTab}
        tabs={[
          { id: "users", label: "Usuarios y Miembros", icon: <Users size={16} /> },
          { id: "roles", label: "Roles y Permisos", icon: <Shield size={16} /> },
          { id: "audit", label: "Registro de Auditoría", icon: <FileText size={16} /> },
        ]}
      />

      {activeTab === "users" && <UsersAdminView />}
      {activeTab === "roles" && <RolesAdminView />}
      {activeTab === "audit" && <AuditLogsView />}
    </div>
  );
}
