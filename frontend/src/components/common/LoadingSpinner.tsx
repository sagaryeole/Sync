export default function LoadingSpinner({ size = 24 }: { size?: number }) {
  return (
    <div
      style={{
        width: size,
        height: size,
        border: `2px solid #334155`,
        borderTopColor: '#38bdf8',
        borderRadius: '50%',
        animation: 'spin 1s linear infinite',
      }}
    />
  );
}
