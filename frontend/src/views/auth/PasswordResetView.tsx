import React, { useState } from "react";
import { authApi } from "@/api/auth";
import { Input } from "@/components/common/Input";
import { Button } from "@/components/common/Button";
import { KeyRound, Mail, ArrowLeft, CheckCircle2 } from "lucide-react";
import { ApiError } from "@/types/api";

export interface PasswordResetViewProps {
  onBackToLogin: () => void;
}

export function PasswordResetView({ onBackToLogin }: PasswordResetViewProps) {
  const [step, setStep] = useState<"request" | "confirm">("request");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleRequest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    setIsLoading(true);
    setErrorMsg(null);

    try {
      await authApi.requestPasswordReset({ email });
      setSuccessMsg(
        "Si la cuenta existe, se ha generado el enlace de restablecimiento. Ingrese el token recibido para continuar."
      );
      setStep("confirm");
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Error al procesar la solicitud.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleConfirm = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !newPassword) {
      setErrorMsg("Por favor complete todos los campos.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMsg("Las contraseñas no coinciden.");
      return;
    }

    setIsLoading(true);
    setErrorMsg(null);

    try {
      await authApi.confirmPasswordReset({ token, new_password: newPassword });
      setSuccessMsg("¡Contraseña actualizada exitosamente! Ya puede iniciar sesión.");
      setTimeout(() => {
        onBackToLogin();
      }, 2000);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Token inválido o expirado.");
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
      }}
    >
      <div
        className="nexus-card nexus-card-elevated"
        style={{
          width: "100%",
          maxWidth: "420px",
          padding: "2.5rem 2rem",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <button
          onClick={onBackToLogin}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.375rem",
            background: "transparent",
            border: "none",
            color: "var(--text-secondary)",
            fontSize: "var(--text-xs)",
            cursor: "pointer",
            marginBottom: "1.5rem",
          }}
        >
          <ArrowLeft size={14} /> Volver al inicio de sesión
        </button>

        <div style={{ textAlign: "center", marginBottom: "2rem" }}>
          <div
            style={{
              width: "48px",
              height: "48px",
              margin: "0 auto 1rem",
              borderRadius: "var(--radius-lg)",
              backgroundColor: "var(--bg-surface-elevated)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "var(--brand-primary)",
            }}
          >
            <KeyRound size={24} />
          </div>
          <h1 style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>
            {step === "request" ? "Recuperar Contraseña" : "Fijar Nueva Contraseña"}
          </h1>
          <p style={{ fontSize: "var(--text-xs)", color: "var(--text-secondary)", marginTop: "0.25rem" }}>
            {step === "request"
              ? "Ingrese su correo registrado para recibir un token de recuperación"
              : "Ingrese el token de seguridad y su nueva contraseña"}
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

        {successMsg && (
          <div
            role="status"
            style={{
              padding: "0.75rem 1rem",
              backgroundColor: "var(--status-healthy-bg)",
              border: "1px solid var(--status-healthy-border)",
              borderRadius: "var(--radius-md)",
              color: "var(--status-healthy)",
              fontSize: "var(--text-xs)",
              marginBottom: "1.25rem",
              display: "flex",
              alignItems: "center",
              gap: "0.5rem",
            }}
          >
            <CheckCircle2 size={16} />
            <span>{successMsg}</span>
          </div>
        )}

        {step === "request" ? (
          <form onSubmit={handleRequest} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            <Input
              label="Correo Electrónico"
              type="email"
              placeholder="admin@empresa.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              leftIcon={<Mail size={16} />}
              required
              autoFocus
            />

            <Button type="submit" variant="primary" size="lg" isLoading={isLoading} style={{ width: "100%" }}>
              Enviar Instrucciones
            </Button>
          </form>
        ) : (
          <form onSubmit={handleConfirm} style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
            <Input
              label="Token de Restablecimiento"
              type="text"
              placeholder="Token de 64 caracteres..."
              value={token}
              onChange={(e) => setToken(e.target.value)}
              required
            />

            <Input
              label="Nueva Contraseña"
              type="password"
              placeholder="••••••••••••"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
            />

            <Input
              label="Confirmar Contraseña"
              type="password"
              placeholder="••••••••••••"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />

            <Button type="submit" variant="primary" size="lg" isLoading={isLoading} style={{ width: "100%" }}>
              Guardar Contraseña
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
