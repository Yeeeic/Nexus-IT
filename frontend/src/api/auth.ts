import { apiClient } from "./client";
import type {
  AuthContextSelectInput,
  LoginCredentials,
  LoginResponse,
  PasswordResetConfirmInput,
  PasswordResetRequestInput,
  UserMeResponse,
} from "@/types/auth";

export const authApi = {
  getMe: () => apiClient<UserMeResponse>("/auth/me"),

  login: (credentials: LoginCredentials) =>
    apiClient<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),

  selectContext: (input: AuthContextSelectInput) =>
    apiClient<UserMeResponse>("/auth/context", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  logout: () =>
    apiClient<{ status: string }>("/auth/logout", {
      method: "POST",
    }),

  requestPasswordReset: (input: PasswordResetRequestInput) =>
    apiClient<{ status: string }>("/auth/password-reset/request", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  confirmPasswordReset: (input: PasswordResetConfirmInput) =>
    apiClient<{ status: string }>("/auth/password-reset/confirm", {
      method: "POST",
      body: JSON.stringify(input),
    }),
};
