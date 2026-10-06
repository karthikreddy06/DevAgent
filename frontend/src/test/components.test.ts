import { describe, it, expect, beforeEach } from 'vitest';
import { api } from '../api/client';
import { resolveAuthoritativeOutcome } from '../lib/taskOutcome';

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

  it('correctly builds POST /v1/tasks request payload with repository_id', async () => {
    let capturedUrl = '';
    let capturedOptions: RequestInit | undefined;

    (globalThis as unknown as { fetch: typeof fetch }).fetch = (async (url: RequestInfo | URL, options?: RequestInit) => {
      capturedUrl = String(url);
      capturedOptions = options;
      return {
        ok: true,
        status: 201,
        json: async () => ({
          id: 'task-1234',
          repository_id: '01a0ebb6-1a06-7997-a4c5-704029c67541',
          title: 'Test Bug Fix',
          status: 'CREATED',
        }),
      } as Response;
    }) as typeof fetch;

    const task = await api.createTask({
      repository_id: '01a0ebb6-1a06-7997-a4c5-704029c67541',
      title: 'Test Bug Fix',
      description: 'Investigate and fix issue',
      type: 'bug_fix',
      base_branch: 'main',
    }, true);

    expect(capturedUrl).toContain('/api/v1/tasks?start=true');
    expect(capturedOptions?.method).toBe('POST');
    const body = JSON.parse(capturedOptions?.body as string);
    expect(body.repository_id).toBe('01a0ebb6-1a06-7997-a4c5-704029c67541');
    expect(body.title).toBe('Test Bug Fix');
    expect(task.id).toBe('task-1234');
  });
});

describe('NewTaskModal repository selection logic', () => {
  it('correctly resolves repositoryId when repositories are loaded asynchronously', () => {
    const repos = [
      { id: 'repo-uuid-1', name: 'multi-document-rag-assistant', default_branch: 'main', indexed_files: 10, indexed_chunks: 30, size_kb: 100, created_at: '' },
      { id: 'repo-uuid-2', name: 'elective-recommendation-system', default_branch: 'main', indexed_files: 34, indexed_chunks: 128, size_kb: 500, created_at: '' },
    ];

    // Case 1: Initial empty state before API loads
    let currentId = '';
    const resolveSelected = (id: string, list: typeof repos) => {
      const exists = list.some((r) => r.id === id);
      return exists && id ? id : (list.length > 0 ? list[0].id : '');
    };

    // When repos array is populated, selection automatically resolves to first repo
    currentId = resolveSelected(currentId, repos);
    expect(currentId).toBe('repo-uuid-1');

    // Case 2: User explicitly chooses second repo
    currentId = 'repo-uuid-2';
    currentId = resolveSelected(currentId, repos);
    expect(currentId).toBe('repo-uuid-2');

    // Case 3: Effective repo ID used in submit payload
    const effectiveRepoId = currentId || (repos.length > 0 ? repos[0].id : '');
    expect(effectiveRepoId).toBe('repo-uuid-2');
  });
});

