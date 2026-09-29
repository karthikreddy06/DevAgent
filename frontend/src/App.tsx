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
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isNewRepoModalOpen, setIsNewRepoModalOpen] = useState(false);
  const [isNewTaskModalOpen, setIsNewTaskModalOpen] = useState(false);

  const refreshData = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const [repos, taskList] = await Promise.all([
        api.listRepositories().catch(() => []),
        api.listTasks().catch(() => []),
      ]);
      setRepositories(repos);
      setTasks(taskList);
    } catch (err) {
      console.error('Error fetching dashboard data', err);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    refreshData();
  }, [refreshData]);

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
            setSelectedTaskId(null);
            setActiveTab(tab);
          }}
          taskCount={tasks.length}
          repoCount={repositories.length}
        />

        <main style={{ flex: 1, padding: '32px', overflowY: 'auto' }}>
          {selectedTaskId ? (
            <TaskDetailPage
              taskId={selectedTaskId}
              onBack={() => setSelectedTaskId(null)}
              onTaskUpdated={refreshData}
            />
          ) : activeTab === 'dashboard' ? (
            <DashboardPage
              repositories={repositories}
              tasks={tasks}
              onSelectTask={(id) => setSelectedTaskId(id)}
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
              onSelectTask={(id) => setSelectedTaskId(id)}
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
          setSelectedTaskId(task.id);
        }}
      />
    </div>
  );
};

export const App: React.FC = () => {
  return <AppContent />;
};

export default App;
