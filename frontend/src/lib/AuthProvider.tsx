"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  configureAuth,
  currentUser,
  isAuthConfigured,
  loginAccount,
  logoutAccount,
  SessionUser,
} from "./auth";

type AuthContextValue = {
  configured: boolean;
  ready: boolean;
  user: SessionUser | null;
  refresh: () => Promise<SessionUser | null>;
  login: (email: string, password: string) => Promise<SessionUser>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue>({
  configured: false,
  ready: false,
  user: null,
  refresh: async () => null,
  login: async () => {
    throw new Error("Auth is not ready");
  },
  logout: async () => undefined,
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const configured = isAuthConfigured();
  const [ready, setReady] = useState(false);
  const [user, setUser] = useState<SessionUser | null>(null);

  const refresh = useCallback(async () => {
    configureAuth();
    const next = await currentUser();
    setUser(next);
    setReady(true);
    return next;
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      await loginAccount(email, password);
      const next = await refresh();
      if (!next) {
        throw new Error("Cognito accepted the password, but the session did not load. Refresh the page.");
      }
      return next;
    },
    [refresh],
  );

  const logout = useCallback(async () => {
    await logoutAccount();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ configured, ready, user, refresh, login, logout }),
    [configured, ready, user, refresh, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
