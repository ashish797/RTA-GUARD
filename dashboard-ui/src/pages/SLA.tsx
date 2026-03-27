import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { slaApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { StatCard } from '@/components/StatCard';
import { LoadingSpinner } from '@/components/Loading';
import { Activity, Clock, AlertTriangle, Zap, Settings } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export default function SLAPage() {
  const qc = useQueryClient();
  const [rateForm, setRateForm] = useState({ tenant_id: '', rpm: '100', burst: '20' });

  const { data: slaStatus, isLoading } = useQuery({
    queryKey: ['sla-status'],
    queryFn: () => slaApi.status(),
    refetchInterval: 10000,
  });

  const { data: slaStats } = useQuery({
    queryKey: ['sla-stats'],
    queryFn: () => slaApi.stats(),
    refetchInterval: 10000,
  });

  const { data: breaches } = useQuery({
    queryKey: ['sla-breaches'],
    queryFn: () => slaApi.breaches(),
    refetchInterval: 15000,
  });

  const { data: rateLimit } = useQuery({
    queryKey: ['rate-limit'],
    queryFn: () => slaApi.rateLimitStatus(),
  });

  const configureMutation = useMutation({
    mutationFn: () => slaApi.rateLimitConfigure(rateForm.tenant_id, parseInt(rateForm.rpm), parseInt(rateForm.burst)),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rate-limit'] }),
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Activity className="w-6 h-6 text-info" /> SLA & Rate Limiting</h1>
        <p className="text-muted-foreground">Service level monitoring and rate limit configuration</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={Activity} label="Uptime" value={slaStatus ? `${slaStatus.uptime.toFixed(2)}%` : '—'} color="pass" />
        <StatCard icon={Clock} label="P50 Response" value={slaStatus ? `${slaStatus.response_time_p50.toFixed(1)}ms` : '—'} color="info" />
        <StatCard icon={Clock} label="P99 Response" value={slaStatus ? `${slaStatus.response_time_p99.toFixed(1)}ms` : '—'} color="warn" />
        <StatCard icon={Zap} label="Kill Rate" value={slaStatus ? `${slaStatus.kill_rate.toFixed(1)}%` : '—'} color="kill" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">SLA Stats</CardTitle></CardHeader>
          <CardContent>
            {slaStats ? (
              <div className="grid grid-cols-2 gap-4">
                <div className="p-3 rounded-lg border">
                  <p className="text-xs text-muted-foreground">Total Requests</p>
                  <p className="text-2xl font-bold">{slaStats.total_requests}</p>
                </div>
                <div className="p-3 rounded-lg border">
                  <p className="text-xs text-muted-foreground">Total Breaches</p>
                  <p className="text-2xl font-bold text-warn">{slaStats.total_breaches}</p>
                </div>
                <div className="p-3 rounded-lg border">
                  <p className="text-xs text-muted-foreground">Breach Rate</p>
                  <p className="text-2xl font-bold">{(slaStats.breach_rate * 100).toFixed(2)}%</p>
                </div>
                <div className="p-3 rounded-lg border">
                  <p className="text-xs text-muted-foreground">Avg Response</p>
                  <p className="text-2xl font-bold">{slaStats.avg_response_time.toFixed(1)}ms</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No stats available</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Settings className="w-4 h-4" /> Rate Limit Config</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Input placeholder="Tenant ID" value={rateForm.tenant_id} onChange={(e) => setRateForm({ ...rateForm, tenant_id: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Requests/min</label>
                <Input type="number" value={rateForm.rpm} onChange={(e) => setRateForm({ ...rateForm, rpm: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Burst Size</label>
                <Input type="number" value={rateForm.burst} onChange={(e) => setRateForm({ ...rateForm, burst: e.target.value })} />
              </div>
            </div>
            <Button onClick={() => configureMutation.mutate()} disabled={!rateForm.tenant_id || configureMutation.isPending}
              className="w-full">
              {configureMutation.isPending ? 'Configuring...' : 'Apply Rate Limit'}
            </Button>
            {rateLimit && (
              <div className="p-3 rounded-lg border bg-muted/30 text-xs">
                <p>Current: {rateLimit.requests_per_minute} rpm, burst: {rateLimit.burst_size}</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-warn" /> Recent Breaches</CardTitle></CardHeader>
        <CardContent className="p-0">
          {!breaches || breaches.breaches.length === 0 ? (
            <div className="p-8 text-center text-muted-foreground">No breaches recorded</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="p-3">Metric</th>
                    <th className="p-3">Value</th>
                    <th className="p-3">Threshold</th>
                    <th className="p-3">Timestamp</th>
                  </tr>
                </thead>
                <tbody>
                  {breaches.breaches.map((b, i) => (
                    <tr key={i} className="border-b hover:bg-accent/50">
                      <td className="p-3 font-mono">{b.metric_name || b.metric || '—'}</td>
                      <td className="p-3 text-warn">{b.value || '—'}</td>
                      <td className="p-3">{b.threshold || '—'}</td>
                      <td className="p-3 text-muted-foreground">{b.timestamp || '—'}</td>
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
