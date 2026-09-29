import React from 'react';
import { BookOpen, Shield, Cpu, RefreshCw, CheckCircle2, GitMerge } from 'lucide-react';

export const DocsPage: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '28px', maxWidth: '1000px' }}>
      <div>
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '6px' }}>
          DevAgent Architecture & Documentation
        </h2>
        <p style={{ color: 'var(--text-muted)', fontSize: '0.875rem' }}>
          Comprehensive operational guide to DevAgent&apos;s multi-agent orchestration, Docker sandboxing, and repair loops.
        </p>
      </div>

      {/* State Machine Overview */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Cpu size={20} color="var(--primary)" />
          <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Autonomous Workflow State Machine</h3>
        </div>
        <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)', lineHeight: 1.6 }}>
          Tasks transition strictly according to predefined state machines, avoiding invalid or arbitrary skips.
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
            gap: '12px',
          }}
        >
          <div style={{ padding: '14px', borderRadius: '8px', backgroundColor: 'rgba(0, 0, 0, 0.3)', border: '1px solid var(--border-color)' }}>
            <span style={{ color: '#818cf8', fontWeight: 600, fontSize: '0.85rem' }}>1. Planning</span>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
              PlannerAgent queries AST symbols and drafts step-by-step strategy.
            </p>
          </div>

          <div style={{ padding: '14px', borderRadius: '8px', backgroundColor: 'rgba(0, 0, 0, 0.3)', border: '1px solid var(--border-color)' }}>
            <span style={{ color: '#38bdf8', fontWeight: 600, fontSize: '0.85rem' }}>2. Investigating</span>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.4, marginTop: '4px' }}>
              CodebaseAgent extracts relevant functions, classes, and cross-references.
            </p>
          </div>

          <div style={{ padding: '14px', borderRadius: '8px', backgroundColor: 'rgba(0, 0, 0, 0.3)', border: '1px solid var(--border-color)' }}>
            <span style={{ color: '#fbbf24', fontWeight: 600, fontSize: '0.85rem' }}>3. Modifying</span>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.4, marginTop: '4px' }}>
              Applies surgical patches and atomic write operations to sandbox workspace.
            </p>
          </div>

          <div style={{ padding: '14px', borderRadius: '8px', backgroundColor: 'rgba(0, 0, 0, 0.3)', border: '1px solid var(--border-color)' }}>
            <span style={{ color: '#34d399', fontWeight: 600, fontSize: '0.85rem' }}>4. Testing & Repair</span>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.4, marginTop: '4px' }}>
              Runs test runners (pytest / npm test). If tests fail, triggers automated repair loop up to budget.
            </p>
          </div>
        </div>
      </div>

      {/* Security & Sandbox isolation */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Shield size={20} color="#34d399" />
          <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Capability Boundaries & Security</h3>
        </div>

        <ul style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.875rem', color: 'var(--text-muted)', paddingLeft: '20px' }}>
          <li>
            <strong style={{ color: 'var(--text-main)' }}>Non-Root Execution:</strong> All commands execute as unprivileged sandbox users inside transient Docker containers.
          </li>
          <li>
            <strong style={{ color: 'var(--text-main)' }}>Resource Limits:</strong> Max memory capped at 2GB, CPU quota capped at 2.0 cores, process limits enforced via cgroups.
          </li>
          <li>
            <strong style={{ color: 'var(--text-main)' }}>Audit Logging:</strong> Every tool execution, AST query, command stdout, and patch is recorded into the database audit log.
          </li>
          <li>
            <strong style={{ color: 'var(--text-main)' }}>Human-in-the-Loop Gate:</strong> Merging changes into target branches requires developer review and approval.
          </li>
        </ul>
      </div>

      {/* Local Development Commands */}
      <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <BookOpen size={20} color="#f59e0b" />
          <h3 style={{ fontSize: '1.125rem', fontWeight: 600 }}>Quick Reference Scripts</h3>
        </div>

        <div className="code-container" style={{ fontSize: '0.825rem' }}>
          # Launch Backend Dev Server{'\n'}
          .\scripts\dev.ps1 -Target backend{'\n\n'}
          # Launch Frontend Dev Server{'\n'}
          .\scripts\dev.ps1 -Target frontend{'\n\n'}
          # Run All Tests & Linting{'\n'}
          .\scripts\test.ps1 -All
        </div>
      </div>
    </div>
  );
};
