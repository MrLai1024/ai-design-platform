import './public-path';
import React from 'react';
import ReactDOM from 'react-dom/client';
import { Provider } from 'react-redux';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { store } from './store';
import './styles/global.css';

let root: ReactDOM.Root | null = null;

function render(props: Record<string, unknown> = {}): void {
  const container = (props.container as HTMLElement) || document.getElementById('app');
  if (!container) return;

  const isQiankun = !!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__;

  root = ReactDOM.createRoot(container.querySelector('#app') || container);
  root.render(
    <React.StrictMode>
      <Provider store={store}>
        <BrowserRouter basename={isQiankun ? '/ai-workflow' : '/'}>
          <App />
        </BrowserRouter>
      </Provider>
    </React.StrictMode>,
  );
}

function destroy(): void {
  root?.unmount();
  root = null;
}

if (!(window as unknown as Record<string, unknown>).__POWERED_BY_QIANKUN__) {
  render();
}

export async function bootstrap(): Promise<void> {
  console.log('[ai-workflow] bootstrap');
}

export async function mount(props: Record<string, unknown>): Promise<void> {
  console.log('[ai-workflow] mount', props);
  render(props);
}

export async function unmount(_props: Record<string, unknown>): Promise<void> {
  console.log('[ai-workflow] unmount');
  destroy();
}
