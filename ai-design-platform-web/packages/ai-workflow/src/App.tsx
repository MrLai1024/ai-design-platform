import React from 'react';
import { Routes, Route } from 'react-router-dom';
import { routes } from './router';
import { onGlobalStateChange } from '@ai-design/micro-core';

const App: React.FC = () => {
  React.useEffect(() => {
    onGlobalStateChange((state, prev) => {
      console.log('[ai-workflow] global state changed:', state, prev);
    });
  }, []);

  return (
    <div className="ai-workflow h-full">
      <Routes>
        {routes.map(route => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Routes>
    </div>
  );
};

export default App;
