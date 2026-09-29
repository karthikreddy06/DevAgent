import { describe, it, expect, beforeEach } from 'vitest';
import { api } from '../api/client';

describe('Diff parsing logic', () => {
  it('correctly categorizes patch lines into additions and deletions', () => {
    const patch = `--- a/main.py
+++ b/main.py
@@ -1,3 +1,3 @@
-def foo(): return 1
+def foo(): return 2
 def bar(): return 3`;

    const lines = patch.split('\n');
    let additions = 0;
    let deletions = 0;

    lines.forEach((line) => {
      if (line.startsWith('+') && !line.startsWith('+++')) additions++;
      if (line.startsWith('-') && !line.startsWith('---')) deletions++;
    });

    expect(additions).toBe(1);
    expect(deletions).toBe(1);
  });
});

describe('ApiClient Configuration', () => {
  beforeEach(() => {
    const storage: Record<string, string> = {};
    (globalThis as unknown as { localStorage: Storage }).localStorage = {
      getItem: (key: string) => storage[key] || null,
      setItem: (key: string, val: string) => {
        storage[key] = val;
      },
      removeItem: (key: string) => {
        delete storage[key];
      },
      clear: () => {
        Object.keys(storage).forEach((k) => delete storage[k]);
      },
      key: () => null,
      length: 0,
    };
    (globalThis as unknown as { window: unknown }).window = globalThis;
  });

  it('has proper API base and token storage methods', () => {
    expect(api).toBeDefined();
    expect(typeof api.login).toBe('function');
    expect(typeof api.listRepositories).toBe('function');
    expect(typeof api.createTask).toBe('function');
    expect(typeof api.streamTaskEvents).toBe('function');

    api.setToken('test-token-xyz');
    expect(globalThis.localStorage.getItem('devagent_token')).toBe('test-token-xyz');

    api.setToken(null);
    expect(globalThis.localStorage.getItem('devagent_token')).toBeNull();
  });
});
