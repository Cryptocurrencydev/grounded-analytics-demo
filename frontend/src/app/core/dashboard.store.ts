import { computed, DestroyRef, inject, Injectable, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { BehaviorSubject, catchError, combineLatest, debounceTime, map, of, switchMap, tap } from 'rxjs';
import { ApiService } from './api.service';
import {
  ChartRef, ChatMessage, Claim, Dashboard, DEFAULT_FILTERS, Dimension, Filters, Interpretation, Lang, Load, Stat,
} from './models';

export const INTERPRET_DEBOUNCE_MS = 450;

const sameFilters = (a: Filters, b: Filters) => JSON.stringify(a) === JSON.stringify(b);

/**
 * Filter state and everything derived from it.
 * Charts refresh at once. The interpretation is debounced, and switchMap drops any answer
 * for a filter state the user has already left.
 */
@Injectable({ providedIn: 'root' })
export class DashboardStore {
  private api = inject(ApiService);
  private filters$ = new BehaviorSubject<Filters>(DEFAULT_FILTERS);
  private lang$ = new BehaviorSubject<Lang>('en');
  private retry$ = new BehaviorSubject(0);

  readonly filters = signal<Filters>(DEFAULT_FILTERS);
  readonly lang = signal<Lang>('en');
  readonly dashboard = signal<Load<Dashboard>>({ state: 'loading' });
  readonly interpretation = signal<Load<Interpretation>>({ state: 'loading' });
  readonly messages = signal<ChatMessage[]>([]);
  readonly chatBusy = signal(false);

  readonly activeFinding = signal<number | null>(null);
  readonly highlights = signal<ChartRef[]>([]);

  private segmentDimensionChoice = signal<Dimension>('department');
  readonly segmentQuestion = signal('workload');
  readonly segmentDimensions = computed<Dimension[]>(() =>
    (['department', 'region', 'role'] as Dimension[]).filter((d) => this.filters()[d] === 'all'),
  );
  readonly segmentDimension = computed<Dimension | null>(() => {
    const open = this.segmentDimensions();
    const choice = this.segmentDimensionChoice();
    return open.includes(choice) ? choice : (open[0] ?? null);
  });

  constructor() {
    const destroyed = inject(DestroyRef);

    this.filters$
      .pipe(
        tap(() => this.dashboard.update((s) => ({ state: 'loading', previous: s.state === 'ready' ? s.data : s.state === 'loading' ? s.previous : undefined }))),
        switchMap((f) =>
          this.api.dashboard(f).pipe(
            map((data): Load<Dashboard> => ({ state: 'ready', data })),
            catchError(() => of<Load<Dashboard>>({ state: 'error', message: 'Could not load the charts.' })),
          ),
        ),
        takeUntilDestroyed(destroyed),
      )
      .subscribe((s) => this.dashboard.set(s));

    combineLatest([this.filters$, this.lang$, this.retry$])
      .pipe(
        tap(() => {
          this.interpretation.set({ state: 'loading' });
          this.clearHighlight();
        }),
        debounceTime(INTERPRET_DEBOUNCE_MS),
        switchMap(([f, lang]) =>
          this.api.interpret(f, lang).pipe(
            map((data): Load<Interpretation> => ({ state: 'ready', data })),
            catchError(() => of<Load<Interpretation>>({ state: 'error', message: 'The interpretation could not be loaded.' })),
          ),
        ),
        takeUntilDestroyed(destroyed),
      )
      .subscribe((s) => this.interpretation.set(s));
  }

  setFilters(next: Partial<Filters>): void {
    const merged = { ...this.filters(), ...next };
    if (sameFilters(merged, this.filters())) return;
    this.filters.set(merged);
    this.filters$.next(merged);
  }

  resetFilters(): void {
    this.setFilters(DEFAULT_FILTERS);
  }

  setLang(lang: Lang): void {
    if (lang === this.lang()) return;
    this.lang.set(lang);
    this.lang$.next(lang);
  }

  retryInterpretation(): void {
    this.retry$.next(this.retry$.value + 1);
  }

  setSegment(dimension: Dimension | null, question: string | null): void {
    if (dimension) this.segmentDimensionChoice.set(dimension);
    if (question) this.segmentQuestion.set(question);
  }

  /** Click on a finding: light up every chart element its cited stats point at. */
  selectFinding(index: number, claim: Claim, stats: Stat[]): void {
    if (this.activeFinding() === index) {
      this.clearHighlight();
      return;
    }
    const refs = claim.cites
      .map((id) => stats.find((s) => s.id === id)?.chart)
      .filter((c): c is ChartRef => !!c);
    const segment = refs.find((r) => r.chart === 'segments');
    if (segment) this.setSegment(segment.dimension ?? null, segment.question ?? null);
    else {
      const q = refs.find((r) => r.chart === 'trend')?.series;
      if (q) this.segmentQuestion.set(q);
    }
    this.activeFinding.set(index);
    this.highlights.set(refs);
  }

  clearHighlight(): void {
    this.activeFinding.set(null);
    this.highlights.set([]);
  }

  ask(question: string): void {
    const history = this.messages().slice(-6);
    this.messages.update((m) => [...m, { role: 'user', text: question }]);
    this.chatBusy.set(true);
    this.api.chat(question, this.filters(), this.lang(), history).subscribe({
      next: (result) => {
        const text = [...result.claims.map((c) => c.text), result.message].filter(Boolean).join(' ');
        this.messages.update((m) => [...m, { role: 'assistant', text, result }]);
        this.chatBusy.set(false);
        if (result.applied_filters) this.setFilters(result.applied_filters);
      },
      error: () => {
        this.messages.update((m) => [...m, {
          role: 'assistant', text: 'The request failed. Please try again.',
          result: { answer_type: 'error', claims: [], message: 'The request failed. Please try again.', stats: [], applied_filters: null, validation: null, attempts: 0, tool_calls: [], cached: false },
        }]);
        this.chatBusy.set(false);
      },
    });
  }
}

