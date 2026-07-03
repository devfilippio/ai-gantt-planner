import { useEffect } from 'react';
import { usePlanStore } from './store/planStore';
import { GanttChart } from './components/GanttChart';
import './App.css';

function App() {
  const loadPlan = usePlanStore((state) => state.loadPlan);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  return (
    <main className="app-shell">
      <div className="app-shell__chart">
        <GanttChart onSelectTask={() => {}} />
      </div>
      <aside className="app-shell__chat" aria-label="AI-агент">
        <span className="app-shell__chat-label">AI-АГЕНТ</span>
      </aside>
    </main>
  );
}

export default App;
