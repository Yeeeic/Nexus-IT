import { apiClient } from "./client";
import type {
  TelemetryResponse,
  AlertListResponse,
  AlertRuleInput,
  AlertRuleResponse,
  AlertRuleListResponse,
  BatchStatusResponse,
  BatchStatusQueryResponse,
  BatchDiagnosticsResponse,
} from "@/types/metrics";

export const metricsApi = {
  getTelemetry: async (
    deviceId: string,
    params?: { metric_name?: string | undefined; limit?: number | undefined }
  ): Promise<TelemetryResponse> => {
    return apiClient<TelemetryResponse>(`/devices/${deviceId}/metrics/telemetry`, {
      method: "GET",
      params: {
        metric_name: params?.metric_name,
        limit: params?.limit,
      },
    });
  },

  listAlerts: async (params?: { limit?: number | undefined }): Promise<AlertListResponse> => {
    return apiClient<AlertListResponse>("/alerts", {
      method: "GET",
      params: {
        limit: params?.limit,
      },
    });
  },

  createAlertRule: async (data: AlertRuleInput): Promise<AlertRuleResponse> => {
    return apiClient<AlertRuleResponse>("/alert-rules", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },

  listAlertRules: async (): Promise<AlertRuleListResponse> => {
    return apiClient<AlertRuleListResponse>("/alert-rules", {
      method: "GET",
    });
  },

  getBatchStatus: async (deviceId: string, batchId: string): Promise<BatchStatusResponse> => {
    return apiClient<BatchStatusResponse>(`/devices/${deviceId}/metrics/batches/${batchId}`, {
      method: "GET",
    });
  },

  queryBatchStatuses: async (
    deviceId: string,
    batchIds: string[]
  ): Promise<BatchStatusQueryResponse> => {
    return apiClient<BatchStatusQueryResponse>(
      `/devices/${deviceId}/metrics/batches/status-query`,
      {
        method: "POST",
        body: JSON.stringify({ batch_ids: batchIds }),
      }
    );
  },

  getDiagnostics: async (
    deviceId: string,
    batchId: string
  ): Promise<BatchDiagnosticsResponse> => {
    return apiClient<BatchDiagnosticsResponse>(
      `/devices/${deviceId}/metrics/batches/${batchId}/export-diagnostics`,
      {
        method: "GET",
      }
    );
  },

  retryBatch: async (
    deviceId: string,
    batchId: string,
    reason: string
  ): Promise<BatchStatusResponse> => {
    return apiClient<BatchStatusResponse>(
      `/devices/${deviceId}/metrics/batches/${batchId}/retry`,
      {
        method: "POST",
        body: JSON.stringify({ reason }),
      }
    );
  },

  makeDecision: async (
    deviceId: string,
    batchId: string,
    action: "PURGE_LOCAL" | "RETAIN",
    reason: string
  ): Promise<BatchStatusResponse> => {
    return apiClient<BatchStatusResponse>(
      `/devices/${deviceId}/metrics/batches/${batchId}/decision`,
      {
        method: "POST",
        body: JSON.stringify({ action, reason }),
      }
    );
  },
};
