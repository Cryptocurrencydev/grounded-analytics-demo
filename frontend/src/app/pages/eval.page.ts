import { HttpClient } from '@angular/common/http';
import { Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, of } from 'rxjs';

interface Side {
  questions: number; numeric_total: number; numeric_correct: number; significance_total: number; significance_correct: number;
  refusal_total: number; refusal_correct: number; answers_with_unsupported_figures: number; unsupported_figures: number;
  over_refusals: number; withheld: number; no_answer: number; regenerated: number; input_tokens: number; output_tokens: number; mean_latency_s: number;
}
interface Answer {
  answer_type: string; text: string; correct: boolean; refused: boolean; unsupported: string[]; latency_s: number;
  attempts?: number; tool_calls?: string[]; rejected_issues?: string[];
}
interface Row {
  id: string; category: string; question: string; refuse: boolean; significance: boolean | null;
  expected: { name: string; value: number; decimals: number; unit: string }[]; n?: number[];
  baseline: Answer; grounded: Answer;
}
interface Results {
  generated_at: string; mode: string; model: string; effort: { baseline: string; grounded: string }; baseline_prompt_chars: number;
  summary: { baseline: Side; grounded: Side }; questions: Row[];
}

const CATEGORIES: Record<string, string> = {
  all: 'All', numeric: 'Numeric', comparison: 'Comparison', significance: 'Significance', unanswerable: 'Unanswerable', tiny_sample: 'Tiny sample',
};

