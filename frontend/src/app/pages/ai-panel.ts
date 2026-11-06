import { JsonPipe } from '@angular/common';
import { Component, computed, inject, signal } from '@angular/core';
import { DashboardStore } from '../core/dashboard.store';
import { Claim, Interpretation, Stat } from '../core/models';
import { ChatPanel } from './chat-panel';
import { formatStat } from './format';

@Component({
  selector: 'app-ai-panel',
  imports: [ChatPanel, JsonPipe],
  template: `
    <aside class="ai" aria-label="AI analysis">
      <div class="ai-head">
        <div class="tabs" role="tablist">
          <button role="tab" type="button" [attr.aria-selected]="tab() === 'interpret'" (click)="tab.set('interpret')">Interpretation</button>
          <button role="tab" type="button" data-testid="tab-chat" [attr.aria-selected]="tab() === 'chat'" (click)="tab.set('chat')">Ask the data</button>
        </div>
        <div class="lang" role="group" aria-label="Language of AI output">
          <button type="button" data-testid="lang-en" [attr.aria-pressed]="store.lang() === 'en'" (click)="store.setLang('en')">EN</button>
          <button type="button" data-testid="lang-de" [attr.aria-pressed]="store.lang() === 'de'" (click)="store.setLang('de')">DE</button>
        </div>
      </div>

      @if (tab() === 'chat') {
        <app-chat-panel />
      } @else {
        <div class="ai-body" data-testid="interpretation" [attr.data-state]="stateName()" aria-live="polite">
          @switch (view().kind) {
            @case ('loading') {
              <div class="ai-mark"><span class="badge ai-badge">AI-generated</span><span class="muted">Computing statistics and writing…</span></div>
              <div class="sk line"></div><div class="sk line short"></div><div class="sk block"></div><div class="sk block"></div>
            }
            @case ('error') {
              <div class="state error" role="alert">
                <p>{{ view().message }}</p>
                <button type="button" class="btn" (click)="store.retryInterpretation()">Try again</button>
              </div>
            }
            @case ('result') {
              @let r = view().result!;
              @if (r.status === 'insufficient') {
                <div class="notice" data-testid="insufficient">
                  <h3>{{ de() ? 'Nicht genügend Daten' : 'Not enough data to interpret' }}</h3>
                  @for (w of r.warnings; track w) { <p>{{ w }}</p> }
                  <p class="muted">{{ de() ? 'Es wurde kein KI-Text erzeugt.' : 'No AI text was generated for this filter.' }}</p>
                </div>
              } @else {
                @if (r.status === 'ok') {
                  <div class="ai-mark">
                    <span class="badge ai-badge">AI-generated</span>
                    <span class="badge ok-badge" data-testid="verified">✓ {{ r.validation?.numbers_matched }} of {{ r.validation?.numbers_checked }} figures verified</span>
                  </div>
                } @else {
                  <div class="notice warn" data-testid="fallback">
                    <h3>{{ r.status === 'rate_limited' ? (de() ? 'Demo-Limit erreicht' : 'Demo limit reached') : (de() ? 'KI-Text zurückgehalten' : 'AI text withheld') }}</h3>
                    <p>{{ r.status === 'rate_limited'
                      ? (de() ? 'Hier stehen nur berechnete Werte, ohne KI-Text.' : 'Only computed figures are shown here, with no AI text.')
                      : (de() ? 'Die Prüfung ist zweimal fehlgeschlagen, daher stehen hier nur berechnete Werte.' : 'Verification failed twice, so only computed figures are shown.') }}</p>
                  </div>
                }
                <div class="summary" data-testid="summary">
                  @for (c of r.summary; track c.text) { <p>{{ c.text }}</p> }
                </div>
                @if (r.warnings.length) {
                  <ul class="warnings" data-testid="warnings">
                    @for (w of r.warnings; track w) { <li>{{ w }}</li> }
                  </ul>
                }
                @if (r.findings.length) {
                  <h3 class="sub">{{ de() ? 'Kernergebnisse' : 'Key findings' }}</h3>
                  <ol class="findings">
                    @for (f of r.findings; track f.title; let i = $index) {
                      <li>
                        <button type="button" class="finding" data-testid="finding"
                          [class.active]="store.activeFinding() === i" [attr.aria-pressed]="store.activeFinding() === i"
                          (click)="pick(i, f, r.stats)">
                          <b>{{ f.title }}</b>
                          <span>{{ f.text }}</span>
                          <span class="cites">
                            @for (id of f.cites; track id) {
                              <span class="chip" [title]="statOf(r, id)?.label ?? id">{{ id }}</span>
                            }
                          </span>
                        </button>
                        @if (store.activeFinding() === i) {
                          <table class="evidence" data-testid="evidence">
                            <caption>{{ de() ? 'Zitierte Kennzahlen' : 'Cited statistics' }}</caption>
                            @for (id of f.cites; track id) {
                              @if (statOf(r, id); as s) {
                                <tr><th scope="row"><span class="chip">{{ s.id }}</span> {{ s.label }}</th><td>{{ show(s) }}</td></tr>
                              }
                            }
                          </table>
                        }
                      </li>
                    }
                  </ol>
                }
                @if (r.status === 'ok') {
                  <p class="fine">{{ r.model }} · {{ r.cached ? 'cached' : 'generated now' }}{{ r.attempts > 1 ? ' · regenerated once after a failed check' : '' }}</p>
                  <details class="sent">
                    <summary>What the model received</summary>
                    <p class="fine">Computed statistics only. No rows, no comment text.</p>
                    <pre>{{ r.sent_to_model | json }}</pre>
                  </details>
                }
              }
            }
          }
        </div>
      }
    </aside>
  `,
})
export class AiPanel {
  protected readonly store = inject(DashboardStore);
  protected readonly tab = signal<'interpret' | 'chat'>('interpret');
  protected readonly de = computed(() => this.store.lang() === 'de');
  protected readonly stateName = computed(() => {
    const s = this.store.interpretation();
    return s.state === 'ready' ? s.data.status : s.state;
  });
  protected readonly view = computed(() => {
    const s = this.store.interpretation();
    if (s.state === 'ready') return { kind: 'result' as const, result: s.data, message: '' };
    if (s.state === 'error') return { kind: 'error' as const, result: null, message: s.message };
    return { kind: 'loading' as const, result: null, message: '' };
  });

  protected statOf(r: Interpretation, id: string): Stat | undefined {
    return r.stats.find((s) => s.id === id);
  }
  protected show(s: Stat): string {
    return formatStat(s);
  }
  protected pick(i: number, claim: Claim, stats: Stat[]): void {
    this.store.selectFinding(i, claim, stats);
    const first = this.store.highlights()[0];
    if (first) document.querySelector(`[data-chart="${first.chart}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}
