import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import TerminalPage from './pages/TerminalPage';
import StrategyDetailPage from './pages/StrategyDetailPage';
import OrdersPage from './pages/OrdersPage';
import JournalPage from './pages/JournalPage';
import SettingsPage from './pages/SettingsPage';
import { ErrorBoundary } from './components/common/ErrorBoundary';

function App() {
  return (
    // Last-resort boundary. Individual panels catch their own errors (see
    // components/common/Panel), so this only trips on a routing/shell-level
    // failure — but without it such a failure renders a blank white page
    // with no indication anything went wrong.
    <ErrorBoundary>
      <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes>
          <Route path="/" element={<TerminalPage />} />
          <Route path="/strategies" element={<StrategyDetailPage />} />
          <Route path="/strategies/:key" element={<StrategyDetailPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          {/* Built in Phase 6 but never routed — unreachable until now. */}
          <Route path="/journal" element={<JournalPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </Router>
    </ErrorBoundary>
  );
}

export default App;
