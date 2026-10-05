import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from './stores/auth';
import { Navbar } from './components/Navbar';
import { Sidebar, ActiveTab } from './components/Sidebar';
import { LoginPage } from './pages/LoginPage';
import { RegisterPage } from './pages/RegisterPage';
import { DashboardPage } from './pages/DashboardPage';
import { RepositoriesPage } from './pages/RepositoriesPage';
import { TasksPage } from './pages/TasksPage';
import { TaskDetailPage } from './pages/TaskDetailPage';
import { DocsPage } from './pages/DocsPage';
import { NewRepoModal } from './components/NewRepoModal';
import { NewTaskModal } from './components/NewTaskModal';
import { Repository, Task } from './types';
import { api } from './api/client';

export const AppContent: React.FC = () => {
  const { isAuthenticated, isLoading } = useAuth();
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [activeTab, setActiveTab] = useState<ActiveTab>('dashboard');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null;
    const match = window.location.pathname.match(/^\/tasks\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  });

  const handleSelectTaskId = useCallback((id: string | null) => {
    setSelectedTaskId(id);
    if (typeof window !== 'undefined') {
      if (id) {
        window.history.pushState({}, '', `/tasks/${id}`);
      } else {
        window.history.pushState({}, '', '/');
      }
    }
  }, []);

  useEffect(() => {
    const handlePopState = () => {
      const match = window.location.pathname.match(/^\/tasks\/([a-zA-Z0-9_-]+)/);
      setSelectedTaskId(match ? match[1] : null);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isNewRepoModalOpen, setIsNewRepoModalOpen] = useState(false);
  const [isNewTaskModalOpen, setIsNewTaskModalOpen] = useState(false);

  const refreshData = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      setLoadError(null);
      const [repos, taskList] = await Promise.all([
        api.listRepositories(),
        api.listTasks(),
      ]);
      setRepositories(repos);
      setTasks(taskList);
    } catch (err: unknown) {
      console.error('Error fetching dashboard data', err);
      if (err instanceof Error) {
        setLoadError(`Failed to load data from server: ${err.message}`);
      } else {
        setLoadError('An unexpected network error occurred while loading data.');
      }
    }
  }, [isAuthenticated]);


  useEffect(() => {
    refreshData();
  }, [refreshData]);

  // Active task polling: Keep task list continuously refreshed if any task is executing
  const hasActiveTasks = tasks.some((t) => {
    const s = (t.status || '').toLowerCase();
    return ['created', 'planning', 'analyzing', 'investigating', 'applying', 'testing'].includes(s);
  });

  useEffect(() => {
    if (!isAuthenticated || !hasActiveTasks) return;
    const interval = setInterval(() => {
      refreshData();
    }, 3000);
    return () => clearInterval(interval);
  }, [isAuthenticated, hasActiveTasks, refreshData]);

  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: 'var(--bg-primary)',
          color: 'var(--text-main)',
        }}
      >
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
          <div
            style={{
              width: '40px',
              height: '40px',
              border: '3px solid rgba(99, 102, 241, 0.2)',
              borderTopColor: 'var(--primary)',
              borderRadius: '50%',
              animation: 'spin 0.8s linear infinite',
            }}
          />
          <span style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
            Initializing DevAgent...
          </span>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return authMode === 'login' ? (
      <LoginPage onSwitchToRegister={() => setAuthMode('register')} />
    ) : (
      <RegisterPage onSwitchToLogin={() => setAuthMode('login')} />
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Navbar />

      <div style={{ display: 'flex', flex: 1 }}>
        <Sidebar
          activeTab={activeTab}
          setActiveTab={(tab) => {
            handleSelectTaskId(null);
            setActiveTab(tab);
            refreshData();
          }}
          taskCount={tasks.length}
          repoCount={repositories.length}
        />

        <main style={{ flex: 1, padding: '32px', overflowY: 'auto' }}>
          {loadError && (
            <div
              style={{
                marginBottom: '20px',
                padding: '12px 16px',
                borderRadius: '8px',
                backgroundColor: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#f87171',
                fontSize: '0.875rem',
              }}
            >
              {loadError}
            </div>
          )}
          {selectedTaskId ? (
            <TaskDetailPage
              taskId={selectedTaskId}
              onBack={() => {
                handleSelectTaskId(null);
                refreshData();
              }}
              onTaskUpdated={refreshData}
            />
          ) : activeTab === 'dashboard' ? (

            <DashboardPage
              repositories={repositories}
              tasks={tasks}
              onSelectTask={(id) => handleSelectTaskId(id)}
              onOpenNewTaskModal={() => setIsNewTaskModalOpen(true)}
              onOpenNewRepoModal={() => setIsNewRepoModalOpen(true)}
            />
          ) : activeTab === 'repositories' ? (
            <RepositoriesPage
              repositories={repositories}
              onRefresh={refreshData}
              onOpenNewRepoModal={() => setIsNewRepoModalOpen(true)}
            />
          ) : activeTab === 'tasks' ? (
            <TasksPage
              tasks={tasks}
              repositories={repositories}
              onRefresh={refreshData}
              onSelectTask={(id) => handleSelectTaskId(id)}
              onOpenNewTaskModal={() => setIsNewTaskModalOpen(true)}
            />
          ) : (
            <DocsPage />
          )}
        </main>
      </div>

      {/* Global Modals */}
      <NewRepoModal
        isOpen={isNewRepoModalOpen}
        onClose={() => setIsNewRepoModalOpen(false)}
        onRepoCreated={(repo) => {
          setRepositories((prev) => [repo, ...prev]);
        }}
      />

      <NewTaskModal
        isOpen={isNewTaskModalOpen}
        repositories={repositories}
        onClose={() => setIsNewTaskModalOpen(false)}
        onTaskCreated={(task) => {
          setTasks((prev) => [task, ...prev]);
          handleSelectTaskId(task.id);
        }}
      />
    </div>
  );
};

export const App: React.FC = () => {
  return <AppContent />;
};

export default App;
