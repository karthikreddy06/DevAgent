import React, { useState, useEffect } from 'react';
import { Modal } from './Modal';
import { api } from '../api/client';
import { Repository, Task, TaskType } from '../types';

interface NewTaskModalProps {
  isOpen: boolean;
  repositories: Repository[];
  initialRepositoryId?: string;
  onClose: () => void;
  onTaskCreated: (task: Task) => void;
}

export const NewTaskModal: React.FC<NewTaskModalProps> = ({
  isOpen,
  repositories,
  initialRepositoryId,
  onClose,
  onTaskCreated,
}) => {
  const [repositoryId, setRepositoryId] = useState<string>(
    initialRepositoryId || (repositories.length > 0 ? repositories[0].id : '')
  );
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [taskType, setTaskType] = useState<TaskType>('bug_fix');
  const [baseBranch, setBaseBranch] = useState('main');
  const [targetFilesInput, setTargetFilesInput] = useState('');
  const [testCommandInput, setTestCommandInput] = useState('pytest');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Synchronize repository selection with repositories prop and modal open state
  useEffect(() => {
    if (!isOpen) return;

    setError(null);
    if (repositories.length > 0) {
      setRepositoryId((currentId) => {
        if (initialRepositoryId && repositories.some((r) => r.id === initialRepositoryId)) {
          return initialRepositoryId;
        }
        const exists = repositories.some((r) => r.id === currentId);
        return exists && currentId ? currentId : repositories[0].id;
      });
    } else {
      setRepositoryId('');
    }
  }, [isOpen, repositories, initialRepositoryId]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const effectiveRepoId = repositoryId || (repositories.length > 0 ? repositories[0].id : '');
    if (!effectiveRepoId) {
      setError('Please select a repository');
      return;
    }
    if (!title.trim()) {
      setError('Task title is required');
      return;
    }

    setLoading(true);
    setError(null);

    const parsedTargetFiles = targetFilesInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);

    try {
      const task = await api.createTask({
        repository_id: effectiveRepoId,
        title: title.trim(),
        description: description.trim(),
        type: taskType,
        base_branch: baseBranch || 'main',
        target_files: parsedTargetFiles.length > 0 ? parsedTargetFiles : undefined,
        test_command: testCommandInput.trim() || undefined,
      }, true);
      onTaskCreated(task);
      onClose();
      // Reset form
      setTitle('');
      setDescription('');
      setTargetFilesInput('');
      setTestCommandInput('pytest');
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to create and start task');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Create Autonomous Agent Task"
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
            style={{
              background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
              fontWeight: 600,
            }}
          >
            {loading ? 'Starting Task...' : 'Start Task'}
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
              value={repositoryId || (repositories.length > 0 ? repositories[0].id : '')}
              onChange={(e) => {
                setRepositoryId(e.target.value);
                if (error) setError(null);
              }}
            >
              {repositories.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.name} ({r.full_name ? r.full_name.split('/')[0] : (r.owner || 'local')}) — {r.index_status || 'READY'}
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
            <option value="bug_fix">BUG_FIX — Investigate, Propose Patch & Verify</option>
            <option value="feature">FEATURE — Autonomous Feature Implementation</option>
            <option value="refactor">REFACTOR — Code Modernization & Refactoring</option>
            <option value="test">TEST — Test Suite & Regression Hardening</option>
            <option value="documentation">DOCUMENTATION — API Docs & Schema Typing</option>
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
            placeholder="e.g. Fix invalid prediction input handling"
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
            placeholder="Describe the issue, expected behavior, failing scenarios, or relevant endpoints..."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            style={{ resize: 'vertical' }}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Optional Target Files
            </label>
            <input
              type="text"
              className="input-field"
              placeholder="e.g. backend/app/schemas.py"
              value={targetFilesInput}
              onChange={(e) => setTargetFilesInput(e.target.value)}
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
              Optional Test Command
            </label>
            <input
              type="text"
              className="input-field"
              placeholder="pytest"
              value={testCommandInput}
              onChange={(e) => setTestCommandInput(e.target.value)}
            />
          </div>
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