@Component({
  selector: 'app-eval',
  template: `
    <div class="page-head">
      <h1>Eval: raw data in the prompt vs grounded</h1>
      <p>Same model, same questions, same rules. Expected answers are computed straight from the data file. This page renders a committed JSON file from real model runs, so no figure here is typed by hand.</p>
    </div>
    @if (results() === undefined) {
      <div class="sk block"></div><div class="sk block"></div>
    } @else if (results() === null) {
      <div class="state empty" data-testid="eval-empty">No eval results have been committed yet.</div>
    } @else {
      @let r = results()!;
      @let b = r.summary.baseline;
      @let g = r.summary.grounded;
      <section class="versus" data-testid="eval-summary">
        <div class="vs-head"><span></span><h2>Naive baseline<small>raw rows in the prompt</small></h2><h2>Grounded<small>tools + validator</small></h2></div>
        <div class="vs-row"><span>Numeric answers correct</span><b data-testid="base-numeric">{{ b.numeric_correct }} / {{ b.numeric_total }}</b><b data-testid="ground-numeric">{{ g.numeric_correct }} / {{ g.numeric_total }}</b></div>
        <div class="vs-row"><span>Significance calls correct</span><b>{{ b.significance_correct }} / {{ b.significance_total }}</b><b>{{ g.significance_correct }} / {{ g.significance_total }}</b></div>
        <div class="vs-row"><span>Answers stating a figure not found in the data</span><b data-testid="base-halluc">{{ b.answers_with_unsupported_figures }}</b><b data-testid="ground-halluc">{{ g.answers_with_unsupported_figures }}</b></div>
        <div class="vs-row"><span>Figures not found in the data, in total</span><b>{{ b.unsupported_figures }}</b><b>{{ g.unsupported_figures }}</b></div>
        <div class="vs-row"><span>Correct refusals (unanswerable, tiny samples)</span><b>{{ b.refusal_correct }} / {{ b.refusal_total }}</b><b>{{ g.refusal_correct }} / {{ g.refusal_total }}</b></div>
        <div class="vs-row"><span>Refused an answerable question</span><b>{{ b.over_refusals }}</b><b>{{ g.over_refusals }}</b></div>
        <div class="vs-row"><span>Questions with no usable answer</span><b>{{ b.no_answer }}</b><b>{{ g.no_answer + g.withheld }}</b></div>
        <div class="vs-row"><span>Input tokens, all questions</span><b>{{ b.input_tokens.toLocaleString('en-GB') }}</b><b>{{ g.input_tokens.toLocaleString('en-GB') }}</b></div>
        <div class="vs-row"><span>Mean time per answer</span><b>{{ b.mean_latency_s }} s</b><b>{{ g.mean_latency_s }} s</b></div>
      </section>
      <p class="fine">Run {{ r.generated_at }} · {{ r.model }} · baseline effort {{ r.effort.baseline }}, grounded effort {{ r.effort.grounded }} · {{ r.questions.length }} questions, one run each.
        Raw data sent to the model: baseline every row and comment on each question, grounded none.</p>

      <div class="chips-row" role="group" aria-label="Filter questions">
        @for (c of categories; track c[0]) {
          <button type="button" [attr.aria-pressed]="category() === c[0]" (click)="category.set(c[0])">{{ c[1] }}</button>
        }
      </div>
      <div class="table-wrap">
        <table class="eval-table" data-testid="eval-table">
          <thead><tr><th scope="col">Question</th><th scope="col">Expected</th><th scope="col">Baseline</th><th scope="col">Grounded</th></tr></thead>
          <tbody>
            @for (q of rows(); track q.id) {
              <tr>
                <td><small>{{ q.id }} · {{ label(q.category) }}</small>{{ q.question }}</td>
                <td>{{ expected(q) }}</td>
                <td [class.bad]="!q.baseline.correct" [class.good]="q.baseline.correct">
                  <b>{{ q.baseline.correct ? '✓' : '✗' }}</b> {{ q.baseline.text }}
                  @if (q.baseline.unsupported.length) { <small>Unsupported: {{ q.baseline.unsupported.join(', ') }}</small> }
                </td>
                <td [class.bad]="!q.grounded.correct" [class.good]="q.grounded.correct">
                  <b>{{ q.grounded.correct ? '✓' : '✗' }}</b> {{ q.grounded.text || q.grounded.answer_type }}
                  @if (q.grounded.unsupported.length) { <small>Unsupported: {{ q.grounded.unsupported.join(', ') }}</small> }
                  @if ((q.grounded.attempts ?? 1) > 1) { <small>Regenerated after the validator rejected the first answer</small> }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
      <h2 class="sub2">How it is scored</h2>
      <ul class="plain">
        <li>Both systems get the same rules, including the 30-response minimum, and return the same answer type field. Only the text a user would see is scored.</li>
        <li>A numeric answer is correct when each expected figure appears, under the same rounding rules as the validator.</li>
        <li>Every other number in an answer is checked against a wide table of true figures for the slices in that question: counts, sums, means, SDs, shares, per-quarter values, differences, t and degrees of freedom. A number that matches nothing is counted as not found. The table is wide on purpose, so a wrong count can match by chance. That favours the baseline. p-values are not scored, because they depend on rounding and the test chosen.</li>
        <li>A refusal is correct when the system declines and states no invented figure.</li>
        <li>The baseline ran at a higher effort setting than the grounded system, to give it its best chance.</li>
      </ul>
    }
  `,
})
export class EvalPage {
  private http = inject(HttpClient);
  protected readonly results = toSignal<Results | null | undefined>(
    this.http.get<Results>('/eval-results.json').pipe(catchError(() => of(null))),
    { initialValue: undefined },
  );
  protected readonly category = signal('all');
  protected readonly categories = Object.entries(CATEGORIES);
  protected readonly rows = computed(() => {
    const all = this.results()?.questions ?? [];
    const c = this.category();
    return c === 'all' ? all : all.filter((q) => q.category === c);
  });

  protected label(c: string): string {
    return CATEGORIES[c] ?? c;
  }
  protected expected(q: Row): string {
    if (q.category === 'tiny_sample') return `Refuse: n = ${q.n?.join(', ')}`;
    if (q.refuse) return 'Refuse: not in the data';
    if (q.significance !== null) return q.significance ? 'Significant' : 'Not significant';
    return q.expected.map((e) => e.value.toFixed(e.decimals) + (e.unit === 'pct' ? '%' : e.unit === 'pp' ? ' pp' : '')).join(', ');
  }
}
