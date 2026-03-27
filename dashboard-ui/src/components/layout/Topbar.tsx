import { useAuth } from '@/context/AuthContext';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { LogOut, Moon, Sun, Wifi, WifiOff } from 'lucide-react';
import { useState, useEffect } from 'react';

interface TopbarProps {
  wsConnected?: boolean;
}

export function Topbar({ wsConnected = false }: TopbarProps) {
  const { logout } = useAuth();
  const [dark, setDark] = useState(true);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);

  return (
    <header className="flex items-center justify-between px-6 py-3 border-b bg-card">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-muted-foreground">AI Agent Security Dashboard</h1>
      </div>

      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 text-sm">
          {wsConnected ? (
            <><Wifi className="w-4 h-4 text-pass" /><Badge variant="pass">Live</Badge></>
          ) : (
            <><WifiOff className="w-4 h-4 text-muted-foreground" /><Badge variant="outline">Offline</Badge></>
          )}
        </div>

        <button
          onClick={() => setDark(!dark)}
          className="p-2 rounded-md hover:bg-accent text-muted-foreground"
        >
          {dark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>

        <Button variant="ghost" size="sm" onClick={logout}>
          <LogOut className="w-4 h-4 mr-2" /> Logout
        </Button>
      </div>
    </header>
  );
}
