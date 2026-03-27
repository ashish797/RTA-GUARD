import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { webhooksApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { LoadingSpinner } from '@/components/Loading';
import { Webhook, Plus, Trash2, Play, ExternalLink, Edit } from 'lucide-react';

const EVENT_TYPES = ['session.kill', 'session.warn', 'violation.pii', 'violation.injection', 'violation.jailbreak', 'violation.destructive', 'escalation.alert', 'drift.critical'];

export default function WebhooksPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ url: '', events: [] as string[], tenant_id: '', description: '' });

  const { data: webhooks, isLoading } = useQuery({
    queryKey: ['webhooks'],
    queryFn: () => webhooksApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: () => webhooksApi.create(form),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['webhooks'] }); setShowCreate(false); setForm({ url: '', events: [], tenant_id: '', description: '' }); },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => webhooksApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['webhooks'] }),
  });

  const testMutation = useMutation({
    mutationFn: (id: string) => webhooksApi.test(id),
  });

  if (isLoading) return <LoadingSpinner />;

  const toggleEvent = (evt: string) => {
    setForm((f) => ({
      ...f,
      events: f.events.includes(evt) ? f.events.filter((e) => e !== evt) : [...f.events, evt],
    }));
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2"><Webhook className="w-6 h-6 text-info" /> Webhooks</h1>
          <p className="text-muted-foreground">{webhooks?.total || 0} configured webhooks</p>
        </div>
        <Button onClick={() => setShowCreate(!showCreate)}>
          <Plus className="w-4 h-4 mr-2" /> New Webhook
        </Button>
      </div>

      {showCreate && (
        <Card>
          <CardHeader><CardTitle className="text-base">Create Webhook</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Input placeholder="Webhook URL (https://...)" value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} />
            <Input placeholder="Tenant ID" value={form.tenant_id} onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} />
            <Input placeholder="Description (optional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <div>
              <p className="text-sm font-medium mb-2">Events to subscribe:</p>
              <div className="flex flex-wrap gap-2">
                {EVENT_TYPES.map((evt) => (
                  <button key={evt} onClick={() => toggleEvent(evt)}
                    className={`px-3 py-1 rounded-full text-xs border transition-colors ${
                      form.events.includes(evt) ? 'bg-primary text-primary-foreground border-primary' : 'bg-background hover:bg-accent'
                    }`}
                  >
                    {evt}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex gap-3">
              <Button onClick={() => createMutation.mutate()} disabled={!form.url || form.events.length === 0 || !form.tenant_id || createMutation.isPending}>
                {createMutation.isPending ? 'Creating...' : 'Create'}
              </Button>
              <Button variant="outline" onClick={() => setShowCreate(false)}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {!webhooks || webhooks.webhooks.length === 0 ? (
          <Card className="md:col-span-2">
            <CardContent className="p-12 text-center text-muted-foreground">No webhooks configured</CardContent>
          </Card>
        ) : (
          webhooks.webhooks.map((wh) => (
            <Card key={wh.webhook_id}>
              <CardContent className="p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ExternalLink className="w-4 h-4 text-muted-foreground" />
                    <span className="font-mono text-sm truncate max-w-[200px]">{wh.url}</span>
                  </div>
                  <Badge variant={wh.active ? 'pass' : 'secondary'}>{wh.active ? 'Active' : 'Inactive'}</Badge>
                </div>
                {wh.description && <p className="text-xs text-muted-foreground">{wh.description}</p>}
                <div className="flex flex-wrap gap-1">
                  {wh.events.map((e) => <Badge key={e} variant="outline" className="text-xs">{e}</Badge>)}
                </div>
                <div className="flex items-center gap-2 pt-2 border-t">
                  <Button variant="ghost" size="sm" onClick={() => testMutation.mutate(wh.webhook_id)} disabled={testMutation.isPending}>
                    <Play className="w-3 h-3 mr-1" /> Test
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => deleteMutation.mutate(wh.webhook_id)} disabled={deleteMutation.isPending}>
                    <Trash2 className="w-3 h-3 mr-1 text-kill" /> Delete
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>
    </div>
  );
}
