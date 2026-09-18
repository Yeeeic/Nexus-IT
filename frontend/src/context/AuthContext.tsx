import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { authApi } from "@/api/auth";
import type {
  LoginCredentials,
  OrganizationMembershipItem,
  UserMeResponse,
} from "@/types/auth";
import { ApiError } from "@/types/api";

interface AuthContextType {
  user: UserMeResponse | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  requiresOrgSelection: boolean;
  availableOrganizations: OrganizationMembershipItem[];
  login: (credentials: LoginCredentials) => Promise<{ requiresOrgSelection: boolean }>;
  selectOrganization: (organizationId: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  hasPermission: (permissionCode: string) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserMeResponse | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [requiresOrgSelection, setRequiresOrgSelection] = useState<boolean>(false);
  const [availableOrganizations, setAvailableOrganizations] = useState<
    OrganizationMembershipItem[]
  >([]);

  const refreshSession = useCallback(async () => {
    try {
      setIsLoading(true);
      const me = await authApi.getMe();
      setUser(me);
      setAvailableOrganizations(me.available_organizations || []);
      setRequiresOrgSelection(!me.organization_id && me.available_organizations?.length > 0);
    } catch (err) {
      setUser(null);
      setRequiresOrgSelection(false);
      setAvailableOrganizations([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshSession();
  }, [refreshSession]);

  const login = useCallback(
    async (credentials: LoginCredentials) => {
      setIsLoading(true);
      try {
        const response = await authApi.login(credentials);
        if (response.status === "ORGANIZATION_SELECTION_REQUIRED") {
          setRequiresOrgSelection(true);
          setAvailableOrganizations(response.available_organizations || []);
          return { requiresOrgSelection: true };
        }

        await refreshSession();
        return { requiresOrgSelection: false };
      } catch (err) {
        if (err instanceof ApiError) {
          throw err;
        }
        throw new ApiError(500, "AUTH_ERROR", "Error inesperado al iniciar sesión.");
      } finally {
        setIsLoading(false);
      }
    },
    [refreshSession]
  );

  const selectOrganization = useCallback(
    async (organizationId: string) => {
      setIsLoading(true);
      try {
        const me = await authApi.selectContext({ organization_id: organizationId });
        setUser(me);
        setRequiresOrgSelection(false);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const logout = useCallback(async () => {
    setIsLoading(true);
    try {
      await authApi.logout();
    } catch {
      // ignore network errors on logout
    } finally {
      setUser(null);
      setRequiresOrgSelection(false);
      setAvailableOrganizations([]);
      setIsLoading(false);
    }
  }, []);

  const hasPermission = useCallback(
    (permissionCode: string) => {
      if (!user) return false;
      return user.permissions.includes(permissionCode);
    },
    [user]
  );

  const isAuthenticated = Boolean(user && user.organization_id);

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated,
        requiresOrgSelection,
        availableOrganizations,
        login,
        selectOrganization,
        logout,
        refreshSession,
        hasPermission,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
