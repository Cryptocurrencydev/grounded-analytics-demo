import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', title: 'Dashboard · Quorra Insights', loadComponent: () => import('./pages/dashboard.page').then((m) => m.DashboardPage) },
  { path: 'applications', title: 'Applications · Quorra Insights', loadComponent: () => import('./pages/applications.page').then((m) => m.ApplicationsPage) },
  { path: 'eval', title: 'Eval · Quorra Insights', loadComponent: () => import('./pages/eval.page').then((m) => m.EvalPage) },
  { path: 'data-flow', title: 'Data flow · Quorra Insights', loadComponent: () => import('./pages/data-flow.page').then((m) => m.DataFlowPage) },
  { path: '**', redirectTo: '' },
];
