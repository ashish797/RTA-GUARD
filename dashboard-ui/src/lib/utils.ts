import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatTimestamp(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export function relativeTime(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    const diff = Date.now() - new Date(ts).getTime();
    if (diff < 60000) return 'just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
  } catch {
    return ts;
  }
}

export function decisionColor(decision: string): string {
  switch (decision) {
    case 'kill': return 'text-kill';
    case 'warn': return 'text-warn';
    case 'pass': return 'text-pass';
    default: return 'text-muted-foreground';
  }
}

export function decisionBg(decision: string): string {
  switch (decision) {
    case 'kill': return 'bg-kill/15 text-kill border-kill/30';
    case 'warn': return 'bg-warn/15 text-warn border-warn/30';
    case 'pass': return 'bg-pass/15 text-pass border-pass/30';
    default: return 'bg-muted text-muted-foreground';
  }
}

export function healthColor(level: string): string {
  switch (level?.toLowerCase()) {
    case 'healthy': return 'text-pass';
    case 'degraded': return 'text-warn';
    case 'unhealthy': return 'text-kill';
    case 'critical': return 'text-kill font-bold';
    default: return 'text-muted-foreground';
  }
}

export function truncate(str: string, len = 60): string {
  return str.length > len ? str.slice(0, len) + '…' : str;
}
