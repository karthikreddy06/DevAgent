import React, { useEffect, useState, useRef } from 'react';
import {
  ArrowLeft,
  Play,
  Square,
  CheckCircle,
  XCircle,
  Terminal,
  GitPullRequest,
  MessageSquare,
  Send,
  GitBranch,
  Repeat,
  Radio,
  FileCode,
} from 'lucide-react';
import { Change, ChatMessage, Task, TaskEvent } from '../types';
import { Badge } from '../components/Badge';
import { DiffViewer } from '../components/DiffViewer';
import { api } from '../api/client';

interface TaskDetailPageProps {
  taskId: string;
  onBack: () => void;
  onTaskUpdated?: () => void;
}

export const TaskDetailPage: React.FC<TaskDetailPageProps> = ({
  taskId,
  onBack,
  onTaskUpdated,
}) => {
  const [task, setTask] = useState<Task | null>(null);
  const [changes, setChanges] = useState<Change[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [activeTab, setActiveTab] = useState<'events' | 'diff' | 'chat'>('events');
  const [reviewReason, setReviewReason] = useState('');
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  const eventsEndRef = useRef<HTMLDivElement>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Load Task and Changes
  const loadData = async () => {
    try {
      const taskData = await api.getTask(taskId);
      setTask(taskData);

      const changesData = await api.listChanges(taskId);
      setChanges(changesData);
    } catch (err) {
      console.error('Error loading task details', err);
    }
  };

  useEffect(() => {
    loadData();
    // Connect SSE stream
    const unsubscribe = api.streamTaskEvents(
      taskId,
      (event) => {
        setEvents((prev) => [...prev, event]);
        // Update task state if event contains status change
        if (event.event_type === 'status_change' && event.data?.status) {
          setTask((prev) => (prev ? { ...prev, status: event.data.status as Task['status'] } : prev));
          if (onTaskUpdated) onTaskUpdated();
        }
      },
      (err) => {
        console.warn('SSE stream closed or error:', err);
      }
    );

    return () => {
      unsubscribe();
    };
  }, [taskId]);

  // Scroll to bottom of events
  useEffect(() => {
    if (activeTab === 'events') {
      eventsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
    if (activeTab === 'chat') {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [events, chatMessages, activeTab]);

  const handleRunTask = async () => {
    setActionLoading(true);
    setActionMessage(null);
    try {
      await api.runTask(taskId);
      setActionMessage('Agent execution started!');
      loadData();
      if (onTaskUpdated) onTaskUpdated();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionMessage(`Run error: ${err.message}`);
      } else {
        setActionMessage('Run error occurred');
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancelTask = async () => {
    setActionLoading(true);
    try {
      await api.cancelTask(taskId);
      setActionMessage('Task cancelled.');
      loadData();
      if (onTaskUpdated) onTaskUpdated();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionMessage(`Cancel error: ${err.message}`);
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleReviewChange = async (changeId: string, approved: boolean) => {
    setActionLoading(true);
    try {
      await api.reviewChange(changeId, approved, reviewReason);
      setReviewReason('');
      setActionMessage(approved ? 'Change approved!' : 'Change rejected.');
      loadData();
      if (onTaskUpdated) onTaskUpdated();
    } catch (err: unknown) {
      if (err instanceof Error) {
        setActionMessage(`Review error: ${err.message}`);
      }
    } finally {
      setActionLoading(false);
    }
  };

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!chatInput.trim()) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      session_id: taskId,
      role: 'user',
      content: chatInput,
      created_at: new Date().toISOString(),
    };
    setChatMessages((prev) => [...prev, userMsg]);
    setChatInput('');

    // Synthetic agent echo response for interactive demonstration
    setTimeout(() => {
      const agentMsg: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        session_id: taskId,
        role: 'assistant',
        content: `Acknowledged instruction: "${userMsg.content}". I have updated my working context and will verify code AST references before planning subsequent edits.`,
        created_at: new Date().toISOString(),
      };
      setChatMessages((prev) => [...prev, agentMsg]);
    }, 600);
  };

  if (!task) {
    return (
      <div style={{ textAlign: 'center', padding: '60px 0', color: 'var(--text-muted)' }}>
        Loading task details...
      </div>
    );
  }

  const latestChange = changes[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* Back button and Header */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <button
          onClick={onBack}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            background: 'none',
            border: 'none',
            color: 'var(--text-dim)',
            cursor: 'pointer',
            fontSize: '0.85rem',
            width: 'fit-content',
          }}
        >
          <ArrowLeft size={16} />
          <span>Back to Tasks</span>
        </button>

        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: '16px',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Badge type={task.type} />
              <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>{task.title}</h2>
              <Badge status={task.status} />
            </div>

            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '16px',
                fontSize: '0.8rem',
                color: 'var(--text-muted)',
              }}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <GitBranch size={14} />
                Base: <strong>{task.base_branch}</strong>
              </span>
              {task.fix_branch && (
                <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <GitPullRequest size={14} />
                  Fix: <strong>{task.fix_branch}</strong>
                </span>
              )}
              <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                <Repeat size={14} />
                Iteration: <strong>{task.iteration} / {task.max_iterations}</strong>
              </span>
            </div>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: '10px' }}>
            {task.status?.toLowerCase() !== 'completed' &&
              task.status?.toLowerCase() !== 'failed' &&
              task.status?.toLowerCase() !== 'rejected' && (
              <>
                <button
                  onClick={handleRunTask}
                  disabled={actionLoading}
                  className="btn-primary"
                >
                  <Play size={16} />
                  <span>Start Agent</span>
                </button>
                <button
                  onClick={handleCancelTask}
                  disabled={actionLoading}
                  className="btn-danger"
                >
                  <Square size={16} />
                  <span>Cancel</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>

      {actionMessage && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            backgroundColor: actionMessage.includes('error')
              ? 'rgba(239, 68, 68, 0.15)'
              : 'rgba(99, 102, 241, 0.15)',
            border: '1px solid var(--border-color)',
            color: 'var(--text-main)',
            fontSize: '0.85rem',
          }}
        >
          {actionMessage}
        </div>
      )}

      {/* Description Panel */}
      {task.description && (
        <div
          className="glass-panel"
          style={{
            padding: '16px 20px',
            fontSize: '0.875rem',
            color: 'var(--text-muted)',
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: 'var(--text-main)', display: 'block', marginBottom: '4px' }}>
            Task Objective:
          </strong>
          {task.description}
        </div>
      )}

      {/* Root Cause / Analysis Panel if available */}
      {task.root_cause?.analysis && (
        <div
          className="glass-panel"
          style={{
            padding: '16px 20px',
            fontSize: '0.875rem',
            borderLeft: '4px solid #6366f1',
            backgroundColor: 'rgba(99, 102, 241, 0.05)',
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: '#818cf8', display: 'block', marginBottom: '6px' }}>
            Root Cause Diagnosis:
          </strong>
          <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-main)', fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
            {task.root_cause.analysis}
          </div>
        </div>
      )}

      {/* Task Summary / Verification Outcome */}
      {task.summary && (
        <div
          className="glass-panel"
          style={{
            padding: '16px 20px',
            fontSize: '0.875rem',
            borderLeft: '4px solid #10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.05)',
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: '#34d399', display: 'block', marginBottom: '6px' }}>
            Verification Summary:
          </strong>
          <div style={{ color: 'var(--text-main)' }}>{task.summary}</div>
        </div>
      )}

      {/* Tabs Header */}
      <div
        style={{
          display: 'flex',
          gap: '8px',
          borderBottom: '1px solid var(--border-color)',
          paddingBottom: '2px',
        }}
      >
        <button
          onClick={() => setActiveTab('events')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'events' ? '2px solid var(--primary)' : '2px solid transparent',
            color: activeTab === 'events' ? '#ffffff' : 'var(--text-muted)',
            fontWeight: activeTab === 'events' ? 600 : 400,
            fontSize: '0.875rem',
            cursor: 'pointer',
          }}
        >
          <Terminal size={16} />
          <span>Execution Stream</span>
          <span
            style={{
              padding: '2px 6px',
              borderRadius: '9999px',
              backgroundColor: 'rgba(255, 255, 255, 0.1)',
              fontSize: '0.7rem',
            }}
          >
            {events.length}
          </span>
        </button>

        <button
          onClick={() => setActiveTab('diff')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'diff' ? '2px solid var(--primary)' : '2px solid transparent',
            color: activeTab === 'diff' ? '#ffffff' : 'var(--text-muted)',
            fontWeight: activeTab === 'diff' ? 600 : 400,
            fontSize: '0.875rem',
            cursor: 'pointer',
          }}
        >
          <FileCode size={16} />
          <span>Proposed Diff</span>
          {changes.length > 0 && (
            <span
              style={{
                padding: '2px 6px',
                borderRadius: '9999px',
                backgroundColor: 'rgba(99, 102, 241, 0.2)',
                color: 'var(--primary)',
                fontSize: '0.7rem',
              }}
            >
              {changes.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('chat')}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 16px',
            background: 'none',
            border: 'none',
            borderBottom: activeTab === 'chat' ? '2px solid var(--primary)' : '2px solid transparent',
            color: activeTab === 'chat' ? '#ffffff' : 'var(--text-muted)',
            fontWeight: activeTab === 'chat' ? 600 : 400,
            fontSize: '0.875rem',
            cursor: 'pointer',
          }}
        >
          <MessageSquare size={16} />
          <span>Agent Guidance Chat</span>
        </button>
      </div>

      {/* Tab 1: Real-time Execution Stream */}
      {activeTab === 'events' && (
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
            minHeight: '420px',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              borderBottom: '1px solid var(--border-color)',
              paddingBottom: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Radio size={16} color="#34d399" />
              <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Live Agent Event Stream</span>
            </div>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-dim)' }}>
              Connected via Server-Sent Events (SSE)
            </span>
          </div>

          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '10px',
              fontFamily: 'var(--font-mono)',
              fontSize: '0.8rem',
              maxHeight: '480px',
              overflowY: 'auto',
              paddingRight: '6px',
            }}
          >
            {events.length === 0 ? (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '40px 0' }}>
                Waiting for agent events... Click &quot;Start Agent&quot; to trigger workflow execution.
              </div>
            ) : (
              events.map((evt, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '6px',
                    backgroundColor: 'rgba(0, 0, 0, 0.3)',
                    borderLeft: '3px solid var(--primary)',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-dim)', fontSize: '0.7rem' }}>
                    <span style={{ color: 'var(--primary)', fontWeight: 600 }}>[{evt.event_type.toUpperCase()}]</span>
                    <span>{new Date(evt.timestamp).toLocaleTimeString()}</span>
                  </div>
                  <div style={{ color: '#e2e8f0', marginTop: '4px' }}>
                    {JSON.stringify(evt.data, null, 2)}
                  </div>
                </div>
              ))
            )}
            <div ref={eventsEndRef} />
          </div>
        </div>
      )}

      {/* Tab 2: Proposed Changes & Approval Gate */}
      {activeTab === 'diff' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Approval Action Gate if awaiting approval */}
          {(task.status?.toLowerCase() === 'awaiting_approval' ||
            task.status?.toLowerCase() === 'fix_proposed') &&
            latestChange && (
            <div
              className="glass-panel"
              style={{
                padding: '24px',
                border: '1px solid rgba(245, 158, 11, 0.4)',
                backgroundColor: 'rgba(245, 158, 11, 0.05)',
                display: 'flex',
                flexDirection: 'column',
                gap: '16px',
              }}
            >
              <div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: 600, color: '#fbbf24', marginBottom: '4px' }}>
                  Human-in-the-Loop Approval Required
                </h3>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
                  The agent has generated code modifications and verified tests. Please inspect the diff below before approving merge into the target branch.
                </p>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '6px' }}>
                  Review Reason / Feedback Notes (optional)
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Looks good, approved fix for token expiration check."
                  value={reviewReason}
                  onChange={(e) => setReviewReason(e.target.value)}
                />
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <button
                  onClick={() => handleReviewChange(latestChange.id, true)}
                  disabled={actionLoading}
                  className="btn-primary"
                  style={{ background: 'linear-gradient(135deg, #10b981 0%, #059669 100%)' }}
                >
                  <CheckCircle size={16} />
                  <span>Approve & Merge Fix</span>
                </button>
                <button
                  onClick={() => handleReviewChange(latestChange.id, false)}
                  disabled={actionLoading}
                  className="btn-danger"
                >
                  <XCircle size={16} />
                  <span>Reject & Request Changes</span>
                </button>
              </div>
            </div>
          )}

          {/* Unified Diff Viewer */}
          {latestChange ? (
            <DiffViewer
              patch={latestChange.patch_unified}
              filesChanged={latestChange.files_changed}
            />
          ) : (
            <div
              className="glass-panel"
              style={{
                padding: '60px 24px',
                textAlign: 'center',
                color: 'var(--text-dim)',
                fontSize: '0.875rem',
              }}
            >
              No patch generated yet. Once the agent produces edits, the unified diff will appear here.
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Interactive Chat Panel */}
      {activeTab === 'chat' && (
        <div
          className="glass-panel"
          style={{
            padding: '20px',
            display: 'flex',
            flexDirection: 'column',
            gap: '16px',
            height: '520px',
          }}
        >
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              paddingRight: '6px',
            }}
          >
            {chatMessages.length === 0 ? (
              <div style={{ color: 'var(--text-dim)', textAlign: 'center', padding: '80px 0', fontSize: '0.875rem' }}>
                Send a message to instruct or guide the agent regarding this task.
              </div>
            ) : (
              chatMessages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '75%',
                    gap: '4px',
                  }}
                >
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-dim)' }}>
                    {msg.role === 'user' ? 'You' : 'DevAgent'} • {new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <div
                    style={{
                      padding: '10px 14px',
                      borderRadius: '10px',
                      backgroundColor:
                        msg.role === 'user'
                          ? 'var(--primary)'
                          : 'rgba(30, 41, 59, 0.8)',
                      color: '#ffffff',
                      fontSize: '0.875rem',
                      lineHeight: '1.4',
                      border: msg.role === 'user' ? 'none' : '1px solid var(--border-color)',
                    }}
                  >
                    {msg.content}
                  </div>
                </div>
              ))
            )}
            <div ref={chatEndRef} />
          </div>

          <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '10px' }}>
            <input
              type="text"
              className="input-field"
              placeholder="Provide hints, constraints, or new requirements to the agent..."
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
            />
            <button type="submit" className="btn-primary" style={{ padding: '0 20px' }}>
              <Send size={16} />
            </button>
          </form>
        </div>
      )}
    </div>
  );
};
