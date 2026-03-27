import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { conscienceApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { DriftGauge } from '@/components/DriftGauge';
import { LoadingSpinner } from '@/components/Loading';
import { TrendingUp, BarChart3 } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell } from 'recharts';

const COLORS = ['#4ecdc4', '#e94560', '#f5a623', '#9b59b6', '#3498db', '#2ecc71', '#e67e22', '#1abc9c'];

export default function DriftPage() {
  const qc = useQueryClient();
  const [selectedAgent, setSelectedAgent] = useState('');
  const [recordForm, setRecordForm] = useState({ agent_id: '', session_id: '', score: '0' });

  const { data: agents, isLoading } = useQuery({
    queryKey: ['conscience-agents'],
    queryFn: () => conscienceApi.agents(),
  });

  const { data: driftComponents } = useQuery({
    queryKey: ['drift-components', selectedAgent],
    queryFn: () => conscienceApi.driftComponents(selectedAgent),
    enabled: !!selectedAgent,
  });

  const recordMutation = useMutation({
    mutationFn: () => conscienceApi.driftRecord({
      agent_id: recordForm.agent_id,
      session_id: recordForm.session_id,
      score: parseFloat(recordForm.score),
      components: {},
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conscience-agents'] }),
  });

  if (isLoading) return <LoadingSpinner />;

  const agentList = agents?.agents || [];

  const componentData = driftComponents ? Object.entries(driftComponents.components).map(([name, value]) => ({
    name, value: Math.round(value * 100),
  })) : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><TrendingUp className="w-6 h-6 text-info" /> Drift Analysis</h1>
        <p className="text-muted-foreground">Behavioral drift monitoring and component breakdown</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Agent Selector</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            {agentList.length === 0 ? (
              <p className="text-sm text-muted-foreground">No agents available</p>
            ) : (
              agentList.map((agent) => (
                <button key={agent.agent_id}
                  onClick={() => setSelectedAgent(agent.agent_id)}
                  className={`w-full text-left p-3 rounded-lg border text-sm transition-colors ${
                    selectedAgent === agent.agent_id ? 'bg-accent border-primary' : 'hover:bg-accent/50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono">{agent.agent_id}</span>
                    <Badge variant={agent.health === 'healthy' ? 'pass' : agent.health === 'degraded' ? 'warn' : 'kill'}>
                      {agent.drift_score !== undefined ? `${(agent.drift_score * 100).toFixed(0)}%` : '—'}
                    </Badge>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <div className="lg:col-span-2 space-y-4">
          {!selectedAgent ? (
            <Card>
              <CardContent className="p-12 text-center text-muted-foreground">Select an agent to analyze drift</CardContent>
            </Card>
          ) : !driftComponents ? (
            <LoadingSpinner />
          ) : (
            <>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Card>
                  <CardContent className="p-6 flex flex-col items-center">
                    <DriftGauge score={driftComponents.overall_score} label="Overall Drift" size={160} />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader><CardTitle className="text-base">Component Breakdown</CardTitle></CardHeader>
                  <CardContent className="h-48">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={componentData} layout="vertical" margin={{ left: 80 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                        <XAxis type="number" domain={[0, 100]} stroke="hsl(var(--muted-foreground))" fontSize={11} />
                        <YAxis type="category" dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={10} />
                        <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
                        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                          {componentData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </CardContent>
                </Card>
              </div>

              <Card>
                <CardHeader><CardTitle className="text-base">Record Drift</CardTitle></CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-3">
                    <Input placeholder="Agent ID" value={recordForm.agent_id} onChange={(e) => setRecordForm({ ...recordForm, agent_id: e.target.value })} className="w-40" />
                    <Input placeholder="Session ID" value={recordForm.session_id} onChange={(e) => setRecordForm({ ...recordForm, session_id: e.target.value })} className="w-40" />
                    <Input placeholder="Score (0-1)" type="number" step="0.01" min="0" max="1" value={recordForm.score}
                      onChange={(e) => setRecordForm({ ...recordForm, score: e.target.value })} className="w-28" />
                    <Button onClick={() => recordMutation.mutate()} disabled={recordMutation.isPending}>
                      {recordMutation.isPending ? 'Recording...' : 'Record'}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