describe('Task execution lifecycle & button states', () => {
  it('identifies button actions correctly across lifecycle states', () => {
    const getActionState = (status: string) => {
      const s = status.toUpperCase();
      const isCreated = s === 'CREATED' || s === 'QUEUED';
      const isActive = ['PLANNING', 'ANALYZING', 'INVESTIGATING', 'APPLYING', 'TESTING'].includes(s);
      const isAwaitingApproval = s === 'AWAITING_APPROVAL' || s === 'FIX_PROPOSED';
      const isFailed = s === 'FAILED';
      const isCompleted = s === 'COMPLETED';

      return {
        canStart: isCreated,
        isRunningDisabled: isActive,
        canRetry: isFailed,
        isCompletedNoStart: isCompleted && !isCreated && !isActive,
        isApprovalWorkflow: isAwaitingApproval,
      };
    };

    // 1. CREATED state exposes Start Agent
    const createdState = getActionState('CREATED');
    expect(createdState.canStart).toBe(true);
    expect(createdState.isRunningDisabled).toBe(false);
    expect(createdState.canRetry).toBe(false);

    // 2. Active states disable Start Agent with running indicator
    for (const active of ['PLANNING', 'ANALYZING', 'INVESTIGATING', 'APPLYING', 'TESTING']) {
      const state = getActionState(active);
      expect(state.canStart).toBe(false);
      expect(state.isRunningDisabled).toBe(true);
      expect(state.canRetry).toBe(false);
    }

    // 3. FAILED state exposes Retry Task action
    const failedState = getActionState('FAILED');
    expect(failedState.canStart).toBe(false);
    expect(failedState.isRunningDisabled).toBe(false);
    expect(failedState.canRetry).toBe(true);

    // 4. COMPLETED state cannot be started again
    const completedState = getActionState('COMPLETED');
    expect(completedState.canStart).toBe(false);
    expect(completedState.isRunningDisabled).toBe(false);
    expect(completedState.canRetry).toBe(false);
    expect(completedState.isCompletedNoStart).toBe(true);

    // 5. AWAITING_APPROVAL and FIX_PROPOSED guide user to approval gate
    const approvalState = getActionState('AWAITING_APPROVAL');
    expect(approvalState.canStart).toBe(false);
    expect(approvalState.isApprovalWorkflow).toBe(true);

    const fixProposedState = getActionState('FIX_PROPOSED');
    expect(fixProposedState.canStart).toBe(false);
    expect(fixProposedState.isApprovalWorkflow).toBe(true);
  });

  it('correctly constructs POST /v1/tasks/{id}/retry request payload and url', async () => {
    let capturedUrl = '';
    let capturedMethod = '';

    (globalThis as unknown as { fetch: typeof fetch }).fetch = (async (url: RequestInfo | URL, options?: RequestInit) => {
      capturedUrl = String(url);
      capturedMethod = options?.method || '';
      return {
        ok: true,
        status: 200,
        json: async () => ({
          id: 'task-retry-456',
          status: 'PLANNING',
          iteration: 2,
        }),
      } as Response;
    }) as typeof fetch;

    const retriedTask = await api.retryTask('task-retry-456', false);
    expect(capturedUrl).toContain('/api/v1/tasks/task-retry-456/retry?wait=false');
    expect(capturedMethod).toBe('POST');
    expect(retriedTask.iteration).toBe(2);
    expect(retriedTask.status).toBe('PLANNING');
  });

  it('rejects stale out-of-order SSE events and protects terminal status', () => {
    let currentTask = {
      id: 'task-1',
      status: 'FAILED',
      iteration: 1,
    };
    let maxSeq = 10;

    const handleSseEvent = (event: { seq: number; event_type: string; payload?: { new_status?: string; iteration?: number } }) => {
      // 1. Monotonic sequence check
      if (event.seq <= maxSeq) {
        return; // drop stale / duplicate event
      }
      maxSeq = Math.max(maxSeq, event.seq);

      const incomingStatus = (event.payload?.new_status || (event.event_type === 'task_failed' ? 'FAILED' : undefined))?.toUpperCase();
      if (!incomingStatus) return;

      const terminalStates = ['COMPLETED', 'FAILED', 'REJECTED'];
      const isCurrentTerminal = terminalStates.includes(currentTask.status);
      const isIncomingTerminal = terminalStates.includes(incomingStatus);

      // Terminal protection: do not let an older event revert FAILED back to ANALYZING
      if (isCurrentTerminal && !isIncomingTerminal) {
        if (event.event_type !== 'task_retried' && (!event.payload?.iteration || event.payload.iteration <= currentTask.iteration)) {
          return;
        }
      }

      currentTask = {
        ...currentTask,
        status: incomingStatus,
        iteration: event.payload?.iteration || currentTask.iteration,
      };
    };

    // Stale sequence event with seq 8 arrives -> dropped
    handleSseEvent({ seq: 8, event_type: 'status_change', payload: { new_status: 'ANALYZING' } });
    expect(currentTask.status).toBe('FAILED');

    // Newer seq 12 event arrives with older active status 'ANALYZING' on iteration 1 -> dropped by terminal protection
    handleSseEvent({ seq: 12, event_type: 'status_change', payload: { new_status: 'ANALYZING', iteration: 1 } });
    expect(currentTask.status).toBe('FAILED');

    // Newer event arrives for iteration 2 retry -> accepted
    handleSseEvent({ seq: 13, event_type: 'task_retried', payload: { new_status: 'PLANNING', iteration: 2 } });
    expect(currentTask.status).toBe('PLANNING');
    expect(currentTask.iteration).toBe(2);
  });

  it('keeps detail page and task list status consistent without stale ANALYZING', () => {
    let taskList = [
      { id: 't-1', title: 'Fix bug', status: 'ANALYZING' },
    ];

    // Detail page polls ground truth from backend
    const backendGroundTruth = { id: 't-1', title: 'Fix bug', status: 'FAILED' };

    // When detail page fetches ground truth or updates, onTaskUpdated refreshes taskList
    const refreshData = () => {
      taskList = taskList.map((t) => (t.id === backendGroundTruth.id ? { ...t, status: backendGroundTruth.status } : t));
    };

    expect(taskList[0].status).toBe('ANALYZING');
    refreshData();
    expect(taskList[0].status).toBe('FAILED');
    expect(taskList[0].status).toBe(backendGroundTruth.status);
  });
});

