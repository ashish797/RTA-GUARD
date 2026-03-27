import { cn, healthColor } from '@/lib/utils';

interface HealthBadgeProps {
  level: string;
  className?: string;
}

export function HealthBadge({ level, className }: HealthBadgeProps) {
  const dot = level?.toLowerCase() === 'healthy' ? 'bg-pass' :
    level?.toLowerCase() === 'degraded' ? 'bg-warn' : 'bg-kill';

  return (
    <span className={cn('inline-flex items-center gap-1.5 text-sm', healthColor(level), className)}>
      <span className={cn('w-2 h-2 rounded-full', dot)} />
      {level || 'Unknown'}
    </span>
  );
}
