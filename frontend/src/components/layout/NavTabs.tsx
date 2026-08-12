interface Tab {
  label: string;
  href: string;
}

interface Props {
  tabs: Tab[];
  active: string;
}

export default function NavTabs({ tabs, active }: Props) {
  return (
    <nav style={{
      display: 'flex',
      gap: '0.25rem',
      padding: '0.5rem 1.5rem',
      background: '#0f172a',
      borderBottom: '1px solid #1e293b',
    }}>
      {tabs.map(tab => (
        <a
          key={tab.href}
          href={tab.href}
          style={{
            padding: '0.5rem 1rem',
            borderRadius: '4px',
            fontSize: '0.875rem',
            fontWeight: 500,
            color: active === tab.href ? '#f1f5f9' : '#94a3b8',
            background: active === tab.href ? '#1e293b' : 'transparent',
            textDecoration: 'none',
          }}
        >
          {tab.label}
        </a>
      ))}
    </nav>
  );
}
