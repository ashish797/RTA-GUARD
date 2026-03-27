import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';

interface ViolationChartProps {
  data: Record<string, number>;
}

const COLORS = ['#e94560', '#f5a623', '#4ecdc4', '#9b59b6', '#3498db', '#2ecc71', '#e67e22'];

export function ViolationChart({ data }: ViolationChartProps) {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  if (entries.length === 0) {
    return (
      <Card>
        <CardHeader><CardTitle className="text-base">Violation Breakdown</CardTitle></CardHeader>
        <CardContent className="h-64 flex items-center justify-center text-muted-foreground">No violations yet</CardContent>
      </Card>
    );
  }

  const chartData = entries.map(([name, value]) => ({ name, value }));

  return (
    <Card>
      <CardHeader><CardTitle className="text-base">Violation Breakdown</CardTitle></CardHeader>
      <CardContent className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} layout="vertical" margin={{ left: 80 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis type="number" stroke="hsl(var(--muted-foreground))" fontSize={12} />
            <YAxis type="category" dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={11} />
            <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

export function ViolationPieChart({ data }: ViolationChartProps) {
  const entries = Object.entries(data).filter(([, v]) => v > 0);
  if (entries.length === 0) return null;
  const chartData = entries.map(([name, value]) => ({ name, value }));

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={chartData} cx="50%" cy="50%" innerRadius={40} outerRadius={70}
          paddingAngle={2} dataKey="value" label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
        >
          {chartData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
        </Pie>
        <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8 }} />
      </PieChart>
    </ResponsiveContainer>
  );
}
