import { useState, useEffect, useRef, useCallback } from 'react';
import type { WSMessage } from '@/types';

const WS_URL = import.meta.env.VITE_WS_URL || `ws://${window.location.hostname}:8000/ws`;

export function useWebSocket() {
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number>();

  const connect = useCallback(() => {
    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setIsConnected(true);
      ws.onclose = () => {
        setIsConnected(false);
        reconnectTimer.current = window.setTimeout(connect, 3000);
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as WSMessage;
          setMessages((prev) => [data, ...prev].slice(0, 200));
        } catch { /* ignore parse errors */ }
      };
    } catch {
      reconnectTimer.current = window.setTimeout(connect, 5000);
    }
  }, []);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const clear = useCallback(() => setMessages([]), []);

  return { messages, isConnected, clear };
}
