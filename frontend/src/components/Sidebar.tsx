import React from 'react';
import { LayoutDashboard, FolderGit2, ListTodo, BookOpen, ShieldCheck } from 'lucide-react';

export type ActiveTab = 'dashboard' | 'repositories' | 'tasks' | 'docs';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  taskCount?: number;
  repoCount?: number;
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  taskCount = 0,
  repoCount = 0,
}) => {
  const navItems = [
    {
      id: 'dashboard' as ActiveTab,
      label: 'Dashboard',
      icon: LayoutDashboard,
    },
    {
      id: 'repositories' as ActiveTab,
      label: 'Repositories',
      icon: FolderGit2,
      count: repoCount,
    },
    {
      id: 'tasks' as ActiveTab,
      label: 'Agent Tasks',
      icon: ListTodo,
      count: taskCount,
    },
    {
      id: 'docs' as ActiveTab,
      label: 'Documentation',
      icon: BookOpen,
    },
  ];

  return (
    <aside
      style={{
        width: '240px',
        borderRight: '1px solid var(--border-color)',
        backgroundColor: 'rgba(15, 23, 42, 0.5)',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        padding: '20px 12px',
        flexShrink: 0,
        height: 'calc(100vh - 64px)',
        position: 'sticky',
        top: '64px',
      }}
    >
      <nav style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <div
          style={{
            padding: '4px 12px 10px',
            fontSize: '0.675rem',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-dim)',
          }}
        >
          Navigation
        </div>

        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                borderRadius: '8px',
                border: 'none',
                background: isActive
                  ? 'linear-gradient(90deg, rgba(99, 102, 241, 0.2) 0%, rgba(139, 92, 246, 0.1) 100%)'
                  : 'transparent',
                color: isActive ? '#f8fafc' : 'var(--text-muted)',
                fontWeight: isActive ? 600 : 400,
                fontSize: '0.875rem',
                cursor: 'pointer',
                textAlign: 'left',
                transition: 'all 0.15s ease',
                boxShadow: isActive ? 'inset 3px 0 0 var(--primary)' : 'none',
              }}
              onMouseEnter={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
              }}
              onMouseLeave={(e) => {
                if (!isActive) e.currentTarget.style.backgroundColor = 'transparent';
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Icon size={18} color={isActive ? 'var(--primary)' : 'currentColor'} />
                <span>{item.label}</span>
              </div>
              {item.count !== undefined && item.count > 0 && (
                <span
                  style={{
                    fontSize: '0.725rem',
                    padding: '2px 6px',
                    borderRadius: '9999px',
                    backgroundColor: isActive ? 'var(--primary)' : 'rgba(255, 255, 255, 0.1)',
                    color: '#ffffff',
                  }}
                >
                  {item.count}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      {/* Sandbox security badge */}
      <div
        className="glass-panel"
        style={{
          padding: '12px',
          borderRadius: '8px',
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          backgroundColor: 'rgba(99, 102, 241, 0.05)',
          borderColor: 'rgba(99, 102, 241, 0.2)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--primary)' }}>
          <ShieldCheck size={16} />
          <span style={{ fontSize: '0.75rem', fontWeight: 600 }}>Docker Sandbox</span>
        </div>
        <p style={{ fontSize: '0.7rem', color: 'var(--text-dim)', lineHeight: 1.4 }}>
          All agent tools execute within isolated non-root containers with strict egress filters.
        </p>
      </div>
    </aside>
  );
};
