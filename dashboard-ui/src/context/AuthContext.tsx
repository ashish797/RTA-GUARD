import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';
import { authApi } from '@/lib/api';

interface AuthContextType {
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  authEnabled: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType>({
  token: null,
  isAuthenticated: false,
  isLoading: true,
  authEnabled: true,
  login: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(localStorage.getItem('rta-guard-token'));
  const [isLoading, setIsLoading] = useState(true);
  const [authEnabled, setAuthEnabled] = useState(true);

  useEffect(() => {
    authApi.status()
      .then((s) => {
        setAuthEnabled(s.enabled);
        if (!s.enabled) {
          setToken('no-auth');
          localStorage.setItem('rta-guard-token', 'no-auth');
        }
      })
      .catch(() => setAuthEnabled(true))
      .finally(() => setIsLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await authApi.login(username, password);
    setToken(res.session_id);
    localStorage.setItem('rta-guard-token', res.session_id);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    localStorage.removeItem('rta-guard-token');
  }, []);

  return (
    <AuthContext.Provider value={{
      token,
      isAuthenticated: !!token,
      isLoading,
      authEnabled,
      login,
      logout,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
