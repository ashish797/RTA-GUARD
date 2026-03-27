import * as React from 'react';
import { cn } from '@/lib/utils';

export const Badge = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'kill' | 'warn' | 'pass';
}>(({ className, variant = 'default', ...props }, ref) => {
  const variants: Record<string, string> = {
    default: 'bg-primary text-primary-foreground',
    secondary: 'bg-secondary text-secondary-foreground',
    destructive: 'bg-destructive text-destructive-foreground',
    outline: 'border border-input text-foreground',
    kill: 'bg-kill/15 text-kill border border-kill/30',
    warn: 'bg-warn/15 text-warn border border-warn/30',
    pass: 'bg-pass/15 text-pass border border-pass/30',
  };
  return (
    <div
      ref={ref}
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors',
        variants[variant], className
      )}
      {...props}
    />
  );
});
Badge.displayName = 'Badge';
