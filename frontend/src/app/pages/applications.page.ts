import { JsonPipe } from '@angular/common';
import { Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';
import { ApiService } from '../core/api.service';
import { DashboardStore } from '../core/dashboard.store';
import { AppDetail, AppSummary, Load } from '../core/models';

@Component({
  selector: 'app-applications',
  imports: [JsonPipe],
  template: `
    <div class="page-head">
      <h1>Application summaries</h1>
      <p>Every statement names the fields it came from. Missing and contradictory fields are flagged, never filled in.</p>
    </div>
    <div class="apps">
      <nav class="app-list" aria-label="Applications">
        @if (list() === null) {
          <div class="state error" role="alert">Could not load the applications.</div>
        }
        @for (a of list(); track a.id) {
          <button type="button" data-testid="app-item" [class.on]="a.id === selected()" (click)="selected.set(a.id)">
            <b>{{ a.organisation }}</b>
            <span>{{ a.project_title }}</span>
            <small>{{ a.id }} · {{ a.submitted_on }}</small>
          </button>
        }
      </nav>
      <section class="app-summary" aria-label="AI summary">
        <div class="ai-head">
          <h2>Summary</h2>
          <div class="lang" role="group" aria-label="Language of AI output">
            <button type="button" [attr.aria-pressed]="store.lang() === 'en'" (click)="store.setLang('en')">EN</button>
            <button type="button" [attr.aria-pressed]="store.lang() === 'de'" (click)="store.setLang('de')">DE</button>
          </div>
        </div>
        @switch (summary().state) {
          @case ('loading') {
            <div class="sk line"></div><div class="sk line"></div><div class="sk line short"></div><div class="sk block"></div>
          }
          @case ('error') { <div class="state error" role="alert">The summary could not be loaded.</div> }
          @case ('ready') {
            @let s = ready()!;
            @if (s.status === 'ok') {
              <div class="ai-mark"><span class="badge ai-badge">AI-generated</span><span class="badge ok-badge" data-testid="app-verified">✓ {{ s.numbers_checked }} {{ s.numbers_checked === 1 ? 'figure' : 'figures' }} traced to fields</span></div>
              <ul class="statements" data-testid="statements">
                @for (st of s.statements; track st.text) {
                  <li (mouseenter)="hover.set(st.fields)" (mouseleave)="hover.set([])">
                    <span>{{ st.text }}</span>
                    <span class="cites">@for (f of st.fields; track f) { <span class="chip">{{ f }}</span> }</span>
                  </li>
                }
              </ul>
            } @else {
              <div class="notice warn" data-testid="app-fallback">
                <h3>{{ s.status === 'rate_limited' ? 'Demo limit reached' : 'AI summary withheld' }}</h3>
                <p>Only rule-based flags are shown below. The submitted fields are unchanged.</p>
              </div>
            }
            <h3 class="sub">Flags</h3>
            @if (s.flags.length) {
              <ul class="flags" data-testid="flags">
                @for (fl of s.flags; track fl.text) {
                  <li [class]="fl.kind" (mouseenter)="hover.set(fl.fields)" (mouseleave)="hover.set([])">
                    <b>{{ fl.kind === 'missing' ? 'Missing' : 'Contradiction' }}</b>
                    <span>{{ fl.text }}</span>
                    <small>{{ fl.source === 'rule' ? 'found by rule' : 'found by AI' }} · {{ fl.fields.join(', ') }}</small>
                  </li>
                }
              </ul>
            } @else {
              <p class="muted" data-testid="no-flags">No missing fields or contradictions found.</p>
            }
            @if (s.sent_to_model) {
              <details class="sent">
                <summary>What the model received</summary>
                <p class="fine">Contact name and email are removed before sending.</p>
                <pre>{{ s.sent_to_model | json }}</pre>
              </details>
            }
          }
        }
      </section>
      <section class="app-fields" aria-label="Submitted fields">
        <h2>Submitted fields</h2>
        @if (detail(); as d) {
          <table class="fields">
            @for (f of d.fields; track f.key) {
              <tr [class.hot]="hover().includes(f.key)" [class.missing]="f.missing">
                <th scope="row">{{ f.label }}</th>
                <td>
                  @if (f.missing) { <span class="badge warn-badge">not provided</span> }
                  @else if (f.pii) { {{ f.value }} <span class="badge plain">not sent to AI</span> }
                  @else { {{ f.value }} }
                </td>
              </tr>
            }
          </table>
        } @else {
          <div class="sk block"></div><div class="sk block"></div>
        }
      </section>
    </div>
  `,
})
export class ApplicationsPage {
  protected readonly store = inject(DashboardStore);
  private api = inject(ApiService);
  protected readonly list = toSignal(this.api.applications().pipe(catchError(() => of(null))), { initialValue: [] });
  protected readonly selected = signal('APP-1042');
  protected readonly detail = signal<AppDetail | null>(null);
  protected readonly summary = signal<Load<AppSummary>>({ state: 'loading' });
  protected readonly hover = signal<string[]>([]);
  protected readonly ready = computed(() => {
    const s = this.summary();
    return s.state === 'ready' ? s.data : null;
  });

  constructor() {
    effect((onCleanup) => {
      const id = this.selected();
      const lang = this.store.lang();
      this.detail.set(null);
      this.summary.set({ state: 'loading' });
      const a = this.api.application(id).subscribe({ next: (d) => this.detail.set(d) });
      const b = this.api.summary(id, lang).subscribe({
        next: (data) => this.summary.set({ state: 'ready', data }),
        error: () => this.summary.set({ state: 'error', message: '' }),
      });
      onCleanup(() => { a.unsubscribe(); b.unsubscribe(); });
    });
  }
}
