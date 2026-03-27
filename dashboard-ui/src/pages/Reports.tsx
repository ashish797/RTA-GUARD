import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { reportsApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { LoadingSpinner } from '@/components/Loading';
import { FileText, Download, Play } from 'lucide-react';

export default function ReportsPage() {
  const [form, setForm] = useState({
    report_type: '',
    tenant_id: '',
    start_date: '',
    end_date: '',
    output_format: 'json',
  });

  const { data: types, isLoading } = useQuery({
    queryKey: ['report-types'],
    queryFn: () => reportsApi.types(),
  });

  const generateMutation = useMutation({
    mutationFn: () => reportsApi.generate(form),
  });

  if (isLoading) return <LoadingSpinner />;

  const reportTypes = types?.report_types || [];
  const formats = types?.output_formats || ['json', 'pdf', 'csv'];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><FileText className="w-6 h-6 text-info" /> Reports</h1>
        <p className="text-muted-foreground">Generate compliance and audit reports</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base">Generate Report</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <Select value={form.report_type} onChange={(e) => setForm({ ...form, report_type: e.target.value })}>
              <option value="">Select Report Type</option>
              {reportTypes.map((t) => <option key={t} value={t}>{t}</option>)}
            </Select>
            <Input placeholder="Tenant ID" value={form.tenant_id} onChange={(e) => setForm({ ...form, tenant_id: e.target.value })} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Start Date</label>
                <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground mb-1 block">End Date</label>
                <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
              </div>
            </div>
            <Select value={form.output_format} onChange={(e) => setForm({ ...form, output_format: e.target.value })}>
              {formats.map((f) => <option key={f} value={f}>{f.toUpperCase()}</option>)}
            </Select>
            <Button onClick={() => generateMutation.mutate()} disabled={!form.report_type || !form.tenant_id || generateMutation.isPending}
              className="w-full">
              <Play className="w-4 h-4 mr-2" />
              {generateMutation.isPending ? 'Generating...' : 'Generate Report'}
            </Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-base">Report Output</CardTitle></CardHeader>
          <CardContent>
            {generateMutation.data ? (
              <div className="space-y-3">
                <Badge variant="pass">Generated</Badge>
                <pre className="text-xs bg-muted p-4 rounded border overflow-auto max-h-80">
                  {JSON.stringify(generateMutation.data, null, 2)}
                </pre>
              </div>
            ) : generateMutation.error ? (
              <div className="p-3 rounded bg-kill/10 text-kill text-sm border border-kill/30">
                {(generateMutation.error as Error).message}
              </div>
            ) : (
              <div className="p-12 text-center text-muted-foreground">
                <FileText className="w-12 h-12 mx-auto mb-3 opacity-30" />
                <p>Configure and generate a report</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
