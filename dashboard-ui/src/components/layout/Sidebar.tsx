import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils';
import {
  LayoutDashboard, Shield, AlertTriangle, Activity, Users, Key,
  Webhook, Globe, FileText, Settings, Zap, ChevronLeft, ChevronRight,
  Brain, TrendingUp, Bug,
} from 'lucide-react';
import { useState } from 'react';

const nav = [
  { to: '/', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/events', icon: Shield, label: 'Events' },
  { to: '/sessions', icon: AlertTriangle, label: 'Sessions' },
  { to: '/check', icon: Zap, label: 'Rules & Check' },
  { to: '/conscience', icon: Brain, label: 'Conscience' },
  { to: '/drift', icon: TrendingUp, label: 'Drift Analysis' },
  { to: '/escalation', icon: Bug, label: 'Escalation' },
  { to: '/tenants', icon: Globe, label: 'Tenants' },
  { to: '/rbac', icon: Key, label: 'RBAC' },
  { to: '/webhooks', icon: Webhook, label: 'Webhooks' },
  { to: '/brahmanda', icon: Activity, label: 'Brahmanda' },
  { to: '/reports', icon: FileText, label: 'Reports' },
  { to: '/sla', icon: Users, label: 'SLA & Limits' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false);
  const location = useLocation();

  return (
    <aside className={cn(
      'flex flex-col border-r bg-card transition-all duration-200',
      collapsed ? 'w-16' : 'w-64'
    )}>
      <div className="flex items-center justify-between p-4 border-b">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-kill/20 flex items-center justify-center">
              <Shield className="w-5 h-5 text-kill" />
            </div>
            <span className="font-bold text-lg">RTA-GUARD</span>
          </div>
        )}
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded-md hover:bg-accent text-muted-foreground"
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {nav.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) => cn(
              'flex items-center gap-3 px-4 py-2.5 text-sm transition-colors',
              isActive
                ? 'bg-kill/10 text-kill border-r-2 border-kill'
                : 'text-muted-foreground hover:text-foreground hover:bg-accent',
              collapsed && 'justify-center px-0'
            )}
            end={to === '/'}
          >
            <Icon className="w-5 h-5 shrink-0" />
            {!collapsed && <span>{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t text-xs text-muted-foreground text-center">
        {!collapsed && 'RTA-GUARD v2.0'}
      </div>
    </aside>
  );
}
