import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import useSWR from "swr";
import {
  ApiError,
  getMe,
  login as apiLogin,
  logout as apiLogout,
  type CurrentUser,
} from "../api/client";

interface AuthValue {
  user: CurrentUser | null;
  isLoading: boolean;
  error: ApiError | null;
  login: (email: string, password: string) => Promise<CurrentUser>;
  logout: () => Promise<void>;
  refresh: () => Promise<unknown>;
}

const AuthContext = createContext<AuthValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { data, error, isLoading, mutate } = useSWR<CurrentUser, ApiError>(
    "/api/auth/me",
    getMe,
    { shouldRetryOnError: false, revalidateOnFocus: false },
  );

  const login = useCallback(
    async (email: string, password: string) => {
      await apiLogin(email, password);
      const me = await getMe();
      await mutate(me, { revalidate: false });
      return me;
    },
    [mutate],
  );

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } finally {
      await mutate(undefined, { revalidate: false });
    }
  }, [mutate]);

  const value = useMemo<AuthValue>(
    () => ({
      user: data ?? null,
      isLoading,
      error: error ?? null,
      login,
      logout,
      refresh: () => mutate(),
    }),
    [data, isLoading, error, login, logout, mutate],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within <AuthProvider>");
  }
  return ctx;
}
