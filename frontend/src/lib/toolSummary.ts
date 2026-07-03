/**
 * Shared tool-call summarizer — turns an agent tool name + its args into a
 * short Russian human summary, e.g. "shift_tasks · Олег +7д". Used both by
 * ChatPanel's live tool-call chips and by TaskModal's "История правок
 * агентом" per-task history list, so the two surfaces always agree on
 * wording instead of drifting apart (previously TaskModal rendered the bare
 * tool name — "» shift_tasks" — with no args, which read as an internal
 * debug string to a non-technical user).
 *
 * Falls back to the raw tool name for anything not explicitly handled, so a
 * future tool never renders a blank chip.
 */
export function summarizeToolCall(tool: string, args: Record<string, unknown>): string {
  switch (tool) {
    case 'shift_tasks':
      return `${tool} · ${String(args.assignee ?? '?')} +${String(args.days ?? '?')}д`;
    case 'reassign_tasks':
      return `${tool} · ${String(args.from_assignee ?? '?')} → ${String(args.to_assignee ?? '?')}`;
    case 'update_task':
      return `${tool} · ${String(args.id ?? '?')}`;
    case 'add_task':
      return `${tool} · ${String(args.name ?? '?')}`;
    case 'delete_task':
      return `${tool} · ${String(args.id ?? '?')}`;
    case 'set_dependencies':
      return `${tool} · ${String(args.id ?? '?')}`;
    default:
      return tool;
  }
}
