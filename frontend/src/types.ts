export interface Task {
  id: string;
  name: string;
  description: string;
  assignee: string;
  duration_days: number;
  predecessors: string[];
  color_hint: string | null;
}

export interface Scheduled {
  id: string;
  start: string; // ISO date
  end: string; // ISO date (exclusive end = start + duration)
  is_critical: boolean;
}

export interface Plan {
  tasks: Task[];
  project_start: string;
}

export interface PlanPatch {
  plan: Plan;
  changed_ids: string[];
}

export interface PlanAndSchedule {
  plan: Plan;
  schedule: Scheduled[];
}

export interface ToolCallEvent {
  type: 'tool_call';
  tool: string;
  args: Record<string, unknown>;
}

export interface PatchEvent {
  type: 'patch';
  plan_patch: PlanPatch;
}

export interface MessageEvent {
  type: 'message';
  text: string;
}

export interface ErrorEvent {
  type: 'error';
  detail: string;
}

export interface DoneEvent {
  type: 'done';
}

export type AgentEvent =
  | ToolCallEvent
  | PatchEvent
  | MessageEvent
  | ErrorEvent
  | DoneEvent;
