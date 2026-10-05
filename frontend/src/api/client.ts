import {
  AuthTokens,
  Change,
  ChatSession,
  Repository,
  RepositoryCreate,
  Task,
  TaskEvent,
  User,
} from '../types';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';

class ApiClient {
  private getToken(): string | null {
    if (
      typeof window !== 'undefined' &&
      typeof localStorage !== 'undefined'
    ) {
      return localStorage.getItem('devagent_token');
    }

    return null;
  }

  public setToken(token: string | null) {
    if (
      typeof window !== 'undefined' &&
      typeof localStorage !== 'undefined'
    ) {
      if (token) {
        localStorage.setItem('devagent_token', token);
      } else {
        localStorage.removeItem('devagent_token');
      }
    }
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const token = this.getToken();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...((options.headers as Record<string, string>) || {}),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (response.status === 401) {
      this.setToken(null);
    }

    if (!response.ok) {
      let errorMessage = `HTTP error! status: ${response.status}`;

      try {
        const errorData = await response.json();
        if (errorData?.error?.message) {
          const main = errorData.error.message;
          const problems = errorData.error.details?.problems;
          if (Array.isArray(problems) && problems.length > 0) {
            errorMessage = `${main}: ${problems.join(', ')}`;
          } else {
            errorMessage = main;
          }
        } else if (errorData?.detail) {
          if (Array.isArray(errorData.detail)) {
            errorMessage = errorData.detail
              .map((d: any) => (typeof d === 'string' ? d : d.msg || JSON.stringify(d)))
              .join('; ');
          } else {
            errorMessage = String(errorData.detail);
          }
        } else if (errorData?.message) {
          errorMessage = errorData.message;
        }
      } catch {
        // Use fallback message
      }

      throw new Error(errorMessage);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  // ============================================================
  // Auth
  // ============================================================

  async login(
    credentials: {
      email?: string;
      username?: string;
      password: string;
    }
  ): Promise<AuthTokens> {
    const data = await this.request<AuthTokens>('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });

    this.setToken(data.access_token);

    return data;
  }

  async register(
    data: {
      email: string;
      username: string;
      password: string;
    }
  ): Promise<AuthTokens> {
    const res = await this.request<AuthTokens>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        email: data.email,
        username: data.username,
        full_name: data.username,
        password: data.password,
      }),
    });

    this.setToken(res.access_token);

