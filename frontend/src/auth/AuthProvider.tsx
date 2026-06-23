// src/auth/AuthProvider.tsx
import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "../lib/api";

type User = { username: string };
type AuthCtx = {
  user: User | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
  const token = localStorage.getItem("admin_token");

  if (!token) {
    setLoading(false);
    return;
  }

  api.get("/auth/me")
    .then(res => setUser(res.data?.user ?? null))
    .catch(() => {
      localStorage.removeItem("admin_token");
      setUser(null);
    })
    .finally(() => setLoading(false));
}, []);

  const login = async (username: string, password: string) => {
  const res = await api.post("/auth/login", {
    username,
    password,
  });

  localStorage.setItem(
    "admin_token",
    res.data.token
  );

  setUser(res.data.user);
};

  const logout = async () => {
  localStorage.removeItem("admin_token");
  setUser(null);
};

  return <Ctx.Provider value={{ user, loading, login, logout }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
