import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { usePlanStore } from '../store/planStore';
import { streamChat } from '../api/client';
import { summarizeToolCall } from '../lib/toolSummary';
import type { AgentEvent } from '../types';
import './ChatPanel.css';

const EXAMPLE_COMMANDS = [
  'перенеси задачи Олега на неделю',
  'переназначь задачи Марии на Петра',
];

/** Best-effort extraction of task ids a tool call touched, so TaskModal can
 * later filter the chat log's history to a single task. Not exhaustive for
 * every tool shape — assignee-scoped tools (shift/reassign) can't name
 * specific ids up front, so those are matched at render time by assignee
 * instead (see TaskModal). */
function toolCallTaskIds(tool: string, args: Record<string, unknown>): string[] {
  if (tool === 'update_task' || tool === 'delete_task' || tool === 'set_dependencies') {
    const id = args.id;
    return typeof id === 'string' ? [id] : [];
  }
  return [];
}

export function ChatPanel() {
  const chatLog = usePlanStore((s) => s.chatLog);
  const pushChat = usePlanStore((s) => s.pushChat);
  const applyPatch = usePlanStore((s) => s.applyPatch);
  const undo = usePlanStore((s) => s.undo);

  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chatLog]);

  const send = async (message: string) => {
    const text = message.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    pushChat({ role: 'user', text });

    try {
      await streamChat(text, (event: AgentEvent) => {
        if (event.type === 'tool_call') {
          pushChat({
            role: 'tool_call',
            tool: event.tool,
            args: event.args,
            taskIds: toolCallTaskIds(event.tool, event.args),
          });
        } else if (event.type === 'patch') {
          applyPatch(event.plan_patch);
        } else if (event.type === 'message') {
          if (event.text) pushChat({ role: 'agent', text: event.text });
        } else if (event.type === 'error') {
          pushChat({ role: 'error', text: event.detail });
        }
      });
    } catch (err) {
      pushChat({ role: 'error', text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(input);
  };

  return (
    <div className="chat-panel">
      <div className="chat-panel__header">
        <span className="chat-panel__title">AI-АГЕНТ</span>
        <button
          type="button"
          className="chat-panel__undo"
          data-testid="undo-btn"
          onClick={() => void undo()}
        >
          ↩ Откатить
        </button>
      </div>

      <div className="chat-panel__log" ref={logRef}>
        {chatLog.length === 0 && (
          <div className="chat-panel__empty">
            <p>Опишите изменение плана обычным языком.</p>
            <div className="chat-panel__hints">
              {EXAMPLE_COMMANDS.map((cmd) => (
                <button
                  key={cmd}
                  type="button"
                  className="chat-panel__hint"
                  onClick={() => setInput(cmd)}
                >
                  {cmd}
                </button>
              ))}
            </div>
          </div>
        )}

        {chatLog.map((msg, i) => {
          if (msg.role === 'tool_call') {
            return (
              <div key={i} className="chat-panel__chip" data-testid="tool-chip">
                <span className="chat-panel__chip-glyph" aria-hidden="true">
                  »
                </span>
                {summarizeToolCall(msg.tool, msg.args)}
              </div>
            );
          }
          return (
            <div
              key={i}
              className="chat-panel__message"
              data-testid="chat-message"
              data-role={msg.role}
            >
              {msg.text}
            </div>
          );
        })}

        {busy && (
          <div className="chat-panel__typing" data-testid="chat-typing">
            <span />
            <span />
            <span />
          </div>
        )}
      </div>

      <form className="chat-panel__form" onSubmit={handleSubmit}>
        <input
          type="text"
          className="chat-panel__input"
          data-testid="chat-input"
          placeholder="Что изменить в плане?"
          value={input}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          type="submit"
          className="chat-panel__send"
          data-testid="chat-send"
          disabled={busy || !input.trim()}
        >
          Отправить
        </button>
      </form>
    </div>
  );
}
