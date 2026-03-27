import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { brahmandaApi } from '@/lib/api';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { LoadingSpinner } from '@/components/Loading';
import { Activity, CheckCircle, XCircle, Database } from 'lucide-react';

export default function BrahmandaPage() {
  const [claim, setClaim] = useState('');
  const [domain, setDomain] = useState('');

  const { data: status, isLoading } = useQuery({
    queryKey: ['brahmanda-status'],
    queryFn: () => brahmandaApi.status(),
  });

  const verifyMutation = useMutation({
    mutationFn: () => brahmandaApi.verify(claim, domain),
  });

  const pipelineMutation = useMutation({
    mutationFn: () => brahmandaApi.pipelineVerify(claim, domain),
  });

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Activity className="w-6 h-6 text-info" /> Brahmanda Map</h1>
        <p className="text-muted-foreground">Ground truth verification system</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-base flex items-center gap-2"><Database className="w-4 h-4" /> Backend Status</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {status ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm">Backend</span>
                  <Badge variant="outline">{status.backend}</Badge>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm">Facts</span>
                  <span className="font-mono">{status.fact_count}</span>
                </div>
                {status.qdrant_url && (
                  <div className="flex items-center justify-between">
                    <span className="text-sm">Qdrant</span>
                    <span className="text-xs text-muted-foreground truncate max-w-[150px]">{status.qdrant_url}</span>
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Unable to fetch status</p>
            )}
          </CardContent>
        </Card>

        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader><CardTitle className="text-base">Verify Claim</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <Textarea placeholder="Enter a claim to verify against ground truth..." value={claim} onChange={(e) => setClaim(e.target.value)} rows={3} />
              <Input placeholder="Domain (optional, e.g., science, history)" value={domain} onChange={(e) => setDomain(e.target.value)} />
              <div className="flex gap-3">
                <Button onClick={() => verifyMutation.mutate()} disabled={!claim || verifyMutation.isPending}>
                  {verifyMutation.isPending ? 'Verifying...' : 'Verify'}
                </Button>
                <Button variant="outline" onClick={() => pipelineMutation.mutate()} disabled={!claim || pipelineMutation.isPending}>
                  {pipelineMutation.isPending ? 'Verifying...' : 'Pipeline Verify'}
                </Button>
              </div>
            </CardContent>
          </Card>

          {(verifyMutation.data || pipelineMutation.data) && (
            <Card>
              <CardHeader><CardTitle className="text-base">Verification Result</CardTitle></CardHeader>
              <CardContent>
                {(() => {
                  const result = verifyMutation.data || pipelineMutation.data;
                  if (!result) return null;
                  return (
                    <div className="space-y-4">
                      <div className="flex items-center gap-3">
                        {result.verified ? (
                          <CheckCircle className="w-6 h-6 text-pass" />
                        ) : (
                          <XCircle className="w-6 h-6 text-kill" />
                        )}
                        <div>
                          <p className="font-medium">{result.verified ? 'Verified' : 'Not Verified'}</p>
                          <p className="text-sm text-muted-foreground">
                            Confidence: {(result.confidence * 100).toFixed(1)}% | Domain: {result.domain || 'general'}
                          </p>
                        </div>
                      </div>
                      {result.contradictions.length > 0 && (
                        <div>
                          <p className="text-sm font-medium text-kill mb-2">Contradictions:</p>
                          <pre className="text-xs bg-muted p-3 rounded border overflow-auto max-h-32">
                            {JSON.stringify(result.contradictions, null, 2)}
                          </pre>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
