import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Modal } from "@/components/common/Modal";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { Shield, Building2, Lock } from "lucide-react";

export interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function UserProfileModal({ isOpen, onClose }: UserProfileModalProps) {
  const { user, logout } = useAuth();
  const [activeTab, setActiveTab] = useState<"profile" | "permissions" | "security">("profile");

  if (!user) return null;

  const currentOrg = user.available_organizations?.find((o) => o.organization_id === user.organization_id);

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Perfil de Usuario & Cuenta"
      maxWidth="600px"
    >
      <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
        {/* User Identity Header Card */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "1rem",
            padding: "1rem",
            backgroundColor: "var(--bg-surface-elevated)",
            borderRadius: "var(--radius-lg)",
            border: "1px solid var(--border-subtle)",
          }}
        >
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "var(--radius-full)",
              backgroundColor: "var(--brand-primary)",
              color: "#fff",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "1.25rem",
              fontWeight: 700,
            }}
          >
            {user.full_name?.charAt(0) || user.email?.charAt(0) || "U"}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ fontSize: "1.125rem", fontWeight: 700 }}>{user.full_name || "Usuario"}</span>
              <Badge variant="healthy" dot>Activo</Badge>
            </div>
            <span style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>{user.email}</span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid var(--border-subtle)", paddingBottom: "0.5rem" }}>
          <button
            onClick={() => setActiveTab("profile")}
            style={{
              padding: "0.375rem 0.75rem",
              fontSize: "var(--text-xs)",
              fontWeight: 600,
              borderRadius: "var(--radius-md)",
              background: activeTab === "profile" ? "var(--bg-surface-elevated)" : "transparent",
              color: activeTab === "profile" ? "var(--text-primary)" : "var(--text-muted)",
              border: activeTab === "profile" ? "1px solid var(--border-subtle)" : "none",
              cursor: "pointer",
            }}
          >
            Información General
          </button>
          <button
            onClick={() => setActiveTab("permissions")}
            style={{
              padding: "0.375rem 0.75rem",
              fontSize: "var(--text-xs)",
              fontWeight: 600,
              borderRadius: "var(--radius-md)",
              background: activeTab === "permissions" ? "var(--bg-surface-elevated)" : "transparent",
              color: activeTab === "permissions" ? "var(--text-primary)" : "var(--text-muted)",
              border: activeTab === "permissions" ? "1px solid var(--border-subtle)" : "none",
              cursor: "pointer",
            }}
          >
            Permisos ({user.permissions?.length || 0})
          </button>
          <button
            onClick={() => setActiveTab("security")}
            style={{
              padding: "0.375rem 0.75rem",
              fontSize: "var(--text-xs)",
              fontWeight: 600,
              borderRadius: "var(--radius-md)",
              background: activeTab === "security" ? "var(--bg-surface-elevated)" : "transparent",
              color: activeTab === "security" ? "var(--text-primary)" : "var(--text-muted)",
              border: activeTab === "security" ? "1px solid var(--border-subtle)" : "none",
              cursor: "pointer",
            }}
          >
            Seguridad & Sesión
          </button>
        </div>

        {/* Tab Contents */}
        {activeTab === "profile" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem" }}>
              <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                  <Building2 size={12} />
                  <span>ORGANIZACIÓN</span>
                </div>
                <div style={{ marginTop: "0.25rem", fontWeight: 600, fontSize: "var(--text-sm)" }}>
                  {currentOrg?.organization_name || "Sin organización"}
                </div>
              </div>

              <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", color: "var(--text-muted)", fontSize: "var(--text-2xs)" }}>
                  <Shield size={12} />
                  <span>NIVEL DE PRIVILEGIO</span>
                </div>
                <div style={{ marginTop: "0.25rem", fontWeight: 600, fontSize: "var(--text-sm)" }}>
                  {user.permissions?.includes("users:manage") ? "Administrador de Sistema" : "Técnico Operador"}
                </div>
              </div>
            </div>

            <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)" }}>IDENTIFICADOR ÚNICO DE USUARIO (UUID)</div>
              <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
                {user.user_id}
              </div>
            </div>
          </div>
        )}

        {activeTab === "permissions" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)" }}>
              Permisos RBAC asignados mediante control de acceso multiempresa:
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.375rem", maxHeight: "180px", overflowY: "auto", padding: "0.25rem" }}>
              {user.permissions?.map((perm) => (
                <span
                  key={perm}
                  style={{
                    padding: "0.2rem 0.5rem",
                    fontSize: "var(--text-2xs)",
                    fontFamily: "var(--font-mono)",
                    backgroundColor: "var(--bg-surface-elevated)",
                    border: "1px solid var(--border-subtle)",
                    borderRadius: "var(--radius-sm)",
                    color: "var(--brand-primary)",
                  }}
                >
                  ✓ {perm}
                </span>
              ))}
            </div>
          </div>
        )}

        {activeTab === "security" && (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            <div style={{ padding: "0.75rem", backgroundColor: "var(--bg-surface)", borderRadius: "var(--radius-md)", border: "1px solid var(--border-subtle)" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontWeight: 600, fontSize: "var(--text-sm)" }}>
                <Lock size={14} color="var(--status-healthy)" />
                <span>Sesión Segura Activa</span>
              </div>
              <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
                Autenticada con Cookie <code>__Host-nexus_session</code> (HttpOnly, SameSite=Lax, Secure) y protección anti-CSRF sincronizada.
              </p>
            </div>

            <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem", marginTop: "0.5rem" }}>
              <Button variant="danger" size="sm" onClick={() => { onClose(); logout(); }}>
                Cerrar Sesión Global
              </Button>
            </div>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", marginTop: "0.5rem" }}>
          <Button variant="secondary" onClick={onClose}>
            Cerrar
          </Button>
        </div>
      </div>
    </Modal>
  );
}
