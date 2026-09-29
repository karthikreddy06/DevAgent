import React, { useState } from 'react';
import { Modal } from './Modal';
import { api } from '../api/client';
import { Repository, Task, TaskType } from '../types';

interface NewTaskModalProps {
  isOpen: boolean;
  repositories: Repository[];
  onClose: () => void;
  onTaskCreated: (task: Task) => void;
}

export const NewTaskModal: React.FC<NewTaskModalProps> = ({
  isOpen,
  repositories,
  onClose,
  onTaskCreated,
}) => {
  const [repositoryId, setRepositoryId] = useState<string>(
    repositories.length > 0 ? repositories[0].id : ''
  );
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [taskType, setTaskType] = useState<TaskType>('bug');
  const [baseBranch, setBaseBranch] = useState('main');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repositoryId) {
      setError('Please select a repository');
      return;
    }
    if (!title.trim()) {
      setError('Task title is required');
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const task = await api.createTask({
        repository_id: repositoryId,
        title,
        description,
        type: taskType,
        base_branch: baseBranch || 'main',
      });
      onTaskCreated(task);
      onClose();
      // Reset
      setTitle('');
      setDescription('');
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to create task');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Launch New Agent Task"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading || repositories.length === 0}
            className="btn-primary"
          >
            {loading ? 'Creating...' : 'Create & Launch'}
          </button>
        </>
      }
    >
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {error && (
          <div
            style={{
              padding: '8px 12px',
              borderRadius: '6px',
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              color: '#f87171',
              fontSize: '0.8rem',
            }}
          >
            {error}
          </div>
        )}

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Target Repository *
          </label>
          {repositories.length === 0 ? (
            <div style={{ fontSize: '0.8rem', color: '#f87171' }}>
              No repositories available. Please import a repository first.
            </div>
          ) : (
            <select
              className="input-field"
              value={repositoryId}
              onChange={(e) => setRepositoryId(e.target.value)}
            >
              {repositories.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.owner})
                </option>
              ))}
            </select>
          )}
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Task Type *
          </label>
          <select
            className="input-field"
            value={taskType}
            onChange={(e) => setTaskType(e.target.value as TaskType)}
          >
            <option value="bug">Bug Fix (Investigate, Patch, Verify)</option>
            <option value="feature">Feature Request (Implement & Test)</option>
            <option value="security">Security Audit & Remediation</option>
            <option value="docs">Documentation Generation</option>
            <option value="question">Architecture Question / Exploration</option>
          </select>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Task Title *
          </label>
          <input
            type="text"
            required
            className="input-field"
            placeholder="e.g. Fix token expiration check in AuthManager"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Description & Context
          </label>
          <textarea
            className="input-field"
            rows={4}
            placeholder="Describe expected behavior, failing test names, stack traces, or relevant modules..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ resize: 'vertical' }}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Base Branch
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="main"
            value={baseBranch}
            onChange={(e) => setBaseBranch(e.target.value)}
          />
        </div>
      </form>
    </Modal>
  );
};
