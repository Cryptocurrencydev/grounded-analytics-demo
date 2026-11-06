import type Highcharts from './highcharts';
import { ChartRef, Dashboard, Dimension, SegmentRow } from '../core/models';

/** Fixed order, so a question keeps its colour under every filter. */
export const QUESTION_COLORS: Record<string, string> = {
  satisfaction: '#2a78d6', workload: '#eb6834', leadership: '#1baf7a',
  growth: '#eda100', recognition: '#e87ba4', wellbeing: '#008300',
};
const LIKERT_COLORS = ['#c8413f', '#eba7a3', '#e4e2dc', '#86b6ef', '#256abf'];
const INK = '#1a2233';
const MUTED = '#5b6474';
const GRID = '#eceef1';
const BAR = '#2a78d6';
const DIM = 0.16;

const base = (height: number): Highcharts.Options => ({
  chart: {
    height, backgroundColor: 'transparent', spacing: [8, 4, 20, 0],
    style: { fontFamily: 'inherit' },
  },
  title: { text: undefined },
  legend: { itemStyle: { color: MUTED, fontWeight: '400', fontSize: '12px' }, itemHoverStyle: { color: INK }, symbolRadius: 2 },
  tooltip: {
    backgroundColor: '#ffffff', borderColor: '#d9dde3', borderRadius: 6, shadow: false, useHTML: true,
    style: { color: INK, fontSize: '12px' },
  },
  credits: { position: { y: -4 }, style: { color: '#9aa1ac', fontSize: '10px' } },
  accessibility: { enabled: true },
});

const axisLabels = { style: { color: MUTED, fontSize: '12px' } };

const hit = (refs: ChartRef[], chart: ChartRef['chart']) => refs.filter((r) => r.chart === chart);

export function trendOptions(d: Dashboard, refs: ChartRef[]): Highcharts.Options {
  const lit = hit(refs, 'trend').map((r) => r.series);
  const labels = d.quarters.map((q) => q.label);
  const selected = d.selected_quarters.map((q) => d.quarters.findIndex((x) => x.key === q));
  const partial = selected.length < d.quarters.length;
  return {
    ...base(280),
    xAxis: {
      categories: labels, labels: axisLabels, lineColor: GRID, tickLength: 0,
      plotBands: partial
        ? [{ from: Math.min(...selected) - 0.5, to: Math.max(...selected) + 0.5, color: 'rgba(42,120,214,0.07)' }]
        : [],
    },
    yAxis: {
      title: { text: undefined }, labels: axisLabels, gridLineColor: GRID, tickInterval: 0.25, softMin: 3, softMax: 4,
    },
    tooltip: { ...base(0).tooltip, shared: true, valueDecimals: 2 },
    plotOptions: { series: { animation: false, connectNulls: false } },
    series: d.trend.map((s) => {
      const dimmed = lit.length > 0 && !lit.includes(s.key);
      const active = lit.includes(s.key);
      return {
        type: 'line' as const,
        id: s.key,
        name: s.label,
        color: QUESTION_COLORS[s.key],
        lineWidth: active ? 3.5 : 2,
        opacity: dimmed ? DIM : 1,
        className: active ? 'q-lit' : dimmed ? 'q-dim' : undefined,
        marker: { radius: 4, symbol: 'circle', lineWidth: 2, lineColor: '#fff' },
        data: s.points.map((p) => ({
          y: p.value,
          custom: { n: p.n, small: p.small },
          marker: p.small ? { fillColor: '#fff', lineColor: QUESTION_COLORS[s.key], lineWidth: 2 } : undefined,
        })),
      };
    }),
  };
}

export function distributionOptions(d: Dashboard, refs: ChartRef[]): Highcharts.Options {
  const lit = hit(refs, 'distribution').flatMap((r) => r.categories);
  const hasLit = lit.length > 0;
  const trendLit = hit(refs, 'trend').map((r) => r.series);
  const wanted = hasLit ? lit : trendLit;
  const bands = d.distribution
    .map((row, i) => (wanted.includes(row.key) ? { from: i - 0.5, to: i + 0.5, color: 'rgba(98,80,214,0.1)' } : null))
    .filter((b) => !!b);
  return {
    ...base(280),
    xAxis: {
      categories: d.distribution.map((r) => r.label), labels: axisLabels, lineWidth: 0, tickLength: 0, plotBands: bands,
    },
    yAxis: { min: 0, max: 100, title: { text: undefined }, labels: { ...axisLabels, format: '{value}%' }, gridLineColor: GRID, reversedStacks: false },
    tooltip: { ...base(0).tooltip, valueSuffix: '%', shared: true },
    plotOptions: { bar: { stacking: 'normal', borderWidth: 2, borderColor: '#ffffff', borderRadius: 0, pointPadding: 0.08, groupPadding: 0.08, animation: false } },
    series: d.likert.map((label, i) => ({
      type: 'bar' as const, name: label, color: LIKERT_COLORS[i],
      data: d.distribution.map((r) => r.pct[i]),
    })),
  };
}

