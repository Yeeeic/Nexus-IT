import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "@/components/common/Button";
import { Badge } from "@/components/common/Badge";
import { StatusIndicator } from "@/components/metrics/StatusIndicator";
import { Modal } from "@/components/common/Modal";
import { Table } from "@/components/common/Table";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { RemoteScreenViewer } from "@/components/remote/RemoteScreenViewer";
import { WebTerminalView } from "@/components/remote/WebTerminalView";
import { NotificationProvider } from "@/context/NotificationContext";

describe("Frontend Core UI Components", () => {
  it("renders Button with loading state and disabled attribute", () => {
    render(<Button isLoading>Acción</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
  });

  it("renders Badge with semantic status dot", () => {
    const { container } = render(
      <Badge variant="healthy" dot>
        Activo
      </Badge>
    );
    expect(screen.getByText("Activo")).toBeInTheDocument();
    expect(container.querySelector(".status-dot.healthy")).toBeInTheDocument();
  });

  it("renders StatusIndicator translating internal codes to Spanish", () => {
    render(<StatusIndicator status="ONLINE" />);
    expect(screen.getByText("En línea")).toBeInTheDocument();
  });

  it("handles Modal Escape key to trigger onClose", () => {
    const onClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={onClose} title="Diálogo de Prueba">
        Contenido modal
      </Modal>
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Diálogo de Prueba")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("renders Table with columns, rows and empty states", () => {
    const data = [{ id: "1", name: "Servidor 01", ip: "10.0.0.1" }];
    render(
      <Table
        columns={[
          { header: "Nombre", accessorKey: "name" },
          { header: "IP", accessorKey: "ip" },
        ]}
        data={data}
        keyExtractor={(d) => d.id}
      />
    );

    expect(screen.getByText("Servidor 01")).toBeInTheDocument();
    expect(screen.getByText("10.0.0.1")).toBeInTheDocument();
  });

  it("renders ErrorBoundary fallback when a child crashes", () => {
    const ThrowingComponent = () => {
      throw new Error("Simulated Crash");
    };

    // Suppress console.error in tests for expected thrown error
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    render(
      <ErrorBoundary fallbackTitle="Error en Módulo">
        <ThrowingComponent />
      </ErrorBoundary>
    );

    expect(screen.getByText("Error en Módulo")).toBeInTheDocument();
    spy.mockRestore();
  });

  it("renders RemoteScreenViewer offline state when device is not active", () => {
    render(
      <NotificationProvider>
        <RemoteScreenViewer deviceId="dev-123" hostname="servidor-db" isOnline={false} />
      </NotificationProvider>
    );
    expect(screen.getByText("Dispositivo Fuera de Línea")).toBeInTheDocument();
    expect(screen.getByText(/vista previa visual/i)).toBeInTheDocument();
  });

  it("labels RemoteScreenViewer as a local simulation", () => {
    render(
      <NotificationProvider>
        <RemoteScreenViewer deviceId="dev-123" hostname="servidor-db" isOnline={true} />
      </NotificationProvider>
    );
    expect(screen.getByText(/Vista previa de pantalla/i)).toBeInTheDocument();
    expect(screen.getByText(/Sin conexión remota/i)).toBeInTheDocument();
    expect(screen.queryByText(/Transmitiendo en vivo/i)).not.toBeInTheDocument();
  });

  it("labels WebTerminalView as a non-operational simulation", () => {
    render(<WebTerminalView deviceId="dev-123" hostname="servidor-db" isOnline={true} />);
    expect(screen.getByText(/Vista previa de diagnóstico/i)).toBeInTheDocument();
    expect(screen.getByText(/ningún comando se ejecuta/i)).toBeInTheDocument();
    expect(screen.getByText(/no conecta con el agente/i)).toBeInTheDocument();
  });
});
