import Home from '../pages/Home';
import About from '../pages/About';

export interface RouteConfig {
  path: string;
  element: React.ReactElement;
  label: string;
}

export const routes: RouteConfig[] = [
  { path: '/', element: <Home />, label: 'Home' },
  { path: '/about', element: <About />, label: 'About' },
];
