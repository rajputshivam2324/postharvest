import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api, setSession } from './api/client';
import type { LoginOut, UserOut } from './api/types';

interface Auth {
  user: UserOut | null;
  login: (userId: string, password: string) => Promise<void>;
  signup: (userId: string, password: string, role: 'operator' | 'vendor') => Promise<void>;
  logout: () => void;
}
const Context = createContext<Auth | null>(null);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserOut | null>(null);
  const [expires, setExpires] = useState<number | null>(null);
  const cache = useQueryClient();
  function logout() {
    setSession(null);
    setUser(null);
    setExpires(null);
    void cache.cancelQueries();
    cache.clear();
  }
  useEffect(() => {
    setSession(null, logout);
    return () => setSession(null);
  }, []);
  useEffect(() => {
    if (!expires) return;
    const timer = window.setTimeout(
      logout,
      Math.min(Math.max(0, expires - Date.now()), 2147483647),
    );
    return () => window.clearTimeout(timer);
  }, [expires]);
  async function login(userId: string, password: string) {
    // Older running API processes return only the token until they are restarted.
    const result = await api<Omit<LoginOut, 'user'> & { user?: UserOut | null }>('/auth/login', {
      method: 'POST',
      body: { user_id: userId, password },
    });
    setSession(result.access_token, logout);
    try {
      const current = result.user ?? (await api<UserOut>('/auth/me'));
      if (!current?.id || !current.active)
        throw new Error('Unable to load your account. Please try signing in again.');
      cache.clear();
      setUser(current);
      setExpires(Date.parse(result.expires_at));
    } catch (error) {
      logout();
      throw error;
    }
  }
  async function signup(userId: string, password: string, role: 'operator' | 'vendor') {
    await api<UserOut>('/auth/signup', {
      method: 'POST',
      body: { user_id: userId, password, role },
    });
    try {
      await login(userId, password);
    } catch {
      throw new Error(
        'Your account was created, but automatic sign-in failed. Please use the Sign in link below.',
      );
    }
  }
  return <Context.Provider value={{ user, login, signup, logout }}>{children}</Context.Provider>;
}
export function useAuth() {
  const value = useContext(Context);
  if (!value) throw new Error('AuthProvider required');
  return value;
}
