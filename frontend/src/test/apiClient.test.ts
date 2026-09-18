import { describe, it, expect, vi, beforeEach } from "vitest";
import { apiClient } from "@/api/client";
import { ApiError } from "@/types/api";

describe("apiClient", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("adds credentials and accepts json responses", async () => {
    const mockData = { message: "ok" };
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(mockData), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const result = await apiClient<{ message: string }>("/test");
    expect(result).toEqual(mockData);
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/test",
      expect.objectContaining({
        credentials: "include",
        method: "GET",
      })
    );
  });

  it("injects X-CSRF-Token on mutating requests when cookie exists", async () => {
    // In JSDOM document.cookie works without __Host- security constraints
    Object.defineProperty(document, "cookie", {
      writable: true,
      value: "nexus_csrf=csrf-secret-12345",
    });

    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ status: "created" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      })
    );

    await apiClient("/devices", {
      method: "POST",
      body: JSON.stringify({ hostname: "test-srv" }),
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/v1/devices",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "X-CSRF-Token": "csrf-secret-12345",
          "Content-Type": "application/json",
        }),
      })
    );
  });

  it("converts RFC 7807 error responses into ApiError instances with error_id", async () => {
    const errorPayload = {
      error: {
        code: "PERMISSION_DENIED",
        message: "No posee permisos suficientes.",
        error_id: "ERR-987654",
      },
    };

    vi.spyOn(global, "fetch").mockImplementation(
      async () =>
        new Response(JSON.stringify(errorPayload), {
          status: 403,
          headers: { "Content-Type": "application/json" },
        })
    );

    await expect(apiClient("/admin/protected")).rejects.toThrow(ApiError);
    try {
      await apiClient("/admin/protected");
    } catch (err: any) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.code).toBe("PERMISSION_DENIED");
      expect(err.errorId).toBe("ERR-987654");
      expect(err.status).toBe(403);
    }
  });
});
