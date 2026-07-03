import type { AgentEvent, PlanAndSchedule } from '../types';

const API_BASE: string = import.meta.env.VITE_API_BASE ?? '';

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => '');
    throw new Error(`Request failed: ${res.status} ${detail}`);
  }
  return res.json() as Promise<T>;
}

export async function getPlan(): Promise<PlanAndSchedule> {
  const res = await fetch(`${API_BASE}/api/plan`);
  return handleJson<PlanAndSchedule>(res);
}

export async function resetPlan(): Promise<PlanAndSchedule> {
  const res = await fetch(`${API_BASE}/api/reset`, { method: 'POST' });
  return handleJson<PlanAndSchedule>(res);
}

export async function importExcel(file: File): Promise<PlanAndSchedule> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/api/plan/import`, {
    method: 'POST',
    body: formData,
  });
  return handleJson<PlanAndSchedule>(res);
}

export async function exportExcel(): Promise<Blob> {
  const res = await fetch(`${API_BASE}/api/plan/export`);
  if (!res.ok) {
    throw new Error(`Request failed: ${res.status}`);
  }
  return res.blob();
}

export async function undoPlan(): Promise<PlanAndSchedule> {
  const res = await fetch(`${API_BASE}/api/undo`, { method: 'POST' });
  return handleJson<PlanAndSchedule>(res);
}

export async function streamChat(
  message: string,
  onEvent: (event: AgentEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Chat request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split('\n');
    // Keep the last (possibly incomplete) line in the buffer.
    buffer = lines.pop() ?? '';

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith('data:')) continue;
      const payload = trimmed.slice('data:'.length).trim();
      if (!payload) continue;
      try {
        const event = JSON.parse(payload) as AgentEvent;
        onEvent(event);
      } catch {
        // Ignore malformed SSE chunks.
      }
    }
  }

  // Flush any trailing data line without a terminating newline.
  const trimmed = buffer.trim();
  if (trimmed.startsWith('data:')) {
    const payload = trimmed.slice('data:'.length).trim();
    if (payload) {
      try {
        const event = JSON.parse(payload) as AgentEvent;
        onEvent(event);
      } catch {
        // Ignore malformed SSE chunks.
      }
    }
  }
}
