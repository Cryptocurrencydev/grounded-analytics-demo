import { Component, computed, inject } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ChartDirective } from '../charts/chart.directive';
import { distributionOptions, npsOptions, segmentOptions, themeOptions, trendOptions } from '../charts/options';
import { ApiService } from '../core/api.service';
import { DashboardStore } from '../core/dashboard.store';
import { ChartRef, Dashboard, Dimension, Filters } from '../core/models';
import { AiPanel } from './ai-panel';

const DIM_LABELS: Record<Dimension, string> = { department: 'Department', region: 'Region', role: 'Role' };

@Component({
  selector: 'app-dashboard',
  imports: [ChartDirective, AiPanel],
  template: `
    <section class="filters" aria-label="Filters">
      <label>Time period
        <select data-testid="filter-period" (change)="set('period', $event)">
          @for (p of meta()?.periods; track p.value) {
            <option [value]="p.value" [selected]="p.value === store.filters().period">{{ p.label }}</option>
          }
        </select>
      </label>
      <label>Region
        <select data-testid="filter-region" (change)="set('region', $event)">
          <option value="all" [selected]="store.filters().region === 'all'">All regions</option>
          @for (v of meta()?.regions; track v) {
            <option [value]="v" [selected]="v === store.filters().region">{{ v }}</option>
          }
        </select>
      </label>
      <label>Department
        <select data-testid="filter-department" (change)="set('department', $event)">
          <option value="all" [selected]="store.filters().department === 'all'">All departments</option>
          @for (v of meta()?.departments; track v) {
            <option [value]="v" [selected]="v === store.filters().department">{{ v }}</option>
          }
        </select>
      </label>
      <label>Role
        <select data-testid="filter-role" (change)="set('role', $event)">
          <option value="all" [selected]="store.filters().role === 'all'">All roles</option>
          @for (v of meta()?.roles; track v) {
            <option [value]="v" [selected]="v === store.filters().role">{{ v }}</option>
          }
        </select>
      </label>
      @if (filtered()) {
        <button class="link" type="button" (click)="store.resetFilters()">Reset filters</button>
      }
    </section>

    <div class="layout">
      <div class="charts">
        @if (loadError(); as message) {
          <div class="state error" role="alert">{{ message }} Refresh the page to try again.</div>
        } @else if (data(); as d) {
          <section class="kpis" aria-label="Key figures" data-testid="kpis">
            <div class="kpi"><span>Responses</span><b data-testid="kpi-n">{{ d.n === null ? 'Fewer than 5' : d.n.toLocaleString('en-GB') }}</b></div>
            <div class="kpi"><span>Overall satisfaction</span><b>{{ num(d.kpis.satisfaction, 2) }}<small> / 5</small></b></div>
            <div class="kpi"><span>Employee NPS</span><b>{{ signed(d.kpis.nps) }}</b></div>
            <div class="kpi"><span>Promoters / detractors</span><b>{{ num(d.kpis.promoters, 1) }}%<small> / {{ num(d.kpis.detractors, 1) }}%</small></b></div>
          </section>

          @if (d.too_small) {
            <div class="state empty">This filter matches fewer than 5 responses, so its charts are hidden to protect respondents. Widen the filter to see data.</div>
          } @else {
            <div class="grid">
              <article class="card wide" data-chart="trend" [class.lit]="lit('trend')" [attr.data-lit-series]="litSeries()">
                <header><h2>Scores by quarter</h2><p>Mean on the 1–5 scale, all 6 quarters. The shaded band is the selected period. Hollow points have fewer than 30 responses.</p></header>
                <div class="plot" [qChart]="trendOpts()!" role="img" aria-label="Line chart of question means by quarter"></div>
              </article>
              <article class="card" data-chart="distribution" [class.lit]="lit('distribution') || lit('trend')">
                <header><h2>Answer distribution</h2><p>Share of answers per question, selected period.</p></header>
                <div class="plot" [qChart]="distOpts()!" role="img" aria-label="Stacked bars of answer shares per question"></div>
              </article>
              <article class="card" data-chart="segments" [class.lit]="lit('segments')" [attr.data-lit-segments]="litSegments()">
                <header class="row">
                  <div><h2>Segment comparison</h2><p>Mean with 95% confidence interval. * means fewer than 30 responses.</p></div>
                  <div class="mini">
                    <select aria-label="Segment dimension" data-testid="segment-dimension" (change)="pickDimension($event)">
                      @for (dim of store.segmentDimensions(); track dim) {
                        <option [value]="dim" [selected]="dim === store.segmentDimension()">{{ dimLabel(dim) }}</option>
                      }
                    </select>
                    <select aria-label="Segment question" data-testid="segment-question" (change)="pickQuestion($event)">
                      @for (q of meta()?.questions; track q.key) {
                        <option [value]="q.key" [selected]="q.key === store.segmentQuestion()">{{ q.label }}</option>
                      }
                    </select>
                  </div>
                </header>
                @if (segOpts(); as o) {
                  <div class="plot" [qChart]="o" role="img" aria-label="Bars of mean score per segment"></div>
                } @else {
                  <div class="state empty small">Every segment dimension is already filtered. Clear one filter to compare.</div>
                }
              </article>
              <article class="card" data-chart="nps" [class.lit]="lit('nps')">
                <header><h2>Employee NPS by quarter</h2><p>Promoter, passive and detractor shares, with the NPS under each quarter.</p></header>
                <div class="plot" [qChart]="npsOpts()!" role="img" aria-label="Stacked columns of NPS groups by quarter"></div>
              </article>
              <article class="card" data-chart="themes" [class.lit]="lit('themes')">
                <header><h2>Comment themes</h2><p>Share of comments per theme. Only these counts are used, comment text stays on the server.</p></header>
                @if (d.themes.length) {
                  <div class="plot" [qChart]="themeOpts()!" role="img" aria-label="Bars of comment theme shares"></div>
                } @else {
                  <div class="state empty small">Too few comments in this filter.</div>
                }
              </article>
            </div>
          }
        } @else {
          <div class="kpis"><div class="kpi sk"></div><div class="kpi sk"></div><div class="kpi sk"></div><div class="kpi sk"></div></div>
          <div class="grid"><div class="card wide sk tall"></div><div class="card sk tall"></div><div class="card sk tall"></div></div>
        }
      </div>
      <app-ai-panel />
    </div>
  `,
})
export class DashboardPage {
  protected readonly store = inject(DashboardStore);
  private api = inject(ApiService);
  protected readonly meta = toSignal(this.api.meta().pipe(catchError(() => of(null))));

