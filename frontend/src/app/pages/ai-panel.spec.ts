import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DashboardStore } from '../core/dashboard.store';
import { Interpretation, Lang, Load } from '../core/models';
import { AiPanel } from './ai-panel';

const base: Interpretation = {
  status: 'ok', lang: 'en', scope: 's', n: 100,
  summary: [{ text: 'Summary sentence.', cites: ['S01'] }],
  findings: [{ title: 'Workload', text: 'Workload averages 3.2.', cites: ['S01'] }],
  warnings: [], validation: { ok: true, claims_checked: 2, numbers_checked: 3, numbers_matched: 3, issues: [] },
  stats: [{ id: 'S01', key: 'k', kind: 'mean', label: 'Workload mean', value: 3.2, unit: 'scale', decimals: 2, n: 100, related: [] }],
  attempts: 1, rejected_issues: [], model: 'claude', cached: false, sent_to_model: { stats: [] },
};

describe('AiPanel', () => {
  let fixture: ComponentFixture<AiPanel>;
  const state = signal<Load<Interpretation>>({ state: 'loading' });
  const selectFinding = vi.fn();
  const text = () => (fixture.nativeElement as HTMLElement).textContent ?? '';
  const render = async (s: Load<Interpretation>) => {
    state.set(s);
    await fixture.whenStable();
  };

  beforeEach(() => {
    selectFinding.mockClear();
    TestBed.configureTestingModule({
      imports: [AiPanel],
      providers: [{
        provide: DashboardStore,
        useValue: {
          interpretation: state, lang: signal<Lang>('en'), activeFinding: signal(null), highlights: signal([]), messages: signal([]),
          chatBusy: signal(false), selectFinding, setLang: vi.fn(), retryInterpretation: vi.fn(),
        },
      }],
    });
    fixture = TestBed.createComponent(AiPanel);
  });

  it('marks output as AI-generated and shows the verification count', async () => {
    await render({ state: 'ready', data: base });
    expect(text()).toContain('AI-generated');
    expect(text()).toContain('3 of 3 figures verified');
    expect(text()).toContain('Workload averages 3.2.');
  });

  it('shows a loading state while refreshing', async () => {
    await render({ state: 'loading' });
    expect(text()).toContain('Computing statistics');
  });

  it('says there is not enough data instead of interpreting', async () => {
    await render({ state: 'ready', data: { ...base, status: 'insufficient', summary: [], findings: [], warnings: ['Fewer than 5 responses match this filter.'] } });
    expect(text()).toContain('Not enough data');
    expect(text()).not.toContain('AI-generated');
  });

  it('labels the safe fallback', async () => {
    await render({ state: 'ready', data: { ...base, status: 'fallback', findings: [] } });
    expect(text()).toContain('AI text withheld');
    expect(text()).not.toContain('figures verified');
  });

  it('offers a retry on error', async () => {
    await render({ state: 'error', message: 'Failed.' });
    expect(text()).toContain('Try again');
  });

  it('sends a clicked finding to the store', async () => {
    await render({ state: 'ready', data: base });
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('[data-testid=finding]')!.click();
    expect(selectFinding).toHaveBeenCalledWith(0, base.findings[0], base.stats);
  });
});
