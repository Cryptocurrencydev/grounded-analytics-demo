import { afterRenderEffect, DestroyRef, Directive, ElementRef, inject, input } from '@angular/core';
import Highcharts from './highcharts';

/** Thin wrapper: one Highcharts instance per element, updated in place when the options change. */
@Directive({ selector: '[qChart]' })
export class ChartDirective {
  readonly options = input.required<Highcharts.Options>({ alias: 'qChart' });
  private chart?: Highcharts.Chart;

  constructor() {
    const el = inject<ElementRef<HTMLElement>>(ElementRef).nativeElement;
    afterRenderEffect(() => {
      const options = this.options();
      if (this.chart) this.chart.update(options, true, true, { duration: 250 });
      else this.chart = Highcharts.chart(el, options);
    });
    inject(DestroyRef).onDestroy(() => this.chart?.destroy());
  }
}
