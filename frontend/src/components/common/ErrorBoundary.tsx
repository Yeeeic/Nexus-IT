import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "./Button";

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public override state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("ErrorBoundary atrapó un error no controlado:", error, errorInfo);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  public override render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            padding: "3rem 1.5rem",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            textAlign: "center",
            backgroundColor: "var(--bg-surface)",
            border: "1px solid var(--status-critical-border)",
            borderRadius: "var(--radius-lg)",
            margin: "1rem auto",
            maxWidth: "600px",
          }}
        >
          <div
            style={{
              width: "48px",
              height: "48px",
              borderRadius: "var(--radius-full)",
              backgroundColor: "var(--status-critical-bg)",
              color: "var(--status-critical)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: "1rem",
            }}
          >
            <AlertTriangle size={24} />
          </div>
          <h3 style={{ fontSize: "var(--text-lg)", fontWeight: 600, color: "var(--text-primary)" }}>
            {this.props.fallbackTitle || "Ocurrió un error al cargar este módulo"}
          </h3>
          <p
            style={{
              fontSize: "var(--text-sm)",
              color: "var(--text-secondary)",
              maxWidth: "450px",
              marginTop: "0.5rem",
              marginBottom: "1.5rem",
            }}
          >
            Se ha registrado el incidente. Puede intentar recargar la vista o volver al panel principal.
          </p>
          <div style={{ display: "flex", gap: "0.75rem" }}>
            <Button
              variant="secondary"
              leftIcon={<RefreshCw size={16} />}
              onClick={this.handleReset}
            >
              Reintentar
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                window.location.href = "/";
              }}
            >
              Ir al inicio
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
