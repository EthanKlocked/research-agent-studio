import { readFileSync } from 'node:fs';
import { expect, it } from 'vitest';
import type { Config } from './types';

it('serves explicit offline capabilities in the browser QA config without network access', async () => {
  const source = readFileSync('qa/dashboard-browser.js', 'utf8');
  const run = new Function(`return (${source});`)();
  let config: Config | undefined;
  const stop = new Error('fixture captured');
  await expect(run({
    route: async (url: string, handler: (route: unknown) => Promise<void>) => {
      expect(url).toBe('**/api/config');
      await handler({ fulfill: async ({ json }: { json: Config }) => { config = json; } });
    },
    addInitScript: async () => { throw stop; },
  })).rejects.toBe(stop);
  expect(config?.capabilities).toEqual({ general_web: false, search_provider: null });
});
