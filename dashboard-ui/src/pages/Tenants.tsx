import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { tenantsApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LoadingSpinner } from '@/components/Loading';
import { Globe, Plus, Trash2, Activity, Eye } from 'lucide-react';

export default function TenantsPage() {
  const qc = useQueryClient();
  const [newName, setNewName] = useState('');
  const [newId, setNewId] = useState('');
  const [selectedTenant, setSelectedTenant] = useState<string | null>(null);

  const { data: tenants, isLoading } = useQuery({
    queryKey: ['tenants'],
    queryFn: () => tenantsApi.list(),
  });

  const { data: health } = useQuery({
    queryKey: ['tenant-health', selectedTenant],
    queryFn: () => tenantsApi.health(selectedTenant!),
    enabled: !!selectedTenant,
  });

  const createMutation = useMutation({
    mutationFn: () => tenantsApi.create(newName, newId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tenants'] }); setNewName(''); setNewId(''); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => tenantsApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tenants'] }),
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Globe className="w-6 h-6 text-info" /> Tenants</h1>
        <p className="text-muted-foreground">{tenants?.total || 0} tenants</p>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base flex items-center gap-2"><Plus className="w-4 h-4" /> Create Tenant</CardTitle></CardHeader>
        <CardContent>
          <div className="flex gap-3">
            <Input placeholder="Tenant Name" value={newName} onChange={(e) => setNewName(e.target.value)} className="w-48" />
            <Input placeholder="Tenant ID" value={newId} onChange={(e) => setNewId(e.target.value)} className="w-48" />
            <Button onClick={() => createMutation.mutate()} disabled={!newName || !newId || createMutation.isPending}>
              {createMutation.isPending ? 'Creating...' : 'Create'}
            </Button>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Tenant List</CardTitle></CardHeader>
          <CardContent className="p-0">
            {!tenants || tenants.tenants.length === 0 ? (
              <div className="p-8 text-center text-muted-foreground">No tenants</div>
            ) : (
              tenants.tenants.map((t) => (
                <div key={t.tenant_id} className="flex items-center justify-between px-4 py-3 border-b hover:bg-accent/50">
                  <div>
                    <p className="font-medium text-sm">{t.name || t.tenant_id}</p>
                    <p className="text-xs text-muted-foreground font-mono">{t.tenant_id}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="ghost" size="sm" onClick={() => setSelectedTenant(t.tenant_id)}>
                      <Activity className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => deleteMutation.mutate(t.tenant_id)}
                      disabled={deleteMutation.isPending}>
                      <Trash2 className="w-4 h-4 text-kill" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">{selectedTenant ? `Health: ${selectedTenant}` : 'Select a tenant'}</CardTitle></CardHeader>
          <CardContent>
            {!selectedTenant ? (
              <p className="text-sm text-muted-foreground text-center py-8">Click health icon to view details</p>
            ) : !health ? (
              <LoadingSpinner />
            ) : (
              <div className="space-y-3">
                {Object.entries(health.databases).map(([module, info]) => (
                  <div key={module} className="flex items-center justify-between p-3 rounded-lg border">
                    <span className="text-sm font-medium">{module}</span>
                    <Badge variant={info.status === 'healthy' ? 'pass' : info.status === 'degraded' ? 'warn' : 'kill'}>
                      {info.status}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
