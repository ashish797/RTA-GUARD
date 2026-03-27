import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { guardApi } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { LoadingSpinner } from '@/components/Loading';
import { Trash2, RefreshCw, Search, Eye } from 'lucide-react';

export default function SessionsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState('');
  const [selectedSession, setSelectedSession] = useState<string | null>(null);

  const { data: killed, isLoading } = useQuery({
    queryKey: ['killed'],
    queryFn: () => guardApi.killed(),
    refetchInterval: 5000,
  });

  const { data: sessionEvents } = useQuery({
    queryKey: ['session-events', selectedSession],
    queryFn: () => guardApi.events(selectedSession!),
    enabled: !!selectedSession,
  });

  const resetMutation = useMutation({
    mutationFn: (sid: string) => guardApi.reset(sid),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['killed'] });
      qc.invalidateQueries({ queryKey: ['stats'] });
    },
  });

  if (isLoading) return <LoadingSpinner />;

  const sessions = (killed?.killed_sessions || []).filter((s) => !search || s.includes(search));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Sessions</h1>
        <p className="text-muted-foreground">{killed?.total || 0} killed sessions</p>
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input placeholder="Search session ID..." value={search} onChange={(e) => setSearch(e.target.value)} className="pl-9" />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Killed Sessions</CardTitle></CardHeader>
          <CardContent className="p-0 max-h-[600px] overflow-y-auto">
            {sessions.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">No killed sessions</div>
            ) : (
              sessions.map((sid) => (
                <div key={sid} className="flex items-center justify-between px-4 py-3 border-b hover:bg-accent/50">
                  <div className="flex items-center gap-3">
                    <Badge variant="kill">KILLED</Badge>
                    <span className="font-mono text-sm">{sid}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setSelectedSession(sid)}>
                      <Eye className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => resetMutation.mutate(sid)}
                      disabled={resetMutation.isPending}>
                      <RefreshCw className="w-4 h-4" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              {selectedSession ? `Session: ${selectedSession.slice(0, 16)}...` : 'Select a session'}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 max-h-[600px] overflow-y-auto">
            {!selectedSession ? (
              <div className="p-8 text-center text-muted-foreground">Click the eye icon to view session events</div>
            ) : !sessionEvents ? (
              <LoadingSpinner />
            ) : sessionEvents.events.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">No events for this session</div>
            ) : (
              sessionEvents.events.map((event, i) => (
                <div key={i} className="px-4 py-3 border-b text-sm">
                  <div className="flex items-center gap-2 mb-1">
                    <Badge variant={event.decision === 'kill' ? 'kill' : event.decision === 'warn' ? 'warn' : 'pass'}>
                      {event.decision}
                    </Badge>
                    {event.violation_type && <Badge variant="outline">{event.violation_type}</Badge>}
                  </div>
                  <p className="text-muted-foreground truncate">{event.input_text}</p>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
