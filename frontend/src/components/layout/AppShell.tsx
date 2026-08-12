import { ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

export default function AppShell({ children }: Props) {
  return (
    <div style={{
      minHeight: '100vh',
      background: '#0f172a',
      color: '#f1f5f9',
      fontFamily: 'Inter, system-ui, sans-serif',
    }}>
      {children}
    </div>
  );
}
