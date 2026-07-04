import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { usePlanStore } from '../store/planStore';
import { streamChat } from '../api/client';
import type { ChatHistoryTurn } from '../api/client';
import { summarizeToolCall } from '../lib/toolSummary';
import type { AgentEvent } from '../types';
import type { ChatMessage } from '../store/planStore';
import './ChatPanel.css';

const HISTORY_CAP = 20;

/** Builds the {role, text} history the backend needs for conversation memory
 * from the chat log kept in the store. Only user/agent turns carry
 * conversational content the model should remember — tool-call chips and
 * error messages are UI-only and excluded. Capped to the most recent
 * HISTORY_CAP entries (mirrors api/agent.py's own cap). */
function historyFromChatLog(chatLog: ChatMessage[]): ChatHistoryTurn[] {
  const turns: ChatHistoryTurn[] = [];
  for (const msg of chatLog) {
    if (msg.role === 'user') {
      turns.push({ role: 'user', text: msg.text });
    } else if (msg.role === 'agent') {
      turns.push({ role: 'agent', text: msg.text });
    }
  }
  return turns.slice(-HISTORY_CAP);
}

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
  const syncPlan = usePlanStore((s) => s.syncPlan);
  const undo = usePlanStore((s) => s.undo);
  const draftCommand = usePlanStore((s) => s.draftCommand);
  const setDraftCommand = usePlanStore((s) => s.setDraftCommand);

  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chatLog]);

  // CommandsGuide sets draftCommand when a card is clicked. Pick it up here:
  // drop the text into the input, focus it so the user can hit Enter right
  // away, then clear the draft so re-clicking the same card still fires.
  useEffect(() => {
    if (draftCommand === null) return;
    setInput(draftCommand);
    inputRef.current?.focus();
    setDraftCommand(null);
  }, [draftCommand, setDraftCommand]);

  const send = async (message: string) => {
    const text = message.trim();
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    // Snapshot history BEFORE pushing the new user message — the backend
    // appends `message` itself as the final user turn, so history must only
    // contain turns strictly prior to it (otherwise the latest message would
    // be duplicated in the LLM's message list).
    const history = historyFromChatLog(chatLog);
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
      }, history);
      // The stream has ended. Reconcile the chart with the server's
      // authoritative plan so a dropped mid-stream patch can never leave the
      // Gantt out of sync (owner hit: an added task confirmed in chat but not
      // showing on the chart). The live patches already ran the animation;
      // this just guarantees the final state is correct.
      await syncPlan();
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
              {msg.role === 'agent' ? msg.text.replace(/\*\*?/g, '') : msg.text}
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
          ref={inputRef}
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
