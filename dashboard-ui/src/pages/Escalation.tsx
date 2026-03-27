import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { escalationApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/Loading';
import { Bug, Play, History, Settings } from 'lucide-react';

export default function EscalationPage() {
  const [agentId, setAgentId] = useState('');
  const [evalAgent, setEvalAgent] = useState('');

  const { data: history, isLoading } = useQuery({
    queryKey: ['escalation-history'],
    queryFn: () => escalationApi.history(100),
    refetchInterval: 10000,
  });

  const { data: config } = useQuery({
    queryKey: ['escalation-config'],
    queryFn: () => escalationApi.config(),
  });

  const { data: agentStatus } = useQuery({
    queryKey: ['escalation-status', agentId],
    queryFn: () => escalationApi.status(agentId),
    enabled: !!agentId,
  });

  const evalMutation = useMutation({
    mutationFn: () => escalationApi.evaluate(evalAgent),
  });

  if (isLoading) return <LoadingSpinner />;

  const levelColor = (level: string) => {
    switch (level) {
      case 'KILL': return 'kill';
      case 'ALERT': return 'kill';
      case 'THROTTLE': return 'warn';
      case 'WARN': return 'warn';
      default: return 'pass';
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Bug className="w-6 h-6 text-kill" /> Escalation</h1>
        <p className="text-muted-foreground">Automated escalation policies and history</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Check Agent Status</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Agent ID" value={agentId} onChange={(e) => setAgentId(e.target.value)} />
            {agentStatus && (
              <div className="p-3 rounded-lg border bg-muted/30">
                <div className="flex items-center gap-2 mb-2">
                  <Badge variant={levelColor(agentStatus.level) as any}>{agentStatus.level}</Badge>
                  <span className="text-sm">Score: {(agentStatus.aggregate_score * 100).toFixed(0)}%</span>
                </div>
                {agentStatus.reasons.length > 0 && (
                  <ul className="text-xs text-muted-foreground space-y-1">
                    {agentStatus.reasons.map((r, i) => <li key={i}>• {r}</li>)}
                  </ul>
                )}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Play className="w-4 h-4" /> Evaluate</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Agent ID to evaluate" value={evalAgent} onChange={(e) => setEvalAgent(e.target.value)} />
            <Button onClick={() => evalMutation.mutate()} disabled={!evalAgent || evalMutation.isPending} className="w-full">
              {evalMutation.isPending ? 'Evaluating...' : 'Run Evaluation'}
            </Button>
            {evalMutation.data && (
              <div className="p-3 rounded-lg border bg-muted/30">
                <Badge variant={levelColor(evalMutation.data.level) as any}>{evalMutation.data.level}</Badge>
                <p className="text-xs mt-2 text-muted-foreground">
                  Score: {(evalMutation.data.aggregate_score * 100).toFixed(0)}%
                </p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Settings className="w-4 h-4" /> Config</CardTitle></CardHeader>
          <CardContent>
            {config ? (
              <pre className="text-xs overflow-auto max-h-48">{JSON.stringify(config, null, 2)}</pre>
            ) : (
              <p className="text-sm text-muted-foreground">Loading config...</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><History className="w-4 h-4" /> Escalation History</CardTitle></CardHeader>
        <CardContent className="p-0">
          {!history || history.history.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No escalation events</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="p-3">Level</th>
                    <th className="p-3">Score</th>
                    <th className="p-3">Reasons</th>
                    <th className="p-3">Triggered Rules</th>
                  </tr>
                </thead>
                <tbody>
                  {history.history.map((h, i) => (
                    <tr key={i} className="border-b hover:bg-accent/50">
                      <td className="p-3"><Badge variant={levelColor(h.level) as any}>{h.level}</Badge></td>
                      <td className="p-3">{(h.aggregate_score * 100).toFixed(0)}%</td>
                      <td className="p-3 text-xs text-muted-foreground">{h.reasons?.join(', ') || '—'}</td>
                      <td className="p-3 text-xs">{h.triggered_rules?.join(', ') || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
