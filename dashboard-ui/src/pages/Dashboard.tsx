import { useQuery } from '@tanstack/react-query';
import { guardApi } from '@/lib/api';
import { StatCard } from '@/components/StatCard';
import { ViolationChart, ViolationPieChart } from '@/components/ViolationChart';
import { LiveFeed } from '@/components/LiveFeed';
import { LoadingSpinner } from '@/components/Loading';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Shield, AlertTriangle, CheckCircle, Zap, Activity } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

export default function Dashboard() {
  const { data: stats, isLoading, error } = useQuery({
    queryKey: ['stats'],
    queryFn: () => guardApi.stats(),
    refetchInterval: 10000,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="text-kill">Error: {(error as Error).message}</div>;
  if (!stats) return null;

  const killRate = stats.total_events > 0 ? ((stats.total_kills / stats.total_events) * 100).toFixed(1) : '0';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground">Real-time overview of AI agent security</p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard icon={Activity} label="Total Events" value={stats.total_events} color="info" />
        <StatCard icon={Shield} label="Passed" value={stats.total_passes} color="pass" />
        <StatCard icon={AlertTriangle} label="Warnings" value={stats.total_warnings} color="warn" />
        <StatCard icon={Zap} label="Kills" value={stats.total_kills} color="kill" subtitle={`${killRate}% kill rate`} />
        <StatCard icon={Shield} label="Active Kills" value={stats.active_killed_sessions} color="kill" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ViolationChart data={stats.violation_types} />
        <Card>
          <CardHeader><CardTitle className="text-base">Violation Distribution</CardTitle></CardHeader>
          <CardContent className="h-64">
            <ViolationPieChart data={stats.violation_types} />
          </CardContent>
        </Card>
      </div>

      <LiveFeed />
    </div>
  );
}
