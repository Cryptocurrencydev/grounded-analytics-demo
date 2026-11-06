import { Component } from '@angular/core';

@Component({
  selector: 'app-data-flow',
  template: `
    <div class="page-head">
      <h1>What leaves the server</h1>
      <p>The model provider sees computed statistics, never survey rows. This is what each feature sends.</p>
    </div>
    <div class="table-wrap">
      <table class="flow">
        <thead><tr><th scope="col">Feature</th><th scope="col">Sent to the model</th><th scope="col">Never sent</th></tr></thead>
        <tbody>
          <tr><th scope="row">AI interpretation</th>
            <td>The stat sheet: labels, n, means, shares, changes, test results. Comment themes as counts and shares, with hashed reference ids.</td>
            <td>Rows, response ids, comment text.</td></tr>
          <tr><th scope="row">Ask the data</th>
            <td>The question, current filter values, up to 6 earlier chat turns, and tool results, which are aggregates only.</td>
            <td>Rows, response ids, comment text, SQL. The model cannot run a query of its own.</td></tr>
          <tr><th scope="row">Application summaries</th>
            <td>Application fields and the free-text section, with emails and phone numbers scrubbed.</td>
            <td>Contact name, contact email.</td></tr>
          <tr><th scope="row">Charts and KPIs</th><td>Nothing. No model is involved.</td><td>Everything.</td></tr>
        </tbody>
      </table>
    </div>
    <h2 class="sub2">Safeguards</h2>
    <ul class="plain">
      <li>Filters under 30 responses get no AI text. Segments under 30 are left out of comparisons.</li>
      <li>Cells under 5 responses are hidden from the API altogether.</li>
      <li>Raw comment text is not part of the deployed function. Only theme ids are.</li>
      <li>Visitor addresses are stored only as salted hashes, for rate limiting.</li>
      <li>This demo calls the Anthropic API directly, which is not EU-hosted. The README lists EU-hosted routes for production.</li>
    </ul>
  `,
})
export class DataFlowPage {}
