import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ClientPortalView } from "@/views/portal/ClientPortalView";

const mocks = vi.hoisted(() => ({
  listDevices: vi.fn(),
  listTickets: vi.fn(),
  createTicket: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@/api/devices", () => ({
  devicesApi: { list: mocks.listDevices },
}));

vi.mock("@/api/tickets", () => ({
  ticketsApi: { list: mocks.listTickets, create: mocks.createTicket },
}));

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({
    user: { id: "user-1", email: "ana@example.test", full_name: "Ana" },
  }),
}));

vi.mock("@/context/NotificationContext", () => ({
  useNotification: () => ({ success: mocks.success, error: mocks.error }),
}));

vi.mock("@/views/tickets/CreateTicketModal", () => ({
  CreateTicketModal: () => null,
}));

const device = {
  id: "device-1",
  hostname: "equipo-ana",
  display_name: null,
  is_active: true,
  last_seen_at: "2026-08-25T12:00:00Z",
  created_at: "2026-08-25T10:00:00Z",
  updated_at: "2026-08-25T12:00:00Z",
};

const ticket = {
  id: "ticket-1",
  device_id: device.id,
  alert_id: null,
  created_by: "user-1",
  assigned_to: null,
  ticket_number: "NEX-1001",
  title: "Solicitud prioritaria de asistencia técnica - Ana",
  description: "Solicitud registrada mediante ticket.",
  status: "OPEN" as const,
  priority: "HIGH" as const,
  resolved_at: null,
  created_at: "2026-08-25T12:00:00Z",
  updated_at: "2026-08-25T12:00:00Z",
};

describe("ClientPortalView assistance request", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.listDevices.mockResolvedValue({ items: [device], next_cursor: null });
    mocks.listTickets.mockResolvedValue({ items: [], next_cursor: null });
  });

  it("creates a support ticket without claiming a remote session", async () => {
    mocks.createTicket.mockResolvedValue(ticket);
    render(<ClientPortalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Solicitar ayuda técnica" }));

    expect(await screen.findByText("Solicitud de asistencia registrada")).toBeInTheDocument();
    expect(screen.getByText(/no inicia una sesión remota/i)).toBeInTheDocument();
    expect(mocks.createTicket).toHaveBeenCalledWith(
      expect.objectContaining({
        description: expect.stringContaining("no inicia una sesión remota ni autoriza comandos"),
      })
    );
    expect(mocks.success).toHaveBeenCalled();
  });

  it("reports ticket creation failure without showing false success", async () => {
    mocks.createTicket.mockRejectedValue(new Error("network unavailable"));
    render(<ClientPortalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Solicitar ayuda técnica" }));

    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
    expect(mocks.success).not.toHaveBeenCalled();
    expect(screen.queryByText("Solicitud de asistencia registrada")).not.toBeInTheDocument();
  });
});
