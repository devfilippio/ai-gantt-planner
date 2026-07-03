import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
import { usePlanStore } from '../store/planStore';
import { exportExcel, importExcel } from '../api/client';
import './Toolbar.css';

const TOAST_DURATION_MS = 5000;

export function Toolbar() {
  const applyPatch = usePlanStore((s) => s.applyPatch);
  const resetPlanStore = usePlanStore((s) => s.resetPlan);

  const [toast, setToast] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const showToast = (message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  };

  const handleImportFile = async (file: File) => {
    setBusy(true);
    try {
      const { plan, schedule } = await importExcel(file);
      // A fresh import replaces the whole plan; there's no "changed" subset
      // to highlight (everything is new), so applyPatch is fed an empty
      // changed_ids — the bars simply reflect the new plan without a glow.
      applyPatch({ plan, changed_ids: [], schedule });
      showToast(`Импортировано задач: ${plan.tasks.length}`);
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleImportFile(file);
  };

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleImportFile(file);
  };

  const handleExport = async () => {
    setBusy(true);
    try {
      const blob = await exportExcel();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'plan.xlsx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showToast((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const handleReset = async () => {
    setBusy(true);
    try {
      await resetPlanStore();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="toolbar"
      data-drag-over={dragOver}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <span className="toolbar__label">§ 00 · ПРОЕКТ</span>

      <div className="toolbar__actions">
        <label className="toolbar__button" data-busy={busy}>
          Импорт Excel
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx"
            data-testid="toolbar-import"
            onChange={handleFileInputChange}
            disabled={busy}
          />
        </label>

        <button
          type="button"
          className="toolbar__button"
          data-testid="toolbar-export"
          onClick={() => void handleExport()}
          disabled={busy}
        >
          Экспорт
        </button>

        <button
          type="button"
          className="toolbar__button toolbar__button--ghost"
          data-testid="toolbar-reset"
          onClick={() => void handleReset()}
          disabled={busy}
        >
          Сброс
        </button>
      </div>

      {dragOver && (
        <div className="toolbar__drop-hint" aria-hidden="true">
          Отпустите файл .xlsx для импорта
        </div>
      )}

      {toast && (
        <div className="toolbar__toast" data-testid="toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
