import { useWebSocket } from '@/hooks/useWebSocket';
import { Badge } from '@/components/ui/badge';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { truncate, relativeTime } from '@/lib/utils';

export function LiveFeed() {
  const { messages, isConnected, clear } = useWebSocket();

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between py-3">
        <CardTitle className="text-base">Live Event Feed</CardTitle>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-pass animate-pulse' : 'bg-muted-foreground'}`} />
          <span className="text-xs text-muted-foreground">{messages.length} events</span>
          {messages.length > 0 && (
            <button onClick={clear} className="text-xs text-muted-foreground hover:text-foreground">Clear</button>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0 max-h-96 overflow-y-auto">
        {messages.length === 0 ? (
          <div className="p-8 text-center text-muted-foreground text-sm">
            {isConnected ? 'Waiting for events...' : 'WebSocket disconnected'}
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={`${msg.session_id}-${msg.timestamp}-${i}`}
              className="flex items-center gap-3 px-4 py-2.5 border-b hover:bg-accent/50 text-sm"
            >
              <Badge variant={msg.decision === 'kill' ? 'kill' : msg.decision === 'warn' ? 'warn' : 'pass'}>
                {msg.decision}
              </Badge>
              <span className="text-muted-foreground font-mono text-xs w-20 shrink-0">
                {msg.session_id?.slice(0, 8)}
              </span>
              <span className="flex-1 truncate">{truncate(msg.input_text, 80)}</span>
              {msg.violation_type && (
                <Badge variant="outline" className="text-xs">{msg.violation_type}</Badge>
              )}
              <span className="text-xs text-muted-foreground shrink-0">{relativeTime(msg.timestamp)}</span>
            </div>
          ))
        )}
      </CardContent>
    </Card>
  );
}
