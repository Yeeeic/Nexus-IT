import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { App } from "@/App";
import * as authContext from "@/context/AuthContext";
import { NotificationProvider } from "@/context/NotificationContext";
import { ThemeProvider } from "@/context/ThemeContext";

// Mock the AuthContext values
vi.mock("@/context/AuthContext", () => ({
  useAuth: vi.fn(),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock WebSocket hook
vi.mock("@/realtime/useWebSocket", () => ({
  useWebSocket: () => ({
    status: "CONNECTED",
    lastEvent: null,
    isManualPaused: false,
    toggleConnection: vi.fn(),
  }),
}));

// Mock API modules matching their object exports
vi.mock("@/api/devices", () => ({
  devicesApi: {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          id: "dev-01",
          hostname: "servidor-db",
          display_name: "Base de Datos Principal",
          is_active: true,
          last_seen_at: new Date().toISOString(),
        },
      ],
      next_cursor: null,
    }),
    getById: vi.fn().mockResolvedValue({
      id: "dev-01",
      hostname: "servidor-db",
      is_active: true,
    }),
  },
}));

vi.mock("@/api/tickets", () => ({
  ticketsApi: {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          id: "tick-01",
          title: "Fallo de conexión",
          status: "OPEN",
          priority: "HIGH",
          created_at: new Date().toISOString(),
        },
      ],
      next_cursor: null,
    }),
    create: vi.fn().mockResolvedValue({
      id: "tick-02",
      title: "Nuevo Ticket",
      status: "OPEN",
      ticket_number: "1001",
    }),
  },
}));

vi.mock("@/api/metrics", () => ({
  metricsApi: {
    listAlerts: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
    listAlertRules: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
    getTelemetry: vi.fn().mockResolvedValue({
      items: [],
    }),
  },
}));

vi.mock("@/api/actions", () => ({
  actionsApi: {
    listExecutions: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
  },
}));

vi.mock("@/api/admin", () => ({
  adminApi: {
    getAuditLogs: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
    getRoles: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
    getPermissions: vi.fn().mockResolvedValue({
      items: [],
      next_cursor: null,
    }),
  },
}));

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <ThemeProvider>
      <NotificationProvider>{ui}</NotificationProvider>
    </ThemeProvider>
  );
}

describe("Application End-to-End Navigation & Auth Flow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders Loading verification state while auth is loading", () => {
    vi.mocked(authContext.useAuth).mockReturnValue({
      isLoading: true,
      isAuthenticated: false,
      requiresOrgSelection: false,
      user: null,
      availableOrganizations: [],
      hasPermission: () => false,
      login: vi.fn(),
      selectOrganization: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    renderWithProviders(<App />);
    expect(screen.getByText("Verificando sesión segura...")).toBeInTheDocument();
  });

  it("renders Login view when user is unauthenticated", () => {
    vi.mocked(authContext.useAuth).mockReturnValue({
      isLoading: false,
      isAuthenticated: false,
      requiresOrgSelection: false,
      user: null,
      availableOrganizations: [],
      hasPermission: () => false,
      login: vi.fn(),
      selectOrganization: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    renderWithProviders(<App />);
    expect(screen.getByText("Iniciar Sesión")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("admin@empresa.com")).toBeInTheDocument();
  });

  it("renders OrgSelectView when user requires organization selection", () => {
    vi.mocked(authContext.useAuth).mockReturnValue({
      isLoading: false,
      isAuthenticated: false,
      requiresOrgSelection: true,
      user: null,
      availableOrganizations: [
        {
          organization_id: "org-1",
          organization_name: "Nexus IT Corp",
          slug: "nexus-corp",
        },
      ],
      hasPermission: () => false,
      login: vi.fn(),
      selectOrganization: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    renderWithProviders(<App />);
    expect(screen.getByText("Seleccione una Organización")).toBeInTheDocument();
    expect(screen.getByText("Nexus IT Corp")).toBeInTheDocument();
  });

  it("renders Admin Dashboard and allows navigating between tabs for full admin", async () => {
    vi.mocked(authContext.useAuth).mockReturnValue({
      isLoading: false,
      isAuthenticated: true,
      requiresOrgSelection: false,
      user: {
        user_id: "usr-1",
        email: "admin@nexus.local",
        full_name: "Administrador Principal",
        organization_id: "org-1",
        permissions: ["devices:read_all", "tickets:read_all", "actions:execute"],
        available_organizations: [],
      },
      availableOrganizations: [],
      hasPermission: () => true,
      login: vi.fn(),
      selectOrganization: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    renderWithProviders(<App />);

    // Initial view should have dashboard stats
    await waitFor(() => {
      expect(screen.getByText("Dispositivos Monitoreados")).toBeInTheDocument();
    });

    // Click on Dispositivos tab
    const devicesNav = screen.getByRole("button", { name: /dispositivos/i });
    fireEvent.click(devicesNav);

    await waitFor(() => {
      expect(screen.getByText("Inventario de Dispositivos")).toBeInTheDocument();
    });

    // Click on Tickets tab
    const ticketsNav = screen.getByRole("button", { name: /mesa de ayuda|tickets/i });
    fireEvent.click(ticketsNav);

    await waitFor(() => {
      expect(screen.getByText("Mesa de Ayuda")).toBeInTheDocument();
    });
  });

  it("restricts client reader to ClientPortalView only", async () => {
    vi.mocked(authContext.useAuth).mockReturnValue({
      isLoading: false,
      isAuthenticated: true,
      requiresOrgSelection: false,
      user: {
        user_id: "usr-carlos",
        email: "carlos@nexus.local",
        full_name: "Carlos (Usuario)",
        organization_id: "org-1",
        permissions: ["devices:read_assigned"],
        available_organizations: [],
      },
      availableOrganizations: [],
      hasPermission: (perm: string) => perm === "devices:read_assigned",
      login: vi.fn(),
      selectOrganization: vi.fn(),
      logout: vi.fn(),
      refreshSession: vi.fn(),
    });

    renderWithProviders(<App />);

    const headings = await screen.findAllByRole("heading", {
      name: /portal de autoservicio & soporte/i,
    });
    expect(headings.length).toBeGreaterThanOrEqual(1);
    expect(
      await screen.findByRole("button", { name: /solicitar ayuda técnica/i })
    ).toBeInTheDocument();
  });
});
