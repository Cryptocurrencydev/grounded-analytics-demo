// The eval page renders from eval/results.json. Nothing on it is typed by hand.
import { copyFileSync, existsSync } from 'node:fs';
const source = new URL('../../eval/results.json', import.meta.url);
if (existsSync(source)) {
  copyFileSync(source, new URL('../public/eval-results.json', import.meta.url));
  console.log('copied eval results');
} else {
  console.log('no eval results yet');
}
