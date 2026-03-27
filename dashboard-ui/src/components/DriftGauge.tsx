import { cn } from '@/lib/utils';

interface DriftGaugeProps {
  score: number;
  label?: string;
  size?: number;
}

export function DriftGauge({ score, label, size = 120 }: DriftGaugeProps) {
  const clamped = Math.max(0, Math.min(1, score));
  const pct = Math.round(clamped * 100);
  const angle = -90 + clamped * 180;
  const color = clamped < 0.3 ? '#00ff88' : clamped < 0.6 ? '#f5a623' : '#e94560';
  const level = clamped < 0.3 ? 'HEALTHY' : clamped < 0.6 ? 'DEGRADED' : clamped < 0.8 ? 'UNHEALTHY' : 'CRITICAL';

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size / 2 + 20} viewBox="0 0 120 80">
        <path d="M 10 70 A 50 50 0 0 1 110 70" fill="none" stroke="hsl(var(--muted))" strokeWidth="8" strokeLinecap="round" />
        <path d="M 10 70 A 50 50 0 0 1 110 70" fill="none" stroke={color} strokeWidth="8"
          strokeLinecap="round" strokeDasharray={`${clamped * 157} 157`}
          className="transition-all duration-700"
        />
        <line x1="60" y1="70" x2={60 + 35 * Math.cos((angle * Math.PI) / 180)}
          y2={70 - 35 * Math.sin((-angle * Math.PI) / 180)}
          stroke={color} strokeWidth="2" strokeLinecap="round"
          className="transition-all duration-500"
        />
        <text x="60" y="65" textAnchor="middle" fill={color} fontSize="18" fontWeight="bold">{pct}%</text>
      </svg>
      {label && <span className="text-xs text-muted-foreground mt-1">{label}</span>}
      <span className={cn('text-xs font-semibold mt-0.5')} style={{ color }}>{level}</span>
    </div>
  );
}
