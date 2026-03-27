import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { authApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/Loading';
import { Settings, Shield, Key, Plus, Trash2, Globe } from 'lucide-react';

export default function SettingsPage() {
  const qc = useQueryClient();
  const [ssoForm, setSsoForm] = useState({
    tenant_id: '', provider_name: '', client_id: '', client_secret: '', discovery_url: '',
  });
  const [showSsoForm, setShowSsoForm] = useState(false);

  const { data: authStatus, isLoading } = useQuery({
    queryKey: ['auth-status'],
    queryFn: () => authApi.status(),
  });

  const { data: ssoProviders } = useQuery({
    queryKey: ['sso-providers'],
    queryFn: () => authApi.ssoProviders(),
  });

  const createSsoMutation = useMutation({
    mutationFn: () => authApi.ssoCreateProvider(ssoForm),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sso-providers'] });
      setShowSsoForm(false);
      setSsoForm({ tenant_id: '', provider_name: '', client_id: '', client_secret: '', discovery_url: '' });
    },
  });

  const deleteSsoMutation = useMutation({
    mutationFn: (data: { tenant_id: string; provider_name: string }) => authApi.ssoDeleteProvider(data.tenant_id, data.provider_name),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sso-providers'] }),
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Settings className="w-6 h-6 text-info" /> Settings</h1>
        <p className="text-muted-foreground">Authentication and system configuration</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Shield className="w-4 h-4" /> Authentication</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between p-3 rounded-lg border">
              <span className="text-sm">Auth Enabled</span>
              <Badge variant={authStatus?.enabled ? 'pass' : 'secondary'}>
                {authStatus?.enabled ? 'Yes' : 'No'}
              </Badge>
            </div>
            <div className="flex items-center justify-between p-3 rounded-lg border">
              <span className="text-sm">API Token Configured</span>
              <Badge variant={authStatus?.token_set ? 'pass' : 'warn'}>
                {authStatus?.token_set ? 'Yes' : 'No'}
              </Badge>
            </div>
            <div className="p-3 rounded-lg bg-muted/30 text-xs text-muted-foreground">
              <p>Current token stored in browser localStorage as <code className="bg-background px-1 rounded">rta-guard-token</code>.</p>
              <p className="mt-1">Set <code className="bg-background px-1 rounded">DASHBOARD_TOKEN</code> env var on the server to configure.</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Globe className="w-4 h-4" /> SSO Providers
              <Button size="sm" variant="ghost" onClick={() => setShowSsoForm(!showSsoForm)} className="ml-auto">
                <Plus className="w-3 h-3 mr-1" /> Add
              </Button>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {showSsoForm && (
              <div className="p-3 rounded-lg border space-y-2">
                <Input placeholder="Tenant ID" value={ssoForm.tenant_id} onChange={(e) => setSsoForm({ ...ssoForm, tenant_id: e.target.value })} />
                <Input placeholder="Provider Name" value={ssoForm.provider_name} onChange={(e) => setSsoForm({ ...ssoForm, provider_name: e.target.value })} />
                <Input placeholder="Client ID" value={ssoForm.client_id} onChange={(e) => setSsoForm({ ...ssoForm, client_id: e.target.value })} />
                <Input placeholder="Client Secret" type="password" value={ssoForm.client_secret} onChange={(e) => setSsoForm({ ...ssoForm, client_secret: e.target.value })} />
                <Input placeholder="Discovery URL" value={ssoForm.discovery_url} onChange={(e) => setSsoForm({ ...ssoForm, discovery_url: e.target.value })} />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => createSsoMutation.mutate()} disabled={createSsoMutation.isPending}>
                    {createSsoMutation.isPending ? 'Creating...' : 'Create'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setShowSsoForm(false)}>Cancel</Button>
                </div>
              </div>
            )}
            {!ssoProviders || ssoProviders.providers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">No SSO providers configured</p>
            ) : (
              ssoProviders.providers.map((p) => (
                <div key={`${p.tenant_id}-${p.provider_name}`} className="flex items-center justify-between p-3 rounded-lg border">
                  <div>
                    <p className="text-sm font-medium">{p.provider_name}</p>
                    <p className="text-xs text-muted-foreground">Tenant: {p.tenant_id}</p>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => deleteSsoMutation.mutate({ tenant_id: p.tenant_id, provider_name: p.provider_name })}>
                    <Trash2 className="w-3 h-3 text-kill" />
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Key className="w-4 h-4" /> API Info</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
            <div className="p-3 rounded-lg border">
              <p className="text-xs text-muted-foreground">API Base URL</p>
              <p className="font-mono">{import.meta.env.VITE_API_URL || window.location.origin}</p>
            </div>
            <div className="p-3 rounded-lg border">
              <p className="text-xs text-muted-foreground">WebSocket URL</p>
              <p className="font-mono">{import.meta.env.VITE_WS_URL || `ws://${window.location.hostname}:8000/ws`}</p>
            </div>
            <div className="p-3 rounded-lg border">
              <p className="text-xs text-muted-foreground">Dashboard Version</p>
              <p className="font-mono">2.0.0 (Phase 8)</p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
