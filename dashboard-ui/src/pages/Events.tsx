import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { guardApi } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { FilterBar } from '@/components/FilterBar';
import { LoadingSpinner } from '@/components/Loading';
import { formatTimestamp, truncate } from '@/lib/utils';
import { ChevronDown, ChevronUp } from 'lucide-react';

export default function EventsPage() {
  const [search, setSearch] = useState('');
  const [decisionFilter, setDecisionFilter] = useState('');
  const [expanded, setExpanded] = useState<number | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ['events'],
    queryFn: () => guardApi.events(),
    refetchInterval: 5000,
  });

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="text-kill">Error: {(error as Error).message}</div>;

  const events = (data?.events || []).filter((e) => {
    const matchSearch = !search || e.session_id.includes(search) || e.input_text.toLowerCase().includes(search.toLowerCase()) || (e.violation_type || '').toLowerCase().includes(search.toLowerCase());
    const matchDecision = !decisionFilter || e.decision === decisionFilter;
    return matchSearch && matchDecision;
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Events</h1>
        <p className="text-muted-foreground">{data?.total || 0} total events</p>
      </div>

      <FilterBar
        searchPlaceholder="Search by session ID, input, or violation..."
        searchValue={search} onSearchChange={setSearch}
        filters={[{
          label: 'All Decisions', value: 'decision',
          options: [
            { label: 'Pass', value: 'pass' },
            { label: 'Warn', value: 'warn' },
            { label: 'Kill', value: 'kill' },
          ],
        }]}
        filterValues={{ decision: decisionFilter }}
        onFilterChange={(_, v) => setDecisionFilter(v)}
      />

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="p-3 w-10"></th>
                  <th className="p-3">Decision</th>
                  <th className="p-3">Session</th>
                  <th className="p-3">Input</th>
                  <th className="p-3">Violation</th>
                  <th className="p-3">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {events.length === 0 ? (
                  <tr><td colSpan={6} className="p-8 text-center text-muted-foreground">No events found</td></tr>
                ) : (
                  events.map((event, i) => (
                    <>
                      <tr key={i} className="border-b hover:bg-accent/50 cursor-pointer" onClick={() => setExpanded(expanded === i ? null : i)}>
                        <td className="p-3">{expanded === i ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}</td>
                        <td className="p-3">
                          <Badge variant={event.decision === 'kill' ? 'kill' : event.decision === 'warn' ? 'warn' : 'pass'}>
                            {event.decision}
                          </Badge>
                        </td>
                        <td className="p-3 font-mono text-xs">{event.session_id?.slice(0, 12)}</td>
                        <td className="p-3">{truncate(event.input_text, 60)}</td>
                        <td className="p-3">
                          {event.violation_type ? <Badge variant="outline">{event.violation_type}</Badge> : '—'}
                        </td>
                        <td className="p-3 text-muted-foreground">{formatTimestamp(event.timestamp)}</td>
                      </tr>
                      {expanded === i && (
                        <tr key={`detail-${i}`} className="bg-muted/30">
                          <td></td>
                          <td colSpan={5} className="p-4">
                            <div className="space-y-2">
                              <p className="text-xs text-muted-foreground">Full Input:</p>
                              <p className="text-sm font-mono bg-background p-3 rounded border">{event.input_text}</p>
                              {event.details && (
                                <>
                                  <p className="text-xs text-muted-foreground mt-2">Details:</p>
                                  <pre className="text-xs bg-background p-3 rounded border overflow-auto max-h-40">
                                    {JSON.stringify(event.details, null, 2)}
                                  </pre>
                                </>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
