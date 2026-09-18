/**
 * Unified API Response and Error Contracts matching FastAPI RFC 7807/Nexus error format.
 */

export interface ApiErrorDetail {
  code: string;
  message: string;
  field?: string | undefined;
}

export interface ApiErrorResponse {
  error: {
    code: string;
    message: string;
    error_id?: string | undefined;
    details?: ApiErrorDetail[] | undefined;
  };
}

export class ApiError extends Error {
  public readonly code: string;
  public readonly status: number;
  public readonly errorId: string | undefined;
  public readonly details: ApiErrorDetail[] | undefined;

  constructor(
    status: number,
    code: string,
    message: string,
    errorId?: string | undefined,
    details?: ApiErrorDetail[] | undefined
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.errorId = errorId;
    this.details = details;
  }
}