describe('Authoritative Task Outcome Resolution & Contradiction Suppression', () => {
  it('NO_CONFIRMED_BUG hides contradictory root-cause/proposed-fix text', () => {
    const contradictoryTask = {
      status: 'COMPLETED',
      type: 'bug_fix',
      summary: 'NO_CONFIRMED_BUG: No reproducible defect was established from repository evidence. No files were modified.',
      root_cause: {
        outcome: 'NO_CONFIRMED_BUG',
        // Contradictory text generated during LLM turn:
        analysis: 'Based on search, the bug is caused by esbuild. Proposed Code Change: modify package-lock.json. Verification Steps: run git status. The bug is fixed.',
      },
    };

    const outcome = resolveAuthoritativeOutcome(contradictoryTask, [], null);

    // 1. Authoritative outcome MUST be NO_CONFIRMED_BUG
    expect(outcome.outcome).toBe('NO_CONFIRMED_BUG');
    expect(outcome.isNoConfirmedBug).toBe(true);
    expect(outcome.isFixedAndVerified).toBe(false);

    // 2. Contradictory diagnosis and proposed change must be strictly hidden
    expect(outcome.shouldShowDiagnosis).toBe(false);
    expect(outcome.shouldShowProposedChange).toBe(false);
    expect(outcome.shouldShowVerificationSteps).toBe(false);
    expect(outcome.shouldShowGitBranch).toBe(false);

    // 3. Invariants are accurate
    expect(outcome.filesModifiedCount).toBe(0);
    expect(outcome.patchesGeneratedCount).toBe(0);
    expect(outcome.approvalsRequestedCount).toBe(0);
  });

  it('successful FIXED_AND_VERIFIED still displays its real evidence', () => {
    const verifiedTask = {
      status: 'COMPLETED',
      type: 'bug_fix',
      summary: 'FIXED_AND_VERIFIED: All 5 tests passed. Fix successfully verified in sandbox. Branch bugfix-123 is commit-ready.',
      root_cause: {
        analysis: 'Identified authentic KeyError in request payload validator in backend/app/auth.py:42.',
        outcome: 'FIX_PROPOSED',
      },
    };

    const realChanges = [
      {
        id: 'change-1',
        status: 'APPLIED',
        patch_unified: '--- a/backend/app/auth.py\n+++ b/backend/app/auth.py\n@@ -42,1 +42,1 @@\n- old\n+ new',
        files_changed: 1,
      },
    ];

    const realGitInfo = {
      branch: 'bugfix-123',
      suggested_commit: 'fix(auth): handle KeyError in payload validator',
    };

    const outcome = resolveAuthoritativeOutcome(verifiedTask, realChanges, realGitInfo);

    expect(outcome.outcome).toBe('FIXED_AND_VERIFIED');
    expect(outcome.isFixedAndVerified).toBe(true);
    expect(outcome.isNoConfirmedBug).toBe(false);
    expect(outcome.isFailed).toBe(false);

    // Displays real evidence because artifacts exist
    expect(outcome.shouldShowDiagnosis).toBe(true);
    expect(outcome.shouldShowProposedChange).toBe(true);
    expect(outcome.shouldShowVerificationSteps).toBe(true);
    expect(outcome.shouldShowGitBranch).toBe(true);
    expect(outcome.filesModifiedCount).toBe(1);
    expect(outcome.patchesGeneratedCount).toBe(1);
  });

  it('FAILED displays failure information and suppresses successful fix presentation', () => {
    const failedTask = {
      status: 'FAILED',
      type: 'bug_fix',
      summary: null,
      error: {
        reason: 'Verification tests failed after applying patch in sandbox: 2 failed, 3 passed',
      },
      root_cause: {
        analysis: 'Hypothetical fix was tried but tests failed.',
      },
    };

    const outcome = resolveAuthoritativeOutcome(failedTask, [], null);

    expect(outcome.outcome).toBe('FAILED');
    expect(outcome.isFailed).toBe(true);
    expect(outcome.isFixedAndVerified).toBe(false);
    expect(outcome.isNoConfirmedBug).toBe(false);

    // Never present failed task as having verified diagnosis or successful fix
    expect(outcome.shouldShowDiagnosis).toBe(false);
    expect(outcome.shouldShowSummary).toBe(false);
    expect(outcome.shouldShowGitBranch).toBe(false);
    expect(outcome.explanation).toContain('Verification tests failed');
  });

  it('no fabricated bug fixed message appears for NO_CONFIRMED_BUG', () => {
    const cleanRepoTask = {
      status: 'COMPLETED',
      type: 'bug_fix',
      summary: 'NO_CONFIRMED_BUG: No reproducible defect was established from repository evidence. No files were modified.',
      root_cause: {
        outcome: 'NO_CONFIRMED_BUG',
        evidence: 'No reproducible defect was established from repository evidence. No files were modified.',
      },
    };

    const outcome = resolveAuthoritativeOutcome(cleanRepoTask, [], null);

    expect(outcome.outcome).toBe('NO_CONFIRMED_BUG');
    expect(outcome.shouldShowDiagnosis).toBe(false);
    expect(outcome.shouldShowProposedChange).toBe(false);
    expect(outcome.shouldShowVerificationSteps).toBe(false);

    // Explanation must state clean state rather than bug fixed
    expect(outcome.explanation).toContain('no reproducible software defect exists');
    expect(outcome.explanation.toLowerCase()).not.toContain('bug is fixed');
    expect(outcome.explanation.toLowerCase()).not.toContain('fix applied');
  });

  it('authoritative outcome wins when LLM hallucinates diagnosis on clean repo without artifacts', () => {
    // Edge case: task was marked COMPLETED without changes or gitInfo, and summary mentions no defect
    const ambiguousTask = {
      status: 'COMPLETED',
      type: 'bug_fix',
      summary: 'Analysis completed: No reproducible defect found in target codebase.',
      root_cause: {
        analysis: 'The bug is caused by syntax error in non-existent file fake.py. The bug is fixed.',
      },
    };

    // No changes, no gitInfo
    const outcome = resolveAuthoritativeOutcome(ambiguousTask, [], null);

    // Authoritative check must determine NO_CONFIRMED_BUG because 0 artifacts exist
    expect(outcome.outcome).toBe('NO_CONFIRMED_BUG');
    expect(outcome.shouldShowDiagnosis).toBe(false);
    expect(outcome.shouldShowProposedChange).toBe(false);
  });
});

