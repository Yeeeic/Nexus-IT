import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Building2, ChevronDown, Check } from "lucide-react";

export function TenantSelector() {
  const { user, availableOrganizations, selectOrganization } = useAuth();
  const [isOpen, setIsOpen] = useState(false);

  if (!user || availableOrganizations.length <= 1) {
    const currentOrg = availableOrganizations.find((o) => o.organization_id === user?.organization_id);
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.375rem 0.75rem",
          backgroundColor: "var(--bg-surface-elevated)",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-md)",
          fontSize: "var(--text-xs)",
          color: "var(--text-primary)",
          fontWeight: 500,
        }}
      >
        <Building2 size={14} color="var(--brand-primary)" />
        <span>{currentOrg ? currentOrg.organization_name : "Organización Única"}</span>
      </div>
    );
  }

  const currentOrg = availableOrganizations.find((o) => o.organization_id === user.organization_id);

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.375rem 0.75rem",
          backgroundColor: "var(--bg-surface-elevated)",
          border: "1px solid var(--border-default)",
          borderRadius: "var(--radius-md)",
          fontSize: "var(--text-xs)",
          color: "var(--text-primary)",
          fontWeight: 500,
          cursor: "pointer",
          transition: "all var(--transition-fast)",
        }}
      >
        <Building2 size={14} color="var(--brand-primary)" />
        <span>{currentOrg ? currentOrg.organization_name : "Seleccionar Organización"}</span>
        <ChevronDown size={14} color="var(--text-muted)" />
      </button>

      {isOpen && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: "var(--z-header)" }}
            onClick={() => setIsOpen(false)}
          />
          <div
            role="listbox"
            className="nexus-card nexus-card-elevated"
            style={{
              position: "absolute",
              top: "calc(100% + 4px)",
              left: 0,
              minWidth: "220px",
              zIndex: "var(--z-header)",
              padding: "0.25rem",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div
              style={{
                padding: "0.375rem 0.5rem",
                fontSize: "var(--text-2xs)",
                fontWeight: 600,
                color: "var(--text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              Organizaciones Autorizadas
            </div>
            {availableOrganizations.map((org) => {
              const isSelected = org.organization_id === user.organization_id;
              return (
                <button
                  key={org.organization_id}
                  role="option"
                  aria-selected={isSelected}
                  onClick={async () => {
                    setIsOpen(false);
                    if (!isSelected) {
                      await selectOrganization(org.organization_id);
                    }
                  }}
                  style={{
                    width: "100%",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "0.5rem 0.75rem",
                    borderRadius: "var(--radius-sm)",
                    background: isSelected ? "var(--brand-glow)" : "transparent",
                    color: isSelected ? "var(--brand-primary)" : "var(--text-primary)",
                    border: "none",
                    fontSize: "var(--text-xs)",
                    fontWeight: isSelected ? 600 : 400,
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <span>{org.organization_name}</span>
                  {isSelected && <Check size={14} />}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
