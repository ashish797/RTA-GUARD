import { Card, CardContent } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { LucideIcon } from 'lucide-react';

interface StatCardProps {
  icon: LucideIcon;
  label: string;
  value: number | string;
  color?: 'kill' | 'warn' | 'pass' | 'info';
  subtitle?: string;
}

export function StatCard({ icon: Icon, label, value, color = 'info', subtitle }: StatCardProps) {
  const colorMap = { kill: 'text-kill', warn: 'text-warn', pass: 'text-pass', info: 'text-info' };
  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className={cn('text-3xl font-bold mt-1', colorMap[color])}>{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          <div className={cn('p-3 rounded-lg', {
            'bg-kill/10': color === 'kill',
            'bg-warn/10': color === 'warn',
            'bg-pass/10': color === 'pass',
            'bg-info/10': color === 'info',
          })}>
            <Icon className={cn('w-6 h-6', colorMap[color])} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
