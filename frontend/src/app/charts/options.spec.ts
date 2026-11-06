import { describe, expect, it } from 'vitest';
import { ChartRef, Dashboard, SegmentRow } from '../core/models';
import { distributionOptions, segmentOptions, themeOptions, trendOptions } from './options';

const data = {
  quarters: [{ key: '2026-Q1', label: 'Q1 2026' }, { key: '2026-Q2', label: 'Q2 2026' }],
  selected_quarters: ['2026-Q2'],
  trend: [
    { key: 'workload', label: 'Workload', points: [{ value: 3.1, n: 40, small: false }, { value: 3, n: 20, small: true }] },
    { key: 'growth', label: 'Growth', points: [{ value: 3.4, n: 40, small: false }, { value: null, n: null, small: true }] },
  ],
  distribution: [{ key: 'workload', label: 'Workload', n: 10, pct: [10, 20, 30, 30, 10] }, { key: 'growth', label: 'Growth', n: 10, pct: [10, 20, 30, 30, 10] }],
  likert: ['a', 'b', 'c', 'd', 'e'],
  themes: [{ key: 'tools_systems', label: 'Tools', count: 9, pct: 30 }, { key: 'career_paths', label: 'Career', count: 7, pct: 20 }],
} as unknown as Dashboard;
const trendRef: ChartRef = { chart: 'trend', series: 'workload', categories: [] };

describe('chart options', () => {
  it('leaves every series at full strength with no highlight', () => {
    const s = trendOptions(data, []).series as { opacity: number }[];
    expect(s.map((x) => x.opacity)).toEqual([1, 1]);
  });

  it('fades the other series when a finding lights one', () => {
    const s = trendOptions(data, [trendRef]).series as { id: string; opacity: number; lineWidth: number }[];
    expect(s.find((x) => x.id === 'workload')).toMatchObject({ opacity: 1, lineWidth: 3.5 });
    expect(s.find((x) => x.id === 'growth')!.opacity).toBeLessThan(0.5);
  });

  it('keeps a question on the same colour when another one is filtered out', () => {
    const before = (trendOptions(data, []).series as { id: string; color: string }[]).find((s) => s.id === 'growth')!.color;
    const only = { ...data, trend: [data.trend[1]] };
    expect((trendOptions(only, []).series as { color: string }[])[0].color).toBe(before);
  });

  it('shades the selected period', () => {
    const x = trendOptions(data, []).xAxis as { plotBands: { from: number; to: number }[] };
    expect(x.plotBands).toHaveLength(1);
    expect(x.plotBands[0]).toMatchObject({ from: 0.5, to: 1.5 });
  });

  it('marks the matching row in the distribution chart', () => {
    const x = distributionOptions(data, [trendRef]).xAxis as { plotBands: { from: number }[] };
    expect(x.plotBands).toHaveLength(1);
    expect(x.plotBands[0].from).toBe(-0.5);
  });

  it('sorts segments and flags small ones', () => {
    const rows: SegmentRow[] = [
      { name: 'A', value: 3, n: 50, small: false, lo: 2.9, hi: 3.1 },
      { name: 'B', value: 4, n: 20, small: true, lo: 3.5, hi: 4.5 },
      { name: 'C', value: null, n: null, small: true },
    ];
    const o = segmentOptions(rows, 'role', 'growth', []);
    expect((o.xAxis as { categories: string[] }).categories).toEqual(['B *', 'A']);
  });

  it('lights only the cited segments, and only on the matching view', () => {
    const rows: SegmentRow[] = [
      { name: 'A', value: 3, n: 50, small: false, lo: 2.9, hi: 3.1 },
      { name: 'B', value: 4, n: 50, small: false, lo: 3.9, hi: 4.1 },
    ];
    const ref: ChartRef = { chart: 'segments', dimension: 'role', question: 'growth', categories: ['B'] };
    const points = (o: Highcharts.Options) => (o.series![0] as unknown as { data: { opacity: number }[] }).data.map((p) => p.opacity);
    expect(points(segmentOptions(rows, 'role', 'growth', [ref]))).toEqual([1, 0.28]);
    expect(points(segmentOptions(rows, 'role', 'workload', [ref]))).toEqual([1, 1]);
  });

  it('lights a cited theme', () => {
    const o = themeOptions(data, [{ chart: 'themes', categories: ['career_paths'] }]);
    const p = (o.series![0] as unknown as { data: { opacity: number }[] }).data;
    expect(p.map((x) => x.opacity)).toEqual([0.28, 1]);
  });
});
