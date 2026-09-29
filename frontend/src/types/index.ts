export type UserRole = 'admin' | 'developer' | 'viewer';

export interface User {
  id: string;
  email: string;
  username: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface AuthTokens {
  access_token: string;
  token_type: string;
}

export interface Repository {
  id: string;
  name: string;
  owner?: string;
  full_name?: string;
  owner_id?: string;
  local_path?: string;
  source_url?: string;
  git_url?: string;
  default_branch: string;
  clone_status?: string;
  index_status?: string;
  analysis_status?: string;
  is_indexed?: boolean;
  indexed_files: number;
  indexed_chunks: number;
  size_kb: number;
  indexed_at?: string;
  created_at: string;
  updated_at?: string;
}

export interface RepositoryCreate {
  name: string;
  owner: string;
  local_path?: string;
  source_url?: string;
  default_branch?: string;
}

export type TaskType = 'bug' | 'feature' | 'question' | 'security' | 'docs';

export type TaskStatus =
  | 'queued'
  | 'planning'
  | 'analyzing'
  | 'investigating'
  | 'fix_proposed'
  | 'awaiting_approval'
  | 'applying'
  | 'modifying'
  | 'testing'
  | 'repairing'
  | 'completed'
  | 'rejected'
  | 'failed'
  | 'cancelled'
  | 'CREATED'
  | 'PLANNING'
  | 'ANALYZING'
  | 'INVESTIGATING'
  | 'FIX_PROPOSED'
  | 'AWAITING_APPROVAL'
  | 'APPLYING'
  | 'TESTING'
  | 'COMPLETED'
  | 'FAILED'
  | 'REJECTED'
  | string;

export interface Task {
  id: string;
  repository_id: string;
  user_id?: string;
  title: string;
  description?: string;
  type: TaskType;
  status: TaskStatus;
  base_branch: string;
  target_branch?: string;
  fix_branch?: string;
  iteration: number;
  max_iterations: number;
  error_message?: string;
  plan?: { text?: string } | null;
  root_cause?: { analysis?: string } | null;
  summary?: string | null;
  error?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface Change {
  id: string;
  task_id: string;
  patch_unified: string;
  files_changed: string[];
  summary?: string;
  status: 'pending' | 'approved' | 'rejected' | 'merged';
  test_status: 'pending' | 'passed' | 'failed' | 'skipped';
  reviewed_at?: string;
  reviewed_by?: string;
  created_at: string;
}

export interface Approval {
  id: string;
  change_id: string;
  approved: boolean;
  reason?: string;
  approved_by?: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  meta_data?: Record<string, unknown>;
  created_at: string;
}

export interface ChatSession {
  id: string;
  task_id?: string;
  title: string;
  created_at: string;
  messages: ChatMessage[];
}

export interface TaskEvent {
  event_type: string;
  task_id: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface TestResult {
  passed: boolean;
  exit_code: number;
  stdout: string;
  stderr: string;
  test_count: number;
  failed_count: number;
}