  protected readonly data = computed<Dashboard | null>(() => {
    const s = this.store.dashboard();
    return s.state === 'ready' ? s.data : s.state === 'loading' ? (s.previous ?? null) : null;
  });
  protected readonly loadError = computed(() => {
    const s = this.store.dashboard();
    return s.state === 'error' ? s.message : null;
  });
  protected readonly filtered = computed(() => Object.values(this.store.filters()).some((v) => v !== 'all'));

  private refs = computed<ChartRef[]>(() => this.store.highlights());
  protected readonly trendOpts = computed(() => (this.data() ? trendOptions(this.data()!, this.refs()) : null));
  protected readonly distOpts = computed(() => (this.data() ? distributionOptions(this.data()!, this.refs()) : null));
  protected readonly npsOpts = computed(() => (this.data() ? npsOptions(this.data()!, this.refs()) : null));
  protected readonly themeOpts = computed(() => (this.data() ? themeOptions(this.data()!, this.refs()) : null));
  protected readonly segOpts = computed(() => {
    const d = this.data();
    const dim = this.store.segmentDimension();
    const q = this.store.segmentQuestion();
    const rows = dim ? d?.segments[dim]?.[q] : undefined;
    return rows && dim ? segmentOptions(rows, dim, q, this.refs()) : null;
  });

  protected readonly litSeries = computed(() =>
    this.refs().filter((r) => r.chart === 'trend').map((r) => r.series).join(',') || null,
  );
  protected readonly litSegments = computed(() =>
    this.refs().filter((r) => r.chart === 'segments').flatMap((r) => r.categories).join(',') || null,
  );

  protected lit(chart: ChartRef['chart']): boolean {
    return this.refs().some((r) => r.chart === chart);
  }
  protected set(key: keyof Filters, e: Event): void {
    this.store.setFilters({ [key]: (e.target as HTMLSelectElement).value });
  }
  protected pickDimension(e: Event): void {
    this.store.setSegment((e.target as HTMLSelectElement).value as Dimension, null);
  }
  protected pickQuestion(e: Event): void {
    this.store.setSegment(null, (e.target as HTMLSelectElement).value);
  }
  protected dimLabel(d: Dimension): string {
    return DIM_LABELS[d];
  }
  protected num(v: number | null, digits: number): string {
    return v === null ? 'n/a' : v.toFixed(digits);
  }
  protected signed(v: number | null): string {
    return v === null ? 'n/a' : `${v > 0 ? '+' : ''}${v.toFixed(1)}`;
  }
}
