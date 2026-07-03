import { useEffect } from 'react';
import { usePlanStore } from './store/planStore';

function App() {
  const plan = usePlanStore((state) => state.plan);
  const loadPlan = usePlanStore((state) => state.loadPlan);

  useEffect(() => {
    void loadPlan();
  }, [loadPlan]);

  const tasks = plan?.tasks ?? [];

  return (
    <main style={{ padding: 24 }}>
      <h1 style={{ fontFamily: 'var(--font-mono)', fontSize: 14, letterSpacing: '0.08em', color: 'var(--text-dim)' }}>
        ПЛАН ПРОЕКТА
      </h1>
      <div id="gantt-placeholder">
        {tasks.map((task) => (
          <div key={task.id} data-testid="task-bar" data-task-id={task.id}>
            {task.name}
          </div>
        ))}
      </div>
    </main>
  );
}

export default App;
