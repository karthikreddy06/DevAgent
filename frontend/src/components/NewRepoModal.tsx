import React, { useState } from 'react';
import { Modal } from './Modal';
import { api } from '../api/client';
import { Repository } from '../types';

interface NewRepoModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRepoCreated: (repo: Repository) => void;
}

export const NewRepoModal: React.FC<NewRepoModalProps> = ({
  isOpen,
  onClose,
  onRepoCreated,
}) => {
  const [name, setName] = useState('');
  const [owner, setOwner] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [gitUrl, setGitUrl] = useState('');
  const [defaultBranch, setDefaultBranch] = useState('main');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !owner) {
      setError('Name and Owner are required');
      return;
    }
    setLoading(true);
    setError(null);
                                                                                                                                                                                                        try {
      const repo = await api.createRepository({
        name,
        owner,
        local_path: localPath || undefined,
        source_url: gitUrl || undefined,
        default_branch: defaultBranch || 'main',
      });
      onRepoCreated(repo);
      onClose();
      // reset form
      setName('');
      setOwner('');
      setLocalPath('');
      setGitUrl('');
    } catch (err: unknown) {
      if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Failed to create repository');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Import Repository"
      footer={
        <>
          <button type="button" onClick={onClose} className="btn-secondary">
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="btn-primary"
          >
            {loading ? 'Importing...' : 'Import Repository'}
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
            Repository Name *
          </label>
          <input
            type="text"
            required
            className="input-field"
            placeholder="e.g. auth-service"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Owner / Organization *
          </label>
          <input
            type="text"
            required
            className="input-field"
            placeholder="e.g. acme-corp"
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Local Filesystem Path (Optional)
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="e.g. C:\projects\auth-service"
            value={localPath}
            onChange={(e) => setLocalPath(e.target.value)}
          />
          <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)', marginTop: '2px', display: 'block' }}>
            Used for local sandbox mount during development
          </span>
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Remote Git URL (Optional)
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="https://github.com/acme/auth-service.git"
            value={gitUrl}
            onChange={(e) => setGitUrl(e.target.value)}
          />
        </div>

        <div>
          <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
            Default Branch
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="main"
            value={defaultBranch}
            onChange={(e) => setDefaultBranch(e.target.value)}
          />
        </div>
      </form>
    </Modal>
  );
};
