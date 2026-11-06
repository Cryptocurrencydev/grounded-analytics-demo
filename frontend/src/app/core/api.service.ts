import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  AppDetail, AppListItem, AppSummary, ChatMessage, ChatResult, Dashboard, Filters, Interpretation, Lang, Meta,
} from './models';

/** Everything the UI asks of the backend. Swap the base path to mount in another app. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = '/api';

  meta(): Observable<Meta> {
    return this.http.get<Meta>(`${this.base}/meta`);
  }
  dashboard(filters: Filters): Observable<Dashboard> {
    return this.http.post<Dashboard>(`${this.base}/dashboard`, { filters });
  }
  interpret(filters: Filters, lang: Lang): Observable<Interpretation> {
    return this.http.post<Interpretation>(`${this.base}/interpret`, { filters, lang });
  }
  chat(question: string, filters: Filters, lang: Lang, history: ChatMessage[]): Observable<ChatResult> {
    const turns = history.map((m) => ({ role: m.role, text: m.text }));
    return this.http.post<ChatResult>(`${this.base}/chat`, { question, filters, lang, history: turns });
  }
  applications(): Observable<AppListItem[]> {
    return this.http.get<AppListItem[]>(`${this.base}/applications`);
  }
  application(id: string): Observable<AppDetail> {
    return this.http.get<AppDetail>(`${this.base}/applications/${id}`);
  }
  summary(id: string, lang: Lang): Observable<AppSummary> {
    return this.http.post<AppSummary>(`${this.base}/applications/${id}/summary`, { lang });
  }
}
