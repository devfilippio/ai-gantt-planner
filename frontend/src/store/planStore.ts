import { create } from 'zustand';
import { getPlan, resetPlan, undoPlan, updateTask, type TaskUpdate } from '../api/client';
import type { Plan, PlanPatch, Scheduled } from '../types';

const HIGHLIGHT_DURATION_MS = 1200;

export type ChatMessage =
  | { role: 'user'; text: string }
  | { role: 'agent'; text: string }
  | { role: 'error'; text: string }
  | { role: 'tool_call'; tool: string; args: Record<string, unknown>; taskIds: string[] };

interface PlanState {
  plan: Plan | null;
  schedule: Scheduled[];
  changedIds: string[];
  chatLog: ChatMessage[];
  loading: boolean;
  error: string | null;

  loadPlan: () => Promise<void>;
  resetPlan: () => Promise<void>;
  applyPatch: (patch: PlanPatch) => void;
  pushChat: (message: ChatMessage) => void;
  clearToolChips: () => void;
  undo: () => Promise<void>;
  resizeTask: (id: string, patch: TaskUpdate) => Promise<void>;
}

let highlightTimer: ReturnType<typeof setTimeout> | undefined;

export const usePlanStore = create<PlanState>((set, get) => ({
  plan: null,
  schedule: [],
  changedIds: [],
  chatLog: [],
  loading: false,
  error: null,

  loadPlan: async () => {
    set({ loading: true, error: null });
    try {
      const { plan, schedule } = await getPlan();
      set({ plan, schedule, loading: false });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  resetPlan: async () => {
    set({ loading: true, error: null });
    try {
      const { plan, schedule } = await resetPlan();
      set({ plan, schedule, loading: false, changedIds: [] });
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  applyPatch: (patch: PlanPatch) => {
    set((state) => ({
      plan: patch.plan,
      // The backend now enriches the SSE `patch` event with a freshly
      // computed schedule (see api/index.py chat_route). Without setting it
      // here too, the Gantt bars would keep their stale start/end dates and
      // never reposition after an agent edit — plan alone isn't enough
      // because dates are always derived, never stored on Task itself.
      schedule: patch.schedule ?? state.schedule,
      changedIds: patch.changed_ids,
    }));

    if (highlightTimer) clearTimeout(highlightTimer);
    highlightTimer = setTimeout(() => {
      set({ changedIds: [] });
    }, HIGHLIGHT_DURATION_MS);
  },

  pushChat: (message: ChatMessage) => {
    set((state) => ({ chatLog: [...state.chatLog, message] }));
  },

  clearToolChips: () => {
    set((state) => ({ chatLog: state.chatLog.filter((m) => m.role !== 'tool_call') }));
  },

  undo: async () => {
    set({ loading: true, error: null });
    try {
      const { plan, schedule } = await undoPlan();
      // Undo reverts the plan to its pre-agent-edit snapshot, so any tool
      // chips referencing the edit that's being undone are stale — drop
      // them from the chat log along with the highlight state.
      set({ plan, schedule, loading: false, changedIds: [] });
      get().clearToolChips();
    } catch (err) {
      set({ error: (err as Error).message, loading: false });
    }
  },

  resizeTask: async (id: string, patch: TaskUpdate) => {
    const previous = { plan: get().plan, schedule: get().schedule };
    try {
      const { plan, schedule } = await updateTask(id, patch);
      set({ plan, schedule, changedIds: [id] });
      if (highlightTimer) clearTimeout(highlightTimer);
      highlightTimer = setTimeout(() => {
        set({ changedIds: [] });
      }, HIGHLIGHT_DURATION_MS);
    } catch (err) {
      // Revert optimistic UI on failure — the dragged bar snaps back.
      set({ ...previous, error: (err as Error).message });
    }
  },
}));
