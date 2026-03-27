import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { conscienceApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DriftGauge } from '@/components/DriftGauge';
import { HealthBadge } from '@/components/HealthBadge';
import { LoadingSpinner } from '@/components/Loading';
import { Brain, AlertTriangle, Clock, Users, Eye } from 'lucide-react';

export default function ConsciencePage() {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const { data: agents, isLoading } = useQuery({
    queryKey: ['conscience-agents'],
    queryFn: () => conscienceApi.agents(),
    refetchInterval: 10000,
  });

  const { data: drift } = useQuery({
    queryKey: ['drift', selectedAgent],
    queryFn: () => conscienceApi.drift(selectedAgent!),
    enabled: !!selectedAgent,
  });

  const { data: anomaly } = useQuery({
    queryKey: ['anomaly', selectedAgent],
    queryFn: () => conscienceApi.anomaly(selectedAgent!),
    enabled: !!selectedAgent,
  });

  const { data: tamas } = useQuery({
    queryKey: ['tamas', selectedAgent],
    queryFn: () => conscienceApi.tamas(selectedAgent!),
    enabled: !!selectedAgent,
  });

  const { data: temporal } = useQuery({
    queryKey: ['temporal', selectedAgent],
    queryFn: () => conscienceApi.temporal(selectedAgent!),
    enabled: !!selectedAgent,
  });

  const { data: users } = useQuery({
    queryKey: ['conscience-users'],
    queryFn: () => conscienceApi.users(),
    refetchInterval: 15000,
  });

  if (isLoading) return <LoadingSpinner />;

  const agentList = agents?.agents || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Brain className="w-6 h-6 text-info" /> Conscience Monitor</h1>
        <p className="text-muted-foreground">Agent health, drift, and anomaly detection</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-1">
          <CardHeader><CardTitle className="text-base">Agents ({agentList.length})</CardTitle></CardHeader>
          <CardContent className="p-0 max-h-[600px] overflow-y-auto">
            {agentList.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">No agents registered</div>
            ) : (
              agentList.map((agent) => (
                <button key={agent.agent_id}
                  onClick={() => setSelectedAgent(agent.agent_id)}
                  className={`w-full text-left px-4 py-3 border-b hover:bg-accent/50 transition-colors ${
                    selectedAgent === agent.agent_id ? 'bg-accent' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-sm">{agent.agent_id}</span>
                    <HealthBadge level={agent.health || 'unknown'} />
                  </div>
                  {agent.drift_score !== undefined && (
                    <div className="mt-1 text-xs text-muted-foreground">
                      Drift: {(agent.drift_score * 100).toFixed(0)}%
                    </div>
                  )}
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <div className="lg:col-span-2 space-y-4">
          {!selectedAgent ? (
            <Card>
              <CardContent className="p-12 text-center text-muted-foreground">
                Select an agent to view details
              </CardContent>
            </Card>
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <Card>
                  <CardContent className="p-4 flex flex-col items-center">
                    <DriftGauge score={drift?.score ?? 0} label="Drift Score" />
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <AlertTriangle className="w-4 h-4 text-warn" />
                      <span className="font-medium text-sm">Anomaly</span>
                    </div>
                    {anomaly ? (
                      <div className="space-y-1">
                        <Badge variant={anomaly.is_anomalous ? 'kill' : 'pass'}>
                          {anomaly.is_anomalous ? 'DETECTED' : 'NONE'}
                        </Badge>
                        <p className="text-xs text-muted-foreground">{anomaly.anomaly_type}</p>
                        <p className="text-xs">{anomaly.detail}</p>
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">Loading...</p>
                    )}
                  </CardContent>
                </Card>
                <Card>
                  <CardContent className="p-4">
                    <div className="flex items-center gap-2 mb-2">
                      <Clock className="w-4 h-4 text-muted-foreground" />
                      <span className="font-medium text-sm">Tamas Level</span>
                    </div>
                    {tamas ? (
                      <pre className="text-xs overflow-auto max-h-24">{JSON.stringify(tamas, null, 2)}</pre>
                    ) : (
                      <p className="text-xs text-muted-foreground">Loading...</p>
                    )}
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader><CardTitle className="text-base">Temporal Consistency</CardTitle></CardHeader>
                <CardContent>
                  {temporal ? (
                    <pre className="text-xs overflow-auto max-h-40">{JSON.stringify(temporal, null, 2)}</pre>
                  ) : (
                    <p className="text-sm text-muted-foreground">Loading...</p>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Users className="w-4 h-4" /> Tracked Users ({users?.total || 0})</CardTitle></CardHeader>
        <CardContent className="p-0">
          {!users || users.users.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No tracked users</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="p-3">User ID</th>
                    <th className="p-3">Sessions</th>
                    <th className="p-3">Last Active</th>
                    <th className="p-3">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {users.users.map((u, i) => (
                    <tr key={i} className="border-b hover:bg-accent/50">
                      <td className="p-3 font-mono">{u.user_id || u.id}</td>
                      <td className="p-3">{u.sessions_count || u.session_count || '—'}</td>
                      <td className="p-3 text-muted-foreground">{u.last_active || '—'}</td>
                      <td className="p-3"><HealthBadge level={u.status || u.health || 'unknown'} /></td>
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
