import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { actionsApi } from "@/api/actions";
import { devicesApi } from "@/api/devices";
import { AutoRemediationPromptModal } from "@/components/remediation/AutoRemediationPromptModal";
import { ACTION_CATALOG_OPTIONS } from "@/views/actions/ActionsConsoleView";
import { DevicesListView } from "@/views/devices/DevicesListView";
import { QuickInstallerModal } from "@/views/devices/QuickInstallerModal";

vi.mock("@/api/actions", () => ({
  actionsApi: {
    listByDevice: vi.fn(),
    create: vi.fn(),
    submitApproval: vi.fn(),
  },
}));

vi.mock("@/api/devices", () => ({
  devicesApi: {
    list: vi.fn(),
    create: vi.fn(),
    delete: vi.fn(),
    createToken: vi.fn(),
  },
}));

vi.mock("@/context/AuthContext", () => ({
  useAuth: () => ({ hasPermission: () => true }),
}));

vi.mock("@/context/NotificationContext", () => ({
  useNotification: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}));

const device = {
  id: "11111111-1111-4111-8111-111111111111",
  hostname: "endpoint-e2e",
  display_name: "Equipo E2E",
  is_active: true,
  last_seen_at: null,
  created_at: "2026-09-04T12:00:00Z",
  updated_at: "2026-09-04T12:00:00Z",
};

describe("console-to-agent contract regressions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(devicesApi.list).mockResolvedValue({ items: [device], next_cursor: null });
    vi.mocked(actionsApi.listByDevice).mockResolvedValue({ items: [] });
  });

  it("offers exactly the action names accepted by the backend catalog", () => {
    expect(ACTION_CATALOG_OPTIONS.map(({ value }) => value)).toEqual([
      "reboot_system",
      "restart_service",
      "collect_extended_diagnostics",
      "flush_dns",
    ]);
  });

  it("opens enrollment after registration and preserves the one-time token", async () => {
    const enrollment = {
      ...device,
      token_id: "22222222-2222-4222-8222-222222222222",
      token: "22222222-2222-4222-8222-222222222222.one-time-secret",
      token_expires_at: null,
    };
    vi.mocked(devicesApi.create).mockResolvedValue(enrollment);

    render(<DevicesListView />);

    fireEvent.click(await screen.findByRole("button", { name: "Registrar Manual" }));
    fireEvent.change(screen.getByLabelText("Nombre de Host (Hostname)"), {
      target: { value: enrollment.hostname },
    });
    fireEvent.click(screen.getByRole("button", { name: "Guardar y Generar Token" }));

    expect(await screen.findByText("Aprovisionamiento de Agente de Monitoreo")).toBeInTheDocument();
    expect(screen.getByText(enrollment.token)).toBeInTheDocument();
  });

  it("never dispatches the unsupported clear_cache action", async () => {
    vi.mocked(actionsApi.create).mockResolvedValue({
      organization_id: "33333333-3333-4333-8333-333333333333",
      id: "44444444-4444-4444-8444-444444444444",
      device_id: device.id,
      action_name: "collect_extended_diagnostics",
      nonce: "55555555-5555-4555-8555-555555555555",
      key_version: 1,
      issued_at: "2026-09-04T12:00:00Z",
      expires_at: "2026-09-04T12:05:00Z",
      signature: "signature",
      parameters: {},
      status: "DISPATCHED",
    });

    render(
      <AutoRemediationPromptModal
        remediation={{ deviceId: device.id, hostname: device.hostname, diskPercent: 96 }}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: "Autorizar y Ejecutar Ahora" }));

    await waitFor(() => expect(actionsApi.create).toHaveBeenCalledTimes(1));
    const [, request] = vi.mocked(actionsApi.create).mock.calls[0]!;
    expect(request.action_name).toBe("collect_extended_diagnostics");
    expect(request.action_name).not.toBe("clear_cache");
  });

  it("keeps the Windows token out of command history", () => {
    render(<QuickInstallerModal isOpen onClose={vi.fn()} />);

    const instructions = screen.getByText(/Windows 10, 11 y Windows Server/).textContent ?? "";
    expect(instructions).not.toContain("-Token");
    expect(instructions).not.toContain("scriptblock");
    expect(instructions).toContain("-ExpectedSha256");
    expect(instructions).toContain("a447aad4d54c541aca7966dd9eab07116ac4fdcf38514131f824332fdc98f534");
    expect(instructions).toContain('-PackageVersion "1.0.0"');
    expect(instructions).not.toContain("<SHA256_DEL_PAQUETE>");
    expect(instructions).toContain("solicitara el token de forma segura");
  });
});
