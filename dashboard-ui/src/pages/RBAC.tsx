import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { rbacApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { LoadingSpinner } from '@/components/Loading';
import { Key, UserPlus, UserMinus, Search } from 'lucide-react';

export default function RBACPage() {
  const qc = useQueryClient();
  const [assignForm, setAssignForm] = useState({ user_id: '', tenant_id: '', role: '' });
  const [lookupUser, setLookupUser] = useState('');
  const [lookupTenant, setLookupTenant] = useState('');

  const { data: roles, isLoading } = useQuery({
    queryKey: ['rbac-roles'],
    queryFn: () => rbacApi.roles(),
  });

  const { data: userRole } = useQuery({
    queryKey: ['user-role', lookupUser, lookupTenant],
    queryFn: () => rbacApi.userRole(lookupUser, lookupTenant),
    enabled: !!lookupUser && !!lookupTenant,
  });

  const assignMutation = useMutation({
    mutationFn: () => rbacApi.assign(assignForm.user_id, assignForm.tenant_id, assignForm.role),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['rbac-roles'] }); setAssignForm({ user_id: '', tenant_id: '', role: '' }); },
  });

  const revokeMutation = useMutation({
    mutationFn: (data: { user_id: string; tenant_id: string }) => rbacApi.revoke(data.user_id, data.tenant_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['rbac-roles'] }),
  });

  if (isLoading) return <LoadingSpinner />;

  const roleList = roles?.roles || {};
  const permissions = roles?.all_permissions || [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Key className="w-6 h-6 text-info" /> RBAC</h1>
        <p className="text-muted-foreground">Role-based access control management</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Roles & Permissions</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {Object.entries(roleList).map(([role, perms]) => (
              <div key={role} className="p-3 rounded-lg border">
                <p className="font-medium text-sm mb-2">{role}</p>
                <div className="flex flex-wrap gap-1">
                  {perms.map((p) => <Badge key={p} variant="outline" className="text-xs">{p}</Badge>)}
                </div>
              </div>
            ))}
            {permissions.length > 0 && (
              <div className="pt-2 border-t">
                <p className="text-xs text-muted-foreground mb-2">All Permissions:</p>
                <div className="flex flex-wrap gap-1">
                  {permissions.map((p) => <Badge key={p} variant="secondary" className="text-xs">{p}</Badge>)}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base flex items-center gap-2"><UserPlus className="w-4 h-4" /> Assign Role</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Input placeholder="User ID" value={assignForm.user_id} onChange={(e) => setAssignForm({ ...assignForm, user_id: e.target.value })} />
              <Input placeholder="Tenant ID" value={assignForm.tenant_id} onChange={(e) => setAssignForm({ ...assignForm, tenant_id: e.target.value })} />
              <Select value={assignForm.role} onChange={(e) => setAssignForm({ ...assignForm, role: e.target.value })}>
                <option value="">Select Role</option>
                {Object.keys(roleList).map((r) => <option key={r} value={r}>{r}</option>)}
              </Select>
              <Button onClick={() => assignMutation.mutate()} disabled={!assignForm.user_id || !assignForm.tenant_id || !assignForm.role || assignMutation.isPending}
                className="w-full">
                {assignMutation.isPending ? 'Assigning...' : 'Assign Role'}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-base flex items-center gap-2"><Search className="w-4 h-4" /> Lookup User Role</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <Input placeholder="User ID" value={lookupUser} onChange={(e) => setLookupUser(e.target.value)} />
              <Input placeholder="Tenant ID" value={lookupTenant} onChange={(e) => setLookupTenant(e.target.value)} />
              {userRole && (
                <div className="p-3 rounded-lg border bg-muted/30">
                  <p className="text-sm">Role: <strong>{userRole.role || 'None'}</strong></p>
                  <div className="flex flex-wrap gap-1 mt-2">
                    {userRole.permissions.map((p) => <Badge key={p} variant="outline" className="text-xs">{p}</Badge>)}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
