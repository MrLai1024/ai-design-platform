import React from 'react';
import { Routes, Route, NavLink } from 'react-router-dom';
import { routes } from './router';
import { onGlobalStateChange } from '@ai-design/micro-core';

const App: React.FC = () => {
  React.useEffect(() => {
    onGlobalStateChange((state, prev) => {
      console.log('[ai-workflow] global state changed:', state, prev);
    });
  }, []);

  return (
    <div className="ai-workflow p-6">
      <h1 className="text-2xl font-bold text-gray-800 mb-4">AI 工作流</h1>
      <nav className="flex space-x-4 mb-6">
        <NavLink
          to="/"
          className={({ isActive }) =>
            `text-blue-600 hover:underline ${isActive ? 'font-bold' : ''}`
          }
        >
          首页
        </NavLink>
        <NavLink
          to="/about"
          className={({ isActive }) =>
            `text-blue-600 hover:underline ${isActive ? 'font-bold' : ''}`
          }
        >
          关于
        </NavLink>
      </nav>
      <Routes>
        {routes.map((route) => (
          <Route key={route.path} path={route.path} element={route.element} />
        ))}
      </Routes>
    </div>
  );
};

export default App;
