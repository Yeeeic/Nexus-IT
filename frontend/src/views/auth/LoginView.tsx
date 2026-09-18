import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { Input } from "@/components/common/Input";
import { Button } from "@/components/common/Button";
import { ShieldCheck, Lock, Mail, Eye, EyeOff } from "lucide-react";
import { ApiError } from "@/types/api";

export interface LoginViewProps {
  onForgotPassword: () => void;
}

export function LoginView({ onForgotPassword }: LoginViewProps) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setErrorMsg("Por favor ingrese su correo electrónico y contraseña.");
      return;
    }

    setIsLoading(true);
    setErrorMsg(null);

    try {
      await login({ email, password });
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message || "Credenciales incorrectas o cuenta bloqueada.");
      } else {
        setErrorMsg("Error de conexión con el servidor de autenticación.");
      }
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
        position: "relative",
      }}
    >
      {/* Background Accent Glow */}
      <div
        style={{
          position: "absolute",
          width: "400px",
          height: "400px",
          borderRadius: "50%",
          background: "radial-gradient(circle, rgba(14, 165, 233, 0.12) 0%, rgba(0, 0, 0, 0) 70%)",
          filter: "blur(40px)",
          pointerEvents: "none",
        }}
      />

      <div
        className="nexus-card nexus-card-elevated"
        style={{
          width: "100%",
          maxWidth: "420px",
          padding: "2.5rem 2rem",
          position: "relative",
          zIndex: 1,
          boxShadow: "var(--shadow-lg)",
        }}
      >
        {/* Brand Header */}
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
          <h1 style={{ fontSize: "var(--text-xl)", fontWeight: 700, letterSpacing: "-0.01em" }}>
            NEXUS <span style={{ color: "var(--brand-primary)" }}>IT</span>
          </h1>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            Monitoreo en Tiempo Real y Soporte Técnico
          </p>
        </div>

        {errorMsg && (
          <div
            role="alert"
            style={{
              padding: "0.75rem 1rem",
              backgroundColor: "var(--status-critical-bg)",
              border: "1px solid var(--status-critical-border)",
              borderRadius: "var(--radius-md)",
              color: "var(--status-critical)",
              fontSize: "var(--text-xs)",
              marginBottom: "1.25rem",
            }}
          >
            {errorMsg}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
          <Input
            label="Correo Electrónico"
            type="email"
            placeholder="admin@empresa.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            leftIcon={<Mail size={16} />}
            required
            autoFocus
            autoComplete="email"
          />

          <Input
            label="Contraseña"
            type={showPassword ? "text" : "password"}
            placeholder="••••••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            leftIcon={<Lock size={16} />}
            rightIcon={
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                aria-label={showPassword ? "Ocultar contraseña" : "Ver contraseña"}
                style={{ background: "transparent", border: "none", color: "var(--text-muted)", cursor: "pointer", display: "flex" }}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            }
            required
            autoComplete="current-password"
          />

          <div style={{ display: "flex", justifyContent: "flex-end" }}>
            <button
              type="button"
              onClick={onForgotPassword}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--brand-primary)",
                fontSize: "var(--text-xs)",
                cursor: "pointer",
                padding: 0,
              }}
            >
              ¿Olvidó su contraseña?
            </button>
          </div>

          <Button
            type="submit"
            variant="primary"
            size="lg"
            isLoading={isLoading}
            style={{ width: "100%", marginTop: "0.5rem" }}
          >
            Iniciar Sesión
          </Button>
        </form>

        <div
          style={{
            marginTop: "1.75rem",
            paddingTop: "1.25rem",
            borderTop: "1px solid var(--border-subtle)",
            textAlign: "center",
            fontSize: "var(--text-2xs)",
            color: "var(--text-muted)",
          }}
        >
          Sesión protegida por Argon2id & Tokens Criptográficos
        </div>
      </div>
    </div>
  );
}