    return res;
  }

  async getMe(): Promise<User> {
    return this.request<User>('/v1/auth/me');
  }

  // ============================================================
  // Repositories
  // ============================================================

  async listRepositories(): Promise<Repository[]> {
    return this.request<Repository[]>('/v1/repositories');
  }

  async getRepository(id: string): Promise<Repository> {
    return this.request<Repository>(`/v1/repositories/${id}`);
  }

  async createRepository(
    data: RepositoryCreate
  ): Promise<Repository> {
    return this.request<Repository>('/v1/repositories', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async indexRepository(
    id: string
  ): Promise<{
    status: string;
    repository_id: string;
    job_id?: string;
  }> {
    return this.request(`/v1/repositories/${id}/index`, {
      method: 'POST',
    });
  }

  // ============================================================
  // Tasks
  // ============================================================

  async listTasks(
    params?: {
      repository_id?: string;
      status?: string;
    }
  ): Promise<Task[]> {
    const searchParams = new URLSearchParams();

    if (params?.repository_id) {
      searchParams.append(
        'repository_id',
        params.repository_id
      );
    }

    if (params?.status) {
      searchParams.append(
        'status',
        params.status
      );
    }

    const query = searchParams.toString()
      ? `?${searchParams.toString()}`
      : '';

    return this.request<Task[]>(
      `/v1/tasks${query}`
    );
  }

  async getTask(id: string): Promise<Task> {
    return this.request<Task>(
      `/v1/tasks/${id}`
    );
  }

  async createTask(
    data: {
      repository_id: string;
      title: string;
      description?: string;
      type?: string;
      base_branch?: string;
      target_files?: string[];
      test_command?: string;
    },
    start: boolean = true
  ): Promise<Task> {
    const query = start ? '?start=true' : '?start=false';
    return this.request<Task>(`/v1/tasks${query}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async runTask(
    id: string,
    wait: boolean = false
  ): Promise<{
    status: string;
    task_id: string;
  }> {
    return this.request(
      `/v1/tasks/${id}/run?wait=${wait}`,
      {
        method: 'POST',
      }
    );
  }


  async cancelTask(id: string): Promise<Task> {
    return this.request<Task>(
      `/v1/tasks/${id}/cancel`,
      {
        method: 'POST',
      }
    );
  }

  async retryTask(id: string, wait: boolean = false): Promise<Task> {
    return this.request<Task>(
      `/v1/tasks/${id}/retry?wait=${wait}`,
      {
        method: 'POST',
      }
    );
  }

  async listTaskEvents(taskId: string): Promise<TaskEvent[]> {
    return this.request<TaskEvent[]>(`/v1/tasks/${taskId}/events`);
  }

  // ============================================================
  // SSE Stream for Task Events
  // ============================================================

  streamTaskEvents(
    taskId: string,
    onEvent: (event: TaskEvent) => void,
    onError?: (err: unknown) => void
  ): () => void {
    const token = this.getToken();

    const url =
      `${API_BASE}/v1/tasks/${taskId}/events/stream` +
      (token
        ? `?token=${encodeURIComponent(token)}`
        : '');

    const eventSource = new EventSource(url);

    const handleMessage = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data);
        if (parsed && typeof parsed === 'object') {
          if (parsed.event_type === 'stream_done') {
            eventSource.close();
            return;
          }
          onEvent(parsed);
        }
      } catch (err) {
        console.error('Failed to parse SSE event', err);
      }
    };

    eventSource.onmessage = handleMessage;
    eventSource.addEventListener('task_event', handleMessage as EventListener);
    eventSource.addEventListener('done', () => {
      eventSource.close();
    });

    eventSource.onerror = (err) => {
      if (onError) {
        onError(err);
      }
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }

  // ============================================================
  // Changes & Approvals
  // ============================================================

  async listChanges(
    taskId?: string
  ): Promise<Change[]> {
    const query = taskId
      ? `?task_id=${taskId}`
      : '';

    return this.request<Change[]>(
      `/v1/changes${query}`
    );
  }

  async getChange(id: string): Promise<Change> {
    return this.request<Change>(
      `/v1/changes/${id}`
    );
  }

  async reviewChange(
    id: string,
    approved: boolean,
    reason?: string
  ): Promise<Change> {
    return this.request<Change>(
      `/v1/changes/${id}/review`,
      {
        method: 'POST',
        body: JSON.stringify({
          approved,
          reason,
        }),
      }
    );
  }

  // ============================================================
  // Chat
  // ============================================================

  async createChatSession(
    taskId?: string,
    title?: string
  ): Promise<ChatSession> {
    return this.request<ChatSession>(
      '/v1/chats/sessions',
      {
        method: 'POST',
        body: JSON.stringify({
          task_id: taskId,
          title: title || 'Agent Chat',
        }),
      }
    );
  }

  async getChatSession(
    sessionId: string
  ): Promise<ChatSession> {
    return this.request<ChatSession>(
      `/v1/chats/sessions/${sessionId}`
    );
  }

  async sendChatMessage(
    sessionId: string,
    content: string
  ): Promise<ChatSession> {
    return this.request<ChatSession>(
      `/v1/chats/sessions/${sessionId}/messages`,
      {
        method: 'POST',
        body: JSON.stringify({
          content,
        }),
      }
    );
  }

  // ============================================================
  // Health
  // ============================================================

  async getHealth(): Promise<{
    status: string;
    environment: string;
    version: string;
  }> {
    return this.request('/v1/health');
  }
}

export const api = new ApiClient();