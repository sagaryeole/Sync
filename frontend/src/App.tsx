import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import Dashboard from './components/Dashboard.tsx';
import PriceTable from './components/PriceTable.tsx';
import Portfolio from './components/Portfolio.tsx';
import TradeForm from './components/TradeForm.tsx';

function App() {
  return (
    <Router future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <div style={{ display: 'flex', minHeight: '100vh', flexDirection: 'column' }}>
        <header style={{
          background: '#1e293b',
          padding: '1rem 2rem',
          borderBottom: '1px solid #334155',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <h1 style={{ margin: 0, color: '#38bdf8', fontWeight: 'bold' }}>
            CryptoTrade Bot
          </h1>
          <nav style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <Link to="/" style={{ color: '#cbd5e1', textDecoration: 'none' }}>
              Dashboard
            </Link>
            <Link to="/prices" style={{ color: '#cbd5e1', textDecoration: 'none' }}>
              Prices
            </Link>
            <Link to="/portfolio" style={{ color: '#cbd5e1', textDecoration: 'none' }}>
              Portfolio
            </Link>
            <Link to="/trade" style={{ color: '#cbd5e1', textDecoration: 'none' }}>
              Trade
            </Link>
          </nav>
        </header>
        <main style={{ flex: 1, padding: '2rem', maxWidth: '1200px', margin: '0 auto', width: '100%' }}>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/prices" element={<PriceTable />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/trade" element={<TradeForm />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
