import { TestBed } from '@angular/core/testing';
import { of, Subject, throwError } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiService } from './api.service';
import { DashboardStore, INTERPRET_DEBOUNCE_MS } from './dashboard.store';
import { ChatResult, Dashboard, Filters, Interpretation, Stat } from './models';

const interpretation = (scope: string): Interpretation => ({
  status: 'ok', lang: 'en', scope, n: 100, summary: [{ text: scope, cites: ['S01'] }], findings: [], warnings: [], stats: [],
  validation: null, attempts: 1, rejected_issues: [], model: 'm', cached: false, sent_to_model: {},
});
const chatResult = (over: Partial<ChatResult>): ChatResult => ({
  answer_type: 'answer', claims: [], message: '', stats: [], applied_filters: null, validation: null, attempts: 1, tool_calls: [], cached: false, ...over,
});
const dashboard = { n: 1 } as Dashboard;

describe('DashboardStore', () => {
  let api: { dashboard: ReturnType<typeof vi.fn>; interpret: ReturnType<typeof vi.fn>; chat: ReturnType<typeof vi.fn> };
  let store: DashboardStore;
  const settle = () => vi.advanceTimersByTime(INTERPRET_DEBOUNCE_MS + 1);

  beforeEach(() => {
    vi.useFakeTimers();
    api = {
      dashboard: vi.fn(() => of(dashboard)),
      interpret: vi.fn((f: Filters) => of(interpretation(f.region))),
      chat: vi.fn(),
    };
    TestBed.configureTestingModule({ providers: [{ provide: ApiService, useValue: api }] });
    store = TestBed.inject(DashboardStore);
    settle();
    api.dashboard.mockClear();
    api.interpret.mockClear();
  });
  afterEach(() => vi.useRealTimers());

  it('refreshes charts at once but waits out the debounce before interpreting', () => {
    store.setFilters({ region: 'North' });
    expect(api.dashboard).toHaveBeenCalledTimes(1);
    expect(api.interpret).not.toHaveBeenCalled();
    expect(store.interpretation().state).toBe('loading');
    settle();
    expect(api.interpret).toHaveBeenCalledTimes(1);
    expect(api.interpret.mock.calls[0][0].region).toBe('North');
    expect(store.interpretation()).toMatchObject({ state: 'ready', data: { scope: 'North' } });
  });

  it('collapses a burst of filter changes into one request for the final state', () => {
    store.setFilters({ region: 'North' });
    vi.advanceTimersByTime(100);
    store.setFilters({ region: 'South' });
    vi.advanceTimersByTime(100);
    store.setFilters({ department: 'Sales' });
    settle();
    expect(api.interpret).toHaveBeenCalledTimes(1);
    expect(api.interpret.mock.calls[0][0]).toMatchObject({ region: 'South', department: 'Sales' });
  });

  it('drops a late answer for a filter the user has left', () => {
    const slow = new Subject<Interpretation>();
    api.interpret.mockImplementationOnce(() => slow);
    store.setFilters({ region: 'North' });
    settle();
    store.setFilters({ region: 'South' });
    settle();
    slow.next(interpretation('North'));
    slow.complete();
    expect(store.interpretation()).toMatchObject({ state: 'ready', data: { scope: 'South' } });
  });

  it('does not refetch when the filters did not change', () => {
    store.setFilters({ region: 'all' });
    settle();
    expect(api.dashboard).not.toHaveBeenCalled();
    expect(api.interpret).not.toHaveBeenCalled();
  });

  it('refetches the interpretation, not the charts, on a language switch', () => {
    store.setLang('de');
    settle();
    expect(api.interpret.mock.calls[0][1]).toBe('de');
    expect(api.dashboard).not.toHaveBeenCalled();
  });

  it('shows an error state, keeps working, and can retry', () => {
    api.interpret.mockImplementationOnce(() => throwError(() => new Error('boom')));
    store.setFilters({ region: 'North' });
    settle();
    expect(store.interpretation().state).toBe('error');
    store.retryInterpretation();
    settle();
    expect(store.interpretation().state).toBe('ready');
  });

  it('shows an error for the charts when the dashboard call fails, then recovers', () => {
    api.dashboard.mockImplementationOnce(() => throwError(() => new Error('boom')));
    store.setFilters({ region: 'North' });
    expect(store.dashboard().state).toBe('error');
    store.setFilters({ region: 'South' });
    expect(store.dashboard().state).toBe('ready');
  });

  it('maps a finding to the chart elements of its cited stats', () => {
    const stats = [
      { id: 'S01', chart: { chart: 'trend', series: 'workload', categories: [] } },
      { id: 'S02', chart: { chart: 'segments', dimension: 'region', question: 'leadership', categories: ['North', 'West'] } },
      { id: 'S03', chart: null },
    ] as unknown as Stat[];
    store.selectFinding(1, { text: 'x', cites: ['S01', 'S02', 'S03'] }, stats);
    expect(store.highlights().map((r) => r.chart)).toEqual(['trend', 'segments']);
    expect(store.segmentDimension()).toBe('region');
    expect(store.segmentQuestion()).toBe('leadership');
    store.selectFinding(1, { text: 'x', cites: ['S01'] }, stats);
    expect(store.highlights()).toEqual([]);
  });

  it('clears the highlight when the filters change', () => {
    store.selectFinding(0, { text: 'x', cites: ['S01'] }, [{ id: 'S01', chart: { chart: 'nps', categories: [] } }] as unknown as Stat[]);
    store.setFilters({ region: 'North' });
    expect(store.highlights()).toEqual([]);
    expect(store.activeFinding()).toBeNull();
  });

  it('moves the segment chart off a dimension that is now filtered', () => {
    expect(store.segmentDimension()).toBe('department');
    store.setFilters({ department: 'Sales' });
    expect(store.segmentDimension()).toBe('region');
    store.setFilters({ region: 'North', role: 'Manager' });
    expect(store.segmentDimension()).toBeNull();
  });

  it('applies filters returned by a chat tool call and refreshes everything', () => {
    api.chat.mockReturnValue(of(chatResult({
      answer_type: 'filters_applied', message: 'Done', applied_filters: { period: '2026', region: 'North', department: 'all', role: 'all' },
    })));
    store.ask('show me only the north region in 2026');
    expect(store.filters()).toMatchObject({ period: '2026', region: 'North' });
    settle();
    expect(api.dashboard).toHaveBeenCalledTimes(1);
    expect(api.interpret).toHaveBeenCalledTimes(1);
    expect(store.messages().map((m) => m.role)).toEqual(['user', 'assistant']);
    expect(store.chatBusy()).toBe(false);
  });

  it('turns a failed chat request into a visible message', () => {
    api.chat.mockReturnValue(throwError(() => new Error('boom')));
    store.ask('hello');
    expect(store.messages()[1].result?.answer_type).toBe('error');
    expect(store.chatBusy()).toBe(false);
  });
});
