import React, { useState } from 'react';
import { FolderGit2, RefreshCw, Plus, HardDrive, GitBranch, Layers, CheckCircle2 } from 'lucide-react';
import { Repository } from '../types';
import { Badge } from '../components/Badge';
import { api } from '../api/client';

interface RepositoriesPageProps {
  repositories: Repository[];
  onRefresh: () => void;
  onOpenNewRepoModal: () => void;
}

export const RepositoriesPage: React.FC<RepositoriesPageProps> = ({
  repositories,
  onRefresh,
  onOpenNewRepoModal,
}) => {
  const [indexingId, setIndexingId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const handleIndex = async (repoId: string) => {
    setIndexingId(repoId);
    setMessage(null);
    try {
      await api.indexRepository(repoId);
      setMessage('Repository indexing triggered successfully in background worker.');
      onRefresh();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setMessage(`Indexing failed: ${err.message}`);
      } else {
        setMessage('Indexing failed');
      }
    } finally {
      setIndexingId(null);
    }
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
            Codebase Repositories
          </h2>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
            Manage target projects, AST semantic indexes, and Docker sandbox bind mounts.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '12px' }}>
          <button onClick={onRefresh} className="btn-secondary">
            <RefreshCw size={16} />
            <span>Refresh</span>
          </button>
          <button onClick={onOpenNewRepoModal} className="btn-primary">
            <Plus size={16} />
            <span>Import Repository</span>
          </button>
        </div>
      </div>

      {message && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            backgroundColor: message.includes('failed')
              ? 'rgba(239, 68, 68, 0.15)'
              : 'rgba(16, 185, 129, 0.15)',
            border: `1px solid ${
              message.includes('failed')
                ? 'rgba(239, 68, 68, 0.3)'
                : 'rgba(16, 185, 129, 0.3)'
            }`,
            color: message.includes('failed') ? '#f87171' : '#34d399',
            fontSize: '0.875rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          <CheckCircle2 size={16} />
          <span>{message}</span>
        </div>
      )}

      {repositories.length === 0 ? (
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
          <FolderGit2 size={48} color="var(--text-dim)" />
          <div>
            <h3 style={{ fontSize: '1.125rem', fontWeight: 600, marginBottom: '6px' }}>
              No Repositories Configured
            </h3>
            <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem', maxWidth: '440px' }}>
              Add a local codebase directory or a git remote URL to enable autonomous search, planning, and sandboxed test execution.
            </p>
          </div>
          <button onClick={onOpenNewRepoModal} className="btn-primary">
            <Plus size={16} />
            <span>Import First Repository</span>
          </button>
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
            gap: '20px',
          }}
        >
          {repositories.map((repo) => (
            <div
              key={repo.id}
              className="glass-panel"
              style={{
                padding: '24px',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'space-between',
                gap: '20px',
              }}
            >
              <div>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    justifyContent: 'space-between',
                    marginBottom: '12px',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div
                      style={{
                        padding: '10px',
                        borderRadius: '8px',
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        border: '1px solid rgba(99, 102, 241, 0.2)',
                      }}
                    >
                      <FolderGit2 size={20} color="var(--primary)" />
                    </div>
                    <div>
                      <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>{repo.name}</h3>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                        {repo.owner || (repo.full_name ? repo.full_name.split('/')[0] : 'Unknown')}
                      </span>
                    </div>
                  </div>

                  <Badge status={(repo.index_status === 'INDEXED' || repo.is_indexed) ? 'completed' : 'queued'}>
                    {(repo.index_status === 'INDEXED' || repo.is_indexed) ? 'Indexed' : 'Unindexed'}
                  </Badge>
                </div>

                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '8px',
                    fontSize: '0.8rem',
                    color: 'var(--text-muted)',
                    backgroundColor: 'rgba(0, 0, 0, 0.2)',
                    padding: '12px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <GitBranch size={14} color="var(--text-dim)" />
                    <span>Default Branch: <strong>{repo.default_branch}</strong></span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Layers size={14} color="var(--text-dim)" />
                    <span>
                      Files: <strong>{repo.indexed_files || 0}</strong> • Chunks: <strong>{repo.indexed_chunks || 0}</strong>
                    </span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <HardDrive size={14} color="var(--text-dim)" />
                    <span>
                      Disk Size: <strong>{repo.size_kb ? `${(repo.size_kb / 1024).toFixed(1)} MB` : 'Unknown'}</strong>
                    </span>
                  </div>
                  {repo.local_path && (
                    <div
                      style={{
                        fontSize: '0.725rem',
                        color: 'var(--text-dim)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                      title={repo.local_path}
                    >
                      Path: {repo.local_path}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                <button
                  onClick={() => handleIndex(repo.id)}
                  disabled={indexingId === repo.id}
                  className="btn-secondary"
                  style={{ width: '100%', fontSize: '0.825rem' }}
                >
                  <RefreshCw
                    size={14}
                    style={{
                      animation: indexingId === repo.id ? 'spin 1s linear infinite' : 'none',
                    }}
                  />
                  <span>{indexingId === repo.id ? 'Indexing...' : 'Index Codebase'}</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
