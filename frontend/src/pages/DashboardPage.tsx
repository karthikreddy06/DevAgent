import React from 'react';
import {
  FolderGit2,
  ListTodo,
  FileCode,
  ShieldCheck,
  Plus,
  Play,
  ArrowUpRight,
  Clock,
} from 'lucide-react';
import { Repository, Task } from '../types';
import { Badge } from '../components/Badge';

interface DashboardPageProps {
  repositories: Repository[];
  tasks: Task[];
  onSelectTask: (taskId: string) => void;
  onOpenNewTaskModal: () => void;
  onOpenNewRepoModal: () => void;
}

export const DashboardPage: React.FC<DashboardPageProps> = ({
  repositories,
  tasks,
  onSelectTask,
  onOpenNewTaskModal,
  onOpenNewRepoModal,
}) => {
  const activeTasks = tasks.filter(
    (t) =>
      t.status === 'planning' ||
      t.status === 'investigating' ||
      t.status === 'modifying' ||
      t.status === 'testing' ||
      t.status === 'repairing' ||
      t.status === 'awaiting_approval'
  );

  const completedTasks = tasks.filter((t) => t.status === 'completed');
  const indexedRepos = repositories.filter((r) => r.index_status === 'INDEXED' || r.is_indexed);

  const stats = [
    {
      title: 'Indexed Repositories',
      value: `${indexedRepos.length} / ${repositories.length}`,
      icon: FolderGit2,
      color: 'var(--primary)',
      subtext: `${repositories.reduce((acc, r) => acc + (r.indexed_chunks || 0), 0)} search chunks`,
    },
    {
      title: 'Active Agent Tasks',
      value: activeTasks.length.toString(),
      icon: ListTodo,
      color: '#38bdf8',
      subtext: `${tasks.length} total tasks tracked`,
    },
    {
      title: 'Completed Tasks',
      value: completedTasks.length.toString(),
      icon: FileCode,
      color: '#34d399',
      subtext: `${completedTasks.length > 0 ? Math.round((completedTasks.length / tasks.length) * 100) : 100}% resolution rate`,
    },
    {
      title: 'Container Sandboxes',
      value: 'Isolated',
      icon: ShieldCheck,
      color: '#a855f7',
      subtext: 'Docker capability-constrained',
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
      {/* Top Banner with Quick Actions */}
      <div
        className="glass-panel"
        style={{
          padding: '28px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)',
          borderColor: 'rgba(99, 102, 241, 0.2)',
        }}
      >
        <div>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '6px' }}>
            Autonomous Engineering Control Center
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', maxWidth: '600px' }}>
            DevAgent inspects, navigates AST symbols, plans changes, executes in isolated Docker sandboxes, runs tests, and applies automated repair loops.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          <button onClick={onOpenNewRepoModal} className="btn-secondary">
            <Plus size={16} />
            <span>Add Repo</span>
          </button>
          <button onClick={onOpenNewTaskModal} className="btn-primary">
            <Play size={16} />
            <span>Launch Task</span>
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '16px',
        }}
      >
        {stats.map((s, idx) => {
          const Icon = s.icon;
          return (
            <div
              key={idx}
              className="glass-panel"
              style={{
                padding: '20px',
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontWeight: 500 }}>
                  {s.title}
                </span>
                <div
                  style={{
                    padding: '8px',
                    borderRadius: '8px',
                    backgroundColor: 'rgba(255, 255, 255, 0.05)',
                  }}
                >
                  <Icon size={18} color={s.color} />
                </div>
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--text-main)' }}>
                {s.value}
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>{s.subtext}</span>
            </div>
          );
        })}
      </div>

      {/* Active Tasks & Repositories Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.4fr 1fr',
          gap: '24px',
        }}
      >
        {/* Recent Tasks */}
        <div className="glass-panel" style={{ padding: '24px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '16px',
            }}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Recent Tasks</h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {tasks.length} total
            </span>
          </div>

          {tasks.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '36px 0',
                color: 'var(--text-dim)',
                fontSize: '0.875rem',
              }}
            >
              No tasks created yet. Click &quot;Launch Task&quot; to begin.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {tasks.slice(0, 5).map((task) => (
                <div
                  key={task.id}
                  onClick={() => onSelectTask(task.id)}
                  className="glass-card-interactive"
                  style={{
                    padding: '14px 16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Badge type={task.type} />
                      <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>{task.title}</span>
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '12px',
                        fontSize: '0.75rem',
                        color: 'var(--text-dim)',
                      }}
                    >
                      <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <Clock size={12} />
                        {new Date(task.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <span>Branch: {task.base_branch}</span>
                      {task.iteration > 0 && <span>Iteration {task.iteration}</span>}
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Badge status={task.status} />
                    <ArrowUpRight size={16} color="var(--text-dim)" />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Repositories Quick View */}
        <div className="glass-panel" style={{ padding: '24px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '16px',
            }}
          >
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Repositories</h3>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {repositories.length} indexed
            </span>
          </div>

          {repositories.length === 0 ? (
            <div
              style={{
                textAlign: 'center',
                padding: '36px 0',
                color: 'var(--text-dim)',
                fontSize: '0.875rem',
              }}
            >
              No repositories added yet. Click &quot;Add Repo&quot; to import.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {repositories.map((repo) => (
                <div
                  key={repo.id}
                  className="glass-card-interactive"
                  style={{
                    padding: '14px 16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '6px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <FolderGit2 size={16} color="var(--primary)" />
                      <span style={{ fontWeight: 600, fontSize: '0.875rem' }}>{repo.name}</span>
                    </div>
                    <Badge status={(repo.index_status === 'INDEXED' || repo.is_indexed) ? 'completed' : 'queued'}>
                      {(repo.index_status === 'INDEXED' || repo.is_indexed) ? 'Indexed' : 'Pending Index'}
                    </Badge>
                  </div>
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
                    Owner: {repo.owner || (repo.full_name ? repo.full_name.split('/')[0] : 'Unknown')} • Default: {repo.default_branch} • Chunks: {repo.indexed_chunks || 0}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
