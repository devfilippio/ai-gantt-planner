import { useEffect, useState } from 'react';
import { usePlanStore } from './store/planStore';
import { GanttChart } from './components/GanttChart';
import { ChatPanel } from './components/ChatPanel';
import { TaskModal } from './components/TaskModal';
import { Toolbar } from './components/Toolbar';
import { CommandsGuide } from './components/CommandsGuide';
import './App.css';

function App() {
  const loadPlan = usePlanStore((state) => state.loadPlan);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  return (
    <main className="app-shell">
      <div className="app-shell__chart">
        <Toolbar />
        <GanttChart onSelectTask={setSelectedTaskId} />
        <CommandsGuide />
      </div>
      <aside className="app-shell__chat" aria-label="AI-агент">
        <ChatPanel />
      </aside>

      {selectedTaskId && (
        <TaskModal
          taskId={selectedTaskId}
          onClose={() => setSelectedTaskId(null)}
          onSelectTask={setSelectedTaskId}
        />
      )}
    </main>
  );
}

export default App;
