import React from 'react';
import { TaskStatus, TaskType } from '../types';

interface BadgeProps {
  status?: TaskStatus | string;
  type?: TaskType | string;
  children?: React.ReactNode;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({ status, type, children, className = '' }) => {
  const getStatusClass = (s?: string) => {
    switch (s?.toLowerCase()) {
      case 'completed':
      case 'passed':
      case 'approved':
      case 'merged':
        return 'badge-success';
      case 'awaiting_approval':
      case 'planning':
      case 'analyzing':
      case 'investigating':
      case 'fix_proposed':
      case 'applying':
      case 'modifying':
      case 'testing':
      case 'repairing':
        return 'badge-warning';
      case 'failed':
      case 'rejected':
      case 'cancelled':
        return 'badge-danger';
      case 'queued':
      case 'created':
        return 'badge-primary';
      default:
        return 'badge-secondary';
    }
  };

  const getTypeClass = (t?: string) => {
    switch (t?.toLowerCase()) {
      case 'bug':
      case 'bug_fix':
        return 'badge-danger';
      case 'security':
        return 'badge-warning';
      case 'feature':
        return 'badge-primary';
      case 'refactor':
      case 'test':
        return 'badge-primary';
      case 'docs':
      case 'documentation':
      case 'question':
      default:
        return 'badge-secondary';
    }
  };


  const badgeClass = status ? getStatusClass(status) : getTypeClass(type);
  const label = children || status || type;

  return (
    <span className={`badge ${badgeClass} ${className}`}>
      {label}
    </span>
  );
};
