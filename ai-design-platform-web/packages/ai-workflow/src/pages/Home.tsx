import React from 'react';
import { useSelector } from 'react-redux';
import type { RootState } from '../store';

const Home: React.FC = () => {
  const loading = useSelector((state: RootState) => state.workflow.loading);

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <p className="text-gray-600">欢迎使用 AI 工作流功能</p>
      {loading && <p className="text-blue-500 mt-2">加载中...</p>}
    </div>
  );
};

export default Home;
