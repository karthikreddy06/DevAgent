import React from 'react';
import { GitCommit, Plus, Minus } from 'lucide-react';

interface DiffViewerProps {
  patch: string;
  filesChanged?: string[];
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ patch, filesChanged }) => {
  if (!patch || !patch.trim()) {
    return (
      <div
        className="glass-panel"
        style={{
          padding: '24px',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.875rem',
        }}
      >
        No unified diff content available.
      </div>
    );
  }

  const lines = patch.split('\n');
  let additions = 0;
  let deletions = 0;

  lines.forEach((line) => {
    if (line.startsWith('+') && !line.startsWith('+++')) additions++;
    if (line.startsWith('-') && !line.startsWith('---')) deletions++;
  });

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '12px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          backgroundColor: 'rgba(255, 255, 255, 0.03)',
          borderRadius: '8px',
          border: '1px solid var(--border-color)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.825rem' }}>
          <GitCommit size={16} color="var(--primary)" />
          <span style={{ fontWeight: 600 }}>Proposed Changes</span>
          {filesChanged && filesChanged.length > 0 && (
            <span style={{ color: 'var(--text-dim)', fontSize: '0.75rem' }}>
              ({filesChanged.join(', ')})
            </span>
          )}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '0.75rem' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '2px', color: '#34d399' }}>
            <Plus size={14} /> {additions}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '2px', color: '#f87171' }}>
            <Minus size={14} /> {deletions}
          </span>
        </div>
      </div>

      <div
        className="code-container"
        style={{
          maxHeight: '400px',
          overflowY: 'auto',
          lineHeight: '1.4',
          whiteSpace: 'pre',
        }}
      >
        {lines.map((line, idx) => {
          let lineStyle: React.CSSProperties = {
            padding: '1px 8px',
            display: 'block',
          };

          if (line.startsWith('diff --git') || line.startsWith('index ')) {
            lineStyle = {
              ...lineStyle,
              color: 'var(--primary)',
              fontWeight: 600,
              backgroundColor: 'rgba(99, 102, 241, 0.08)',
            };
          } else if (line.startsWith('@@')) {
            lineStyle = {
              ...lineStyle,
              color: '#38bdf8',
              backgroundColor: 'rgba(56, 189, 248, 0.08)',
              fontWeight: 500,
            };
          } else if (line.startsWith('+') && !line.startsWith('+++')) {
            lineStyle = {
              ...lineStyle,
              backgroundColor: 'rgba(16, 185, 129, 0.15)',
              color: '#6ee7b7',
            };
          } else if (line.startsWith('-') && !line.startsWith('---')) {
            lineStyle = {
              ...lineStyle,
              backgroundColor: 'rgba(239, 68, 68, 0.15)',
              color: '#fca5a5',
            };
          }

          return (
            <span key={idx} style={lineStyle}>
              {line || ' '}
            </span>
          );
        })}
      </div>
    </div>
  );
};
