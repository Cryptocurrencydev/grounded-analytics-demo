import { bootstrapApplication } from '@angular/platform-browser';
import { inject } from '@vercel/analytics';
import { appConfig } from './app/app.config';
import { App } from './app/app';

// Initialize Vercel Web Analytics
inject({
  mode: 'auto', // Automatically detects development vs production
  debug: false, // Set to true to see analytics events in console during development
});

bootstrapApplication(App, appConfig).catch((err) => console.error(err));
