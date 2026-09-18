import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/common/Button";
import { Building2, ArrowRight, ShieldCheck } from "lucide-react";

export function OrgSelectView() {
  const { availableOrganizations, selectOrganization, logout } = useAuth();
  const [selectedId, setSelectedId] = useState<string>(
    availableOrganizations[0]?.organization_id || ""
  );
  const [isLoading, setIsLoading] = useState(false);

  const handleSelect = async () => {
    if (!selectedId) return;
    setIsLoading(true);
    try {
      await selectOrganization(selectedId);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: "var(--bg-app)",
        padding: "1.5rem",
      }}
    >
      <div
        className="nexus-card nexus-card-elevated"
        style={{
          width: "100%",
          maxWidth: "460px",
          padding: "2.5rem 2rem",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div
            style={{
              width: "48px",
              height: "48px",
              margin: "0 auto 1rem",
              borderRadius: "var(--radius-lg)",
              background: "linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-secondary) 100%)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#ffffff",
              boxShadow: "var(--shadow-glow-cyan)",
            }}
          >
            <ShieldCheck size={28} />
          </div>
          <h1 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>
            Seleccione una Organización
          </h1>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Su cuenta tiene membresías activas en múltiples empresas
          </p>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "1.75rem" }}>
          {availableOrganizations.map((org) => {
            const isSelected = selectedId === org.organization_id;
            return (
              <button
                key={org.organization_id}
                type="button"
                onClick={() => setSelectedId(org.organization_id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  padding: "1rem 1.25rem",
                  borderRadius: "var(--radius-md)",
                  border: `1px solid ${isSelected ? "var(--brand-primary)" : "var(--border-default)"}`,
                  backgroundColor: isSelected ? "var(--brand-glow)" : "var(--bg-surface-elevated)",
                  color: isSelected ? "var(--brand-primary)" : "var(--text-primary)",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "all var(--transition-fast)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
                  <Building2 size={18} color={isSelected ? "var(--brand-primary)" : "var(--text-muted)"} />
                  <div>
                    <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>
                      {org.organization_name}
                    </div>
                    <div style={{ fontSize: "var(--text-2xs)", color: "var(--text-muted)", fontFamily: "var(--font-mono)" }}>
                      Slug: {org.slug}
                    </div>
                  </div>
                </div>
                {isSelected && <ArrowRight size={16} />}
              </button>
            );
          })}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <Button
            variant="primary"
            size="lg"
            isLoading={isLoading}
            disabled={!selectedId}
            onClick={handleSelect}
            style={{ width: "100%" }}
          >
            Acceder a la Consola
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={logout}
            style={{ width: "100%", color: "var(--text-muted)" }}
          >
            Cerrar Sesión
          </Button>
        </div>
      </div>
    </div>
  );
}
