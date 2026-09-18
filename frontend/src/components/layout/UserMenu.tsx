import { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { User, LogOut, Shield } from "lucide-react";
import { UserProfileModal } from "./UserProfileModal";

export function UserMenu() {
  const { user, logout } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [isLoggingOut, setIsLoggingOut] = useState(false);

  if (!user) return null;

  const handleLogout = async () => {
    setIsLoggingOut(true);
    try {
      await logout();
    } finally {
      setIsLoggingOut(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        aria-haspopup="menu"
        aria-expanded={isOpen}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.25rem 0.5rem",
          background: "transparent",
          border: "1px solid var(--border-subtle)",
          borderRadius: "var(--radius-full)",
          color: "var(--text-primary)",
          cursor: "pointer",
          transition: "all var(--transition-fast)",
        }}
      >
        <div
          style={{
            width: "28px",
            height: "28px",
            borderRadius: "var(--radius-full)",
            backgroundColor: "var(--bg-surface-elevated)",
            color: "var(--brand-primary)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 600,
            fontSize: "var(--text-xs)",
          }}
        >
          {user.full_name ? user.full_name.charAt(0).toUpperCase() : <User size={14} />}
        </div>
        <span style={{ fontSize: "var(--text-xs)", fontWeight: 500, paddingRight: "0.25rem" }}>
          {user.full_name || user.email}
        </span>
      </button>

      {isOpen && (
        <>
          <div
            style={{ position: "fixed", inset: 0, zIndex: "var(--z-header)" }}
            onClick={() => setIsOpen(false)}
          />
          <div
            role="menu"
            className="nexus-card nexus-card-elevated"
            style={{
              position: "absolute",
              top: "calc(100% + 6px)",
              right: 0,
              minWidth: "240px",
              zIndex: "var(--z-header)",
              padding: "0.75rem",
              boxShadow: "var(--shadow-lg)",
            }}
          >
            <div style={{ paddingBottom: "0.5rem", marginBottom: "0.5rem", borderBottom: "1px solid var(--border-subtle)" }}>
              <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{user.full_name}</div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--text-muted)", fontFamily: "var(--font-mono)", marginTop: "2px" }}>
                {user.email}
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: "0.375rem", fontSize: "var(--text-2xs)", color: "var(--text-secondary)", marginBottom: "0.75rem" }}>
              <Shield size={12} color="var(--brand-primary)" />
              <span>{user.permissions.length} Permisos activos</span>
            </div>

            <button
              onClick={() => {
                setIsOpen(false);
                setIsProfileOpen(true);
              }}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.5rem 0.75rem",
                borderRadius: "var(--radius-sm)",
                background: "transparent",
                border: "none",
                color: "var(--text-primary)",
                fontSize: "var(--text-xs)",
                fontWeight: 500,
                cursor: "pointer",
                textAlign: "left",
                marginBottom: "0.25rem",
              }}
            >
              <User size={14} color="var(--brand-primary)" />
              <span>Mi Perfil & Cuenta</span>
            </button>

            <button
              onClick={handleLogout}
              disabled={isLoggingOut}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.5rem 0.75rem",
                borderRadius: "var(--radius-sm)",
                background: "transparent",
                border: "none",
                color: "var(--status-critical)",
                fontSize: "var(--text-xs)",
                fontWeight: 500,
                cursor: "pointer",
                textAlign: "left",
                transition: "background var(--transition-fast)",
              }}
            >
              <LogOut size={14} />
              <span>{isLoggingOut ? "Cerrando sesión..." : "Cerrar sesión"}</span>
            </button>
          </div>
        </>
      )}

      <UserProfileModal
        isOpen={isProfileOpen}
        onClose={() => setIsProfileOpen(false)}
      />
    </div>
  );
}
