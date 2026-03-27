import { useState } from 'react';
import { Input } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Button } from '@/components/ui/button';
import { Search, X } from 'lucide-react';

interface FilterBarProps {
  searchPlaceholder?: string;
  searchValue: string;
  onSearchChange: (v: string) => void;
  filters?: { label: string; value: string; options: { label: string; value: string }[] }[];
  filterValues?: Record<string, string>;
  onFilterChange?: (key: string, value: string) => void;
}

export function FilterBar({ searchPlaceholder = 'Search...', searchValue, onSearchChange, filters, filterValues, onFilterChange }: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative flex-1 min-w-[200px] max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
        <Input placeholder={searchPlaceholder} value={searchValue}
          onChange={(e) => onSearchChange(e.target.value)}
          className="pl-9"
        />
        {searchValue && (
          <button onClick={() => onSearchChange('')} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground">
            <X className="w-4 h-4" />
          </button>
        )}
      </div>
      {filters?.map((f) => (
        <Select key={f.value} value={filterValues?.[f.value] || ''}
          onChange={(e) => onFilterChange?.(f.value, e.target.value)}
          className="w-40"
        >
          <option value="">{f.label}</option>
          {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </Select>
      ))}
    </div>
  );
}
