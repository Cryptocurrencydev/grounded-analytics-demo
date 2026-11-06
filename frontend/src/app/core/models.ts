export type Lang = 'en' | 'de';
export type Dimension = 'region' | 'department' | 'role';

export interface Filters {
  period: string;
  region: string;
  department: string;
  role: string;
}
export const DEFAULT_FILTERS: Filters = { period: 'all', region: 'all', department: 'all', role: 'all' };

export interface Meta {
  periods: { value: string; label: string }[];
  regions: string[];
  departments: string[];
  roles: string[];
  questions: { key: string; label: string }[];
}

export interface Cell {
  value: number | null;
  n: number | null;
  small: boolean;
  lo?: number | null;
  hi?: number | null;
}
export interface TrendSeries { key: string; label: string; points: Cell[] }
export interface DistributionRow { key: string; label: string; n: number | null; pct: (number | null)[] }
export interface SegmentRow extends Cell { name: string }
export interface NpsRow {
  quarter: string; n: number | null; score: number | null; small: boolean;
  promoters: number | null; passives: number | null; detractors: number | null;
}
export interface ThemeRow { key: string; label: string; count: number; pct: number }

export interface Dashboard {
  n: number | null;
  too_small: boolean;
  scope: string;
  selected_quarters: string[];
  quarters: { key: string; label: string }[];
  kpis: { satisfaction: number | null; nps: number | null; promoters: number | null; detractors: number | null };
  trend: TrendSeries[];
  distribution: DistributionRow[];
  likert: string[];
  segments: Partial<Record<Dimension, Record<string, SegmentRow[]>>>;
  nps: NpsRow[];
  themes: ThemeRow[];
}

export interface ChartRef {
  chart: 'trend' | 'distribution' | 'segments' | 'nps' | 'themes';
  series?: string | null;
  categories: string[];
  dimension?: Dimension | null;
  question?: string | null;
}
export interface RelatedNumber { name: string; value: number; unit: string; decimals: number }
export interface Stat {
  id: string; key: string; kind: string; label: string; value: number; unit: string; decimals: number; n: number;
  related: RelatedNumber[]; direction?: string | null; significant?: boolean | null; test?: string | null;
  chart?: ChartRef | null;
}
export interface Claim { text: string; cites: string[] }
export interface Finding extends Claim { title: string }
export interface ValidationReport {
  ok: boolean; claims_checked: number; numbers_checked: number; numbers_matched: number;
  issues: { code: string; claim: number; detail: string }[];
}
export interface Interpretation {
  status: 'ok' | 'insufficient' | 'fallback' | 'rate_limited';
  lang: Lang; scope: string; n: number | null;
  summary: Claim[]; findings: Finding[]; warnings: string[]; stats: Stat[];
  validation: ValidationReport | null; attempts: number; rejected_issues: string[];
  model: string | null; cached: boolean; sent_to_model: unknown;
}

export interface ChatResult {
  answer_type: 'answer' | 'filters_applied' | 'insufficient_data' | 'cannot_answer' | 'unverified' | 'rate_limited' | 'error';
  claims: Claim[]; message: string; stats: Stat[]; applied_filters: Filters | null;
  validation: ValidationReport | null; attempts: number; tool_calls: { tool: string; input: unknown }[];
  cached: boolean;
}
export interface ChatMessage { role: 'user' | 'assistant'; text: string; result?: ChatResult }

export interface AppListItem {
  id: string; programme: string; submitted_on: string; organisation: string; project_title: string; missing: number;
}
export interface AppField { key: string; label: string; value: string | number | null; pii: boolean; missing: boolean }
export interface AppDetail { id: string; programme: string; submitted_on: string; fields: AppField[] }
export interface AppFlag { kind: 'missing' | 'contradiction'; source: 'rule' | 'ai'; text: string; fields: string[] }
export interface AppSummary {
  id: string; status: 'ok' | 'fallback' | 'rate_limited'; lang: Lang;
  statements: { text: string; fields: string[] }[]; flags: AppFlag[];
  attempts: number; rejected_issues: string[]; model: string | null; cached: boolean;
  sent_to_model: unknown; numbers_checked: number;
}

export type Load<T> =
  | { state: 'loading'; previous?: T }
  | { state: 'ready'; data: T }
  | { state: 'error'; message: string };
