import { Component } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header class="top">
      <a class="brand" routerLink="/">
        <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
          <circle cx="11" cy="11" r="8.5" fill="none" stroke="currentColor" stroke-width="2.4" />
          <path d="M13.5 13.5 19 19" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" />
          <path d="M7.5 12.5v-2M11 12.5v-5M14.5 12.5v-3" stroke="#2a78d6" stroke-width="1.8" stroke-linecap="round" />
        </svg>
        <span>Quorra Insights</span>
      </a>
      <nav aria-label="Main">
        <a routerLink="/" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: true }">Dashboard</a>
        <a routerLink="/applications" routerLinkActive="on">Applications</a>
        <a routerLink="/eval" routerLinkActive="on">Eval</a>
        <a routerLink="/data-flow" routerLinkActive="on">Data flow</a>
      </nav>
      <span class="demo-tag">Demo · fictional data</span>
    </header>
    <main><router-outlet /></main>
    <footer class="foot">
      <span>Fictional brand, synthetic data. No real people.</span>
      <span>Demo by <a href="https://dctechltd.com" target="_blank" rel="noopener">DC Tech</a></span>
    </footer>
  `,
})
export class App {}
