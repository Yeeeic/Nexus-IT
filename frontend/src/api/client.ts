import { ApiError, type ApiErrorResponse } from "@/types/api";

const API_BASE_URL = "/api/v1";

/**
 * Reads a cookie value by name from document.cookie safely.
 */
function getCookie(name: string): string | null {
  if (typeof document === "undefined" || !document.cookie) return null;
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1] || "") : null;
}

export interface RequestOptions extends RequestInit {
  timeoutMs?: number | undefined;
  params?: Record<string, string | number | boolean | undefined | null> | undefined;
}

export async function apiClient<T>(endpoint: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = 15000, params, headers = {}, ...customConfig } = options;

  let url = `${API_BASE_URL}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

  if (params) {
    const query = new URLSearchParams();
    for (const [key, val] of Object.entries(params)) {
      if (val !== undefined && val !== null) {
        query.append(key, String(val));
      }
    }
    const queryString = query.toString();
    if (queryString) {
      url += `${url.includes("?") ? "&" : "?"}${queryString}`;
    }
  }

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const reqHeaders: Record<string, string> = {
    Accept: "application/json",
    ...(headers as Record<string, string>),
  };

  const method = (customConfig.method || "GET").toUpperCase();

  // Attach CSRF token on mutating requests
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method)) {
    const csrfToken = getCookie("__Host-nexus_csrf") || getCookie("nexus_csrf");
    if (csrfToken) {
      reqHeaders["X-CSRF-Token"] = csrfToken;
    }
    if (!(customConfig.body instanceof FormData) && !reqHeaders["Content-Type"]) {
      reqHeaders["Content-Type"] = "application/json";
    }
  }

  try {
    const response = await fetch(url, {
      ...customConfig,
      method,
      headers: reqHeaders,
      credentials: "include", // Required for __Host-nexus_session cookies
      signal: customConfig.signal || controller.signal,
    });

    clearTimeout(timeoutId);

    if (response.status === 204) {
      return {} as T;
    }

    const contentType = response.headers.get("content-type");
    const isJson = contentType && contentType.includes("application/json");

    if (!response.ok) {
      let errorCode = `HTTP_${response.status}`;
      let errorMessage = response.statusText || "Error en la solicitud";
      let errorId: string | undefined;
      let details: undefined | any[];

      if (isJson) {
        try {
          const errorData = (await response.json()) as ApiErrorResponse;
          if (errorData?.error) {
            errorCode = errorData.error.code || errorCode;
            errorMessage = errorData.error.message || errorMessage;
            errorId = errorData.error.error_id;
            details = errorData.error.details;
          }
        } catch {
          // fallback to status text
        }
      }

      if (response.status === 429) {
        const retryAfter = response.headers.get("Retry-After");
        errorMessage = retryAfter
          ? `Límite de solicitudes alcanzado. Reintente en ${retryAfter} segundos.`
          : "Límite de solicitudes alcanzado. Por favor, espere antes de reintentar.";
      }

      throw new ApiError(response.status, errorCode, errorMessage, errorId, details);
    }

    if (isJson) {
      return (await response.json()) as T;
    }

    return (await response.blob()) as unknown as T;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(408, "REQUEST_TIMEOUT", "La solicitud superó el tiempo de espera.");
    }
    throw new ApiError(0, "NETWORK_ERROR", "Error de conexión con el servidor. Verifique su red.");
  }
}