export function segmentOptions(
  rows: SegmentRow[], dimension: Dimension, question: string, refs: ChartRef[],
): Highcharts.Options {
  const sorted = [...rows].filter((r) => r.value !== null).sort((a, b) => (b.value ?? 0) - (a.value ?? 0));
  const lit = hit(refs, 'segments')
    .filter((r) => r.dimension === dimension && r.question === question)
    .flatMap((r) => r.categories);
  return {
    ...base(280),
    xAxis: { categories: sorted.map((r) => (r.small ? `${r.name} *` : r.name)), labels: axisLabels, lineColor: GRID, tickLength: 0 },
    yAxis: { min: 1, max: 5, tickInterval: 1, title: { text: undefined }, labels: axisLabels, gridLineColor: GRID },
    legend: { enabled: false },
    tooltip: {
      ...base(0).tooltip, shared: false,
      formatter() {
        const row = sorted[this.index ?? 0];
        if (!row) return false;
        const note = row.small ? '<br/><em>Small sample: read with caution</em>' : '';
        return `<b>${row.name}</b><br/>Mean ${row.value?.toFixed(2)} (95% CI ${row.lo?.toFixed(2)}–${row.hi?.toFixed(2)})<br/>n = ${row.n}${note}`;
      },
    },
    plotOptions: { series: { animation: false }, bar: { borderRadius: 3, borderWidth: 0, pointPadding: 0.14, groupPadding: 0.08 } },
    series: [
      {
        type: 'bar', name: 'Mean', dataLabels: { enabled: true, format: '{y:.2f}', inside: true, align: 'right', style: { color: '#fff', textOutline: 'none', fontWeight: '500', fontSize: '12px' } },
        data: sorted.map((r) => {
          const faded = (lit.length > 0 && !lit.includes(r.name)) || r.small;
          return {
            y: r.value,
            color: BAR,
            opacity: lit.length && !lit.includes(r.name) ? 0.28 : r.small ? 0.5 : 1,
            className: lit.includes(r.name) ? 'q-lit' : undefined,
            dataLabels: faded ? { style: { color: INK, textOutline: 'none', fontWeight: '500', fontSize: '12px' } } : undefined,
          };
        }),
      },
      {
        type: 'errorbar', name: '95% CI', color: INK, stemWidth: 1, whiskerLength: 8, enableMouseTracking: false,
        data: sorted.map((r) => [r.lo, r.hi]),
      },
    ],
  };
}

export function npsOptions(d: Dashboard, refs: ChartRef[]): Highcharts.Options {
  const lit = hit(refs, 'nps').length > 0;
  const rows = d.nps;
  const label = (i: number) => {
    const r = rows[i];
    const score = r.score === null ? 'n/a' : `${r.score > 0 ? '+' : ''}${r.score.toFixed(1)}`;
    return `${d.quarters[i].label}<br/><b style="color:${INK}">${score}</b>`;
  };
  const stack = (name: string, color: string, pick: (r: (typeof rows)[number]) => number | null) => ({
    type: 'column' as const, name, color, data: rows.map(pick),
  });
  return {
    ...base(280),
    xAxis: {
      categories: rows.map((_, i) => label(i)), labels: { ...axisLabels, useHTML: true, rotation: 0, autoRotation: [0] }, lineColor: GRID, tickLength: 0,
    },
    yAxis: { min: 0, max: 100, title: { text: undefined }, labels: { ...axisLabels, format: '{value}%' }, gridLineColor: GRID, reversedStacks: false },
    tooltip: { ...base(0).tooltip, shared: true, valueSuffix: '%' },
    plotOptions: {
      column: {
        stacking: 'normal', borderWidth: 2, borderColor: '#fff', borderRadius: 0, pointPadding: 0.1, groupPadding: 0.08, animation: false,
        className: lit ? 'q-lit' : undefined,
      },
    },
    series: [
      stack('Detractors (0–6)', '#d9605c', (r) => r.detractors),
      stack('Passives (7–8)', '#dcdad3', (r) => r.passives),
      stack('Promoters (9–10)', '#2a78d6', (r) => r.promoters),
    ],
  };
}

export function themeOptions(d: Dashboard, refs: ChartRef[]): Highcharts.Options {
  const lit = hit(refs, 'themes').flatMap((r) => r.categories);
  return {
    ...base(280),
    xAxis: { categories: d.themes.map((t) => t.label), labels: axisLabels, lineColor: GRID, tickLength: 0 },
    yAxis: { min: 0, title: { text: undefined }, labels: { ...axisLabels, format: '{value}%' }, gridLineColor: GRID },
    legend: { enabled: false },
    tooltip: { ...base(0).tooltip, pointFormat: '{point.y:.1f}% of comments ({point.custom.count})', headerFormat: '<b>{point.key}</b><br/>' },
    plotOptions: { bar: { borderRadius: 3, borderWidth: 0, pointPadding: 0.14, groupPadding: 0.08, animation: false } },
    series: [{
      type: 'bar', name: 'Share of comments',
      dataLabels: { enabled: true, format: '{y:.1f}%', style: { color: MUTED, textOutline: 'none', fontWeight: '400', fontSize: '12px' } },
      data: d.themes.map((t) => ({
        y: t.pct, color: BAR, custom: { count: t.count },
        opacity: lit.length && !lit.includes(t.key) ? 0.28 : 1,
        className: lit.includes(t.key) ? 'q-lit' : undefined,
      })),
    }],
  };
}
