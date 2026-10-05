import React, { useState, useEffect } from 'react';
import {
  ListTodo,
  Plus,
  Search,
  Filter,
  ArrowRight,
  GitBranch,
  Repeat,
  AlertCircle,
  Calendar,
} from 'lucide-react';
import { Repository, Task, TaskStatus } from '../types';
import { Badge } from '../components/Badge';

interface TasksPageProps {
  tasks: Task[];
  repositories: Repository[];
  onRefresh?: () => void;
  onSelectTask: (taskId: string) => void;
  onOpenNewTaskModal: () => void;
}

export const TasksPage: React.FC<TasksPageProps> = ({
  tasks,
  repositories,
  onRefresh,
  onSelectTask,
  onOpenNewTaskModal,
}) => {
  useEffect(() => {
    onRefresh?.();
  }, [onRefresh]);

  const [search, setSearch] = useState('');
  const [selectedRepoId, setSelectedRepoId] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');

  const filteredTasks = tasks.filter((t) => {
    const matchesSearch =
      t.title.toLowerCase().includes(search.toLowerCase()) ||
      (t.description && t.description.toLowerCase().includes(search.toLowerCase()));
    const matchesRepo = selectedRepoId === 'all' || t.repository_id === selectedRepoId;
    const matchesStatus = selectedStatus === 'all' || t.status === selectedStatus;
    return matchesSearch && matchesRepo && matchesStatus;
  });

  const getRepoName = (repoId: string) => {
    const found = repositories.find((r) => r.id === repoId);
    return found ? found.name : 'Unknown Repo';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '4px' }}>
            Agent Tasks & Workflows
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Autonomous investigation, code modification, testing, and self-repair runs.
          </p>
        </div>

        <button onClick={onOpenNewTaskModal} className="btn-primary">
          <Plus size={16} />
          <span>New Agent Task</span>
        </button>
      </div>

      {/* Filter Toolbar */}
      <div
        className="glass-panel"
        style={{
          padding: '16px',
          display: 'flex',
          gap: '16px',
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <div style={{ position: 'relative', flex: '1 1 240px' }}>
          <Search
            size={16}
            color="var(--text-dim)"
            style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)' }}
          />
          <input
            type="text"
            className="input-field"
            style={{ paddingLeft: '38px' }}
            placeholder="Search tasks by title or description..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Filter size={16} color="var(--text-dim)" />
          <select
            className="input-field"
            style={{ width: '180px' }}
            value={selectedRepoId}
            onChange={(e) => setSelectedRepoId(e.target.value)}
          >
            <option value="all">All Repositories</option>
            {repositories.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </div>

        <div>
          <select
            className="input-field"
            style={{ width: '180px' }}
            value={selectedStatus}
            onChange={(e) => setSelectedStatus(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="queued">Queued</option>
            <option value="planning">Planning</option>
            <option value="investigating">Investigating</option>
            <option value="modifying">Modifying</option>
            <option value="testing">Testing</option>
            <option value="repairing">Repairing</option>
            <option value="awaiting_approval">Awaiting Approval</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </div>

      {/* Tasks List */}
      {filteredTasks.length === 0 ? (
        <div
          className="glass-panel"
          style={{
            padding: '60px 24px',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '16px',
          }}
        >
          <ListTodo size={48} color="var(--text-dim)" />
          <div>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '6px' }}>
              No Matching Tasks Found
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
              Try adjusting your search filters or launch a new autonomous task.
            </p>
          </div>
          <button onClick={onOpenNewTaskModal} className="btn-primary">
            <Plus size={16} />
            <span>Create New Task</span>
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {filteredTasks.map((task) => (
            <div
              key={task.id}
              onClick={() => onSelectTask(task.id)}
              className="glass-card-interactive"
              style={{
                padding: '18px 22px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxWidth: '75%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Badge type={task.type} />
                  <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>{task.title}</h3>
                </div>

                {task.description && (
                  <p
                    style={{
                      fontSize: '0.825rem',
                      color: 'var(--text-muted)',
                      lineHeight: '1.4',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      maxWidth: '680px',
                    }}
                  >
                    {task.description}
                  </p>
                )}

                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '16px',
                    fontSize: '0.75rem',
                    color: 'var(--text-dim)',
                  }}
                >
                  <span>Repo: <strong>{getRepoName(task.repository_id)}</strong></span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <GitBranch size={12} />
                    {task.base_branch}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Repeat size={12} />
                    Iteration {task.iteration} / {task.max_iterations}
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                    <Calendar size={12} />
                    {new Date(task.created_at).toLocaleDateString()}
                  </span>
                </div>

                {task.error_message && (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '6px',
                      fontSize: '0.75rem',
                      color: '#f87171',
                    }}
                  >
                    <AlertCircle size={12} />
                    <span>{task.error_message}</span>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                <Badge status={task.status as TaskStatus} />
                <button
                  className="btn-secondary"
                  style={{ padding: '8px 14px', fontSize: '0.825rem' }}
                >
                  <span>Inspect</span>
                  <ArrowRight size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
