import { BrowserRouter } from 'react-router-dom';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { AdminRoutes } from './routes';

export function App() {
  return <ErrorBoundary><BrowserRouter><AdminRoutes /></BrowserRouter></ErrorBoundary>;
}