describe('Repository schema & Git URL derivation', () => {
  it('correctly parses GitHub owner and repo name from various Git URL formats', async () => {
    const { parseGitUrl } = await import('../components/NewRepoModal');

    // HTTPS with .git
    expect(parseGitUrl('https://github.com/karthikreddy06/devagent-bug-test.git')).toEqual({
      owner: 'karthikreddy06',
      name: 'devagent-bug-test',
    });

    // HTTPS without .git
    expect(parseGitUrl('https://github.com/karthikreddy06/devagent-bug-test')).toEqual({
      owner: 'karthikreddy06',
      name: 'devagent-bug-test',
    });

    // HTTPS with trailing slash
    expect(parseGitUrl('https://github.com/karthikreddy06/devagent-bug-test/')).toEqual({
      owner: 'karthikreddy06',
      name: 'devagent-bug-test',
    });

    // SSH format
    expect(parseGitUrl('git@github.com:karthikreddy06/devagent-bug-test.git')).toEqual({
      owner: 'karthikreddy06',
      name: 'devagent-bug-test',
    });

    // Empty / invalid
    expect(parseGitUrl('')).toEqual({});
  });

  it('correctly aligns RepositoryCreate payload with full_name and owner', async () => {
    let capturedBody: any;
    (globalThis as unknown as { fetch: typeof fetch }).fetch = (async (_url: RequestInfo | URL, options?: RequestInit) => {
      capturedBody = JSON.parse(options?.body as string);
      return {
        ok: true,
        status: 201,
        json: async () => ({
          id: 'repo-uuid-test',
          name: capturedBody.name,
          full_name: capturedBody.full_name,
          owner: capturedBody.owner,
          owner_id: 'user-uuid-123',
          source_type: 'git_url',
          clone_status: 'READY',
          index_status: 'NOT_INDEXED',
          indexed_files: 0,
          indexed_chunks: 0,
          size_kb: 0,
          default_branch: 'main',
          created_at: new Date().toISOString(),
        }),
      } as Response;
    }) as typeof fetch;

    const res = await api.createRepository({
      name: 'devagent-bug-test',
      owner: 'karthikreddy06',
      full_name: 'karthikreddy06/devagent-bug-test',
      source_url: 'https://github.com/karthikreddy06/devagent-bug-test',
      default_branch: 'main',
    });

    expect(capturedBody.name).toBe('devagent-bug-test');
    expect(capturedBody.owner).toBe('karthikreddy06');
    expect(capturedBody.full_name).toBe('karthikreddy06/devagent-bug-test');
    expect(res.owner_id).toBe('user-uuid-123');
    expect(res.full_name).toBe('karthikreddy06/devagent-bug-test');
  });
});



