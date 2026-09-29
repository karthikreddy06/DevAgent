import React, { useEffect, useState } from 'react';
import { Bot, LogOut, Activity, User as UserIcon } from 'lucide-react';
import { useAuth } from '../stores/auth';
import { api } from '../api/client';

export const Navbar: React.FC = () => {
  const { user, logout } = useAuth();
  const [healthStatus, setHealthStatus] = useState<'healthy' | 'unhealthy' | 'checking'>('checking');

  useEffect(() => {
    api
      .getHealth()
      .then(() => setHealthStatus('healthy'))
      .catch(() => setHealthStatus('unhealthy'));
  }, []);

  return (
    <header
      style={{
        height: '64px',
        borderBottom: '1px solid var(--border-color)',
        backgroundColor: 'rgba(15, 23, 42, 0.85)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
        <div
          style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, var(--primary) 0%, var(--accent-purple) 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: '0 0 16px var(--primary-glow)',
          }}
        >
          <Bot size={20} color="#ffffff" />
        </div>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span
            style={{
              fontSize: '1.2rem',
              fontWeight: 700,
              background: 'linear-gradient(90deg, #f8fafc, #818cf8)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
              letterSpacing: '-0.02em',
            }}
          >
            DevAgent
          </span>
          <span style={{ fontSize: '0.675rem', color: 'var(--text-dim)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Autonomous SWE Platform
          </span>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        {/* Backend health status badge */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '0.75rem',
            padding: '4px 10px',
            borderRadius: '9999px',
            backgroundColor:
              healthStatus === 'healthy'
                ? 'rgba(16, 185, 129, 0.1)'
                : 'rgba(239, 68, 68, 0.1)',
            border: `1px solid ${
              healthStatus === 'healthy'
                ? 'rgba(16, 185, 129, 0.3)'
                : 'rgba(239, 68, 68, 0.3)'
            }`,
            color: healthStatus === 'healthy' ? '#34d399' : '#f87171',
          }}
        >
          <Activity size={12} />
          <span>{healthStatus === 'healthy' ? 'API Online' : 'Connecting...'}</span>
        </div>

        {user && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  backgroundColor: 'rgba(255, 255, 255, 0.1)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  color: 'var(--text-main)',
                }}
              >
                <UserIcon size={16} />
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{ fontSize: '0.825rem', fontWeight: 600 }}>{user.username}</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{user.role}</span>
              </div>
            </div>

            <button
              onClick={logout}
              className="btn-secondary"
              style={{ padding: '6px 12px', fontSize: '0.8rem' }}
              title="Sign Out"
            >
              <LogOut size={14} />
              <span>Sign Out</span>
            </button>
          </div>
        )}
      </div>
    </header>
  );
};
