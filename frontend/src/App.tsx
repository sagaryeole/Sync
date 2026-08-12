import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import TerminalPage from './pages/TerminalPage';
import StrategyDetailPage from './pages/StrategyDetailPage';
import OrdersPage from './pages/OrdersPage';
import SettingsPage from './pages/SettingsPage';

function App() {
  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/" element={<TerminalPage />} />
        <Route path="/strategies" element={<StrategyDetailPage />} />
        <Route path="/strategies/:key" element={<StrategyDetailPage />} />
        <Route path="/orders" element={<OrdersPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Routes>
    </Router>
  );
}

export default App;
