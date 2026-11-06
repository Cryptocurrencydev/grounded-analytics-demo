import { Component, computed, ElementRef, inject, signal, viewChild, effect } from '@angular/core';
import { DashboardStore } from '../core/dashboard.store';
import { ChatResult, Stat } from '../core/models';
import { formatStat } from './format';

@Component({
  selector: 'app-chat-panel',
  template: `
    <div class="chat" data-testid="chat">
      <div class="chat-log" #log aria-live="polite">
        @if (!store.messages().length) {
          <p class="muted">{{ de() ? 'Fragen Sie die Daten. Jede Zahl kommt aus einer geprüften Abfrage.' : 'Ask about the survey. Every figure comes from a checked query, and the AI cannot write its own.' }}</p>
          <div class="suggest">
            @for (s of suggestions; track s) {
              <button type="button" (click)="send(s)">{{ s }}</button>
            }
          </div>
        }
        @for (m of store.messages(); track $index) {
          @if (m.role === 'user') {
            <div class="msg user">{{ m.text }}</div>
          } @else {
            <div class="msg bot" data-testid="chat-answer" [attr.data-type]="m.result?.answer_type">
              <div class="ai-mark">
                <span class="badge ai-badge">AI-generated</span>
                @if (m.result?.validation?.ok && m.result!.claims.length) {
                  <span class="badge ok-badge">✓ {{ m.result!.validation!.numbers_matched }} of {{ m.result!.validation!.numbers_checked }} {{ m.result!.validation!.numbers_checked === 1 ? 'figure' : 'figures' }} verified</span>
                }
                @switch (m.result?.answer_type) {
                  @case ('cannot_answer') { <span class="badge plain">Can't answer from this data</span> }
                  @case ('insufficient_data') { <span class="badge plain">Too few responses</span> }
                  @case ('filters_applied') { <span class="badge plain">Dashboard updated</span> }
                  @case ('unverified') { <span class="badge warn-badge">Answer withheld</span> }
                }
              </div>
              @for (c of m.result?.claims; track c.text) {
                <p>{{ c.text }}
                  @for (id of c.cites; track id) {
                    <span class="chip" [title]="stat(m.result!, id)?.label ?? id">{{ id }}</span>
                  }
                </p>
              }
              @if (m.result?.message) { <p>{{ m.result!.message }}</p> }
              @if (m.result?.stats?.length && m.result?.answer_type !== 'cannot_answer') {
                <details class="sent">
                  <summary>Figures from the tools ({{ m.result!.stats.length }})</summary>
                  <table class="evidence">
                    @for (s of m.result!.stats; track s.id) {
                      <tr><th scope="row"><span class="chip">{{ s.id }}</span> {{ s.label }}</th><td>{{ show(s) }}</td></tr>
                    }
                  </table>
                </details>
              }
            </div>
          }
        }
        @if (store.chatBusy()) {
          <div class="msg bot"><span class="muted">Querying the data…</span></div>
        }
      </div>
      <form class="chat-input" (submit)="submit($event)">
        <input data-testid="chat-input" type="text" maxlength="500" autocomplete="off"
          [placeholder]="de() ? 'Frage zu den Daten…' : 'Ask about the data…'" aria-label="Question"
          [value]="draft()" (input)="draft.set($any($event.target).value)" />
        <button class="btn" type="submit" data-testid="chat-send" [disabled]="!draft().trim() || store.chatBusy()">{{ de() ? 'Senden' : 'Send' }}</button>
      </form>
    </div>
  `,
})
export class ChatPanel {
  protected readonly store = inject(DashboardStore);
  protected readonly draft = signal('');
  protected readonly de = computed(() => this.store.lang() === 'de');
  private log = viewChild<ElementRef<HTMLElement>>('log');
  protected readonly suggestions = [
    'Which department has the lowest workload score?',
    'Did workload change significantly in Operations between 2025 and 2026?',
    'Show me only the North region in 2026',
    'What is the average salary?',
  ];

  constructor() {
    effect(() => {
      this.store.messages();
      this.store.chatBusy();
      const el = this.log()?.nativeElement;
      if (el) queueMicrotask(() => (el.scrollTop = el.scrollHeight));
    });
  }

  protected send(text: string): void {
    this.store.ask(text);
    this.draft.set('');
  }
  protected submit(e: Event): void {
    e.preventDefault();
    const text = this.draft().trim();
    if (text && !this.store.chatBusy()) this.send(text);
  }
  protected stat(r: ChatResult, id: string): Stat | undefined {
    return r.stats.find((s) => s.id === id);
  }
  protected show(s: Stat): string {
    return formatStat(s);
  }
}
