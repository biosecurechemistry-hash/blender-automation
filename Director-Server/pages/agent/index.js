import Head from 'next/head';

// ZeroClaw Agent Dashboard — exposed at /agent.
export default function ZeroClawDashboard() {
  return (
    <>
      <Head>
        <title>ZeroClaw — Agent Dashboard</title>
      </Head>
      <main style={styles.main}>
        <h1 style={styles.h1}>ZeroClaw Agent</h1>
        <p style={styles.sub}>Autonomous Director Orchestrator · Port 42617</p>

        <div style={styles.grid}>
          <div style={styles.card}>
            <h2>Active Agents</h2>
            <ul style={styles.list}>
              <li><strong>Inquisitor</strong> — NOMINAL</li>
              <li><strong>Scout</strong> — NOMINAL</li>
            </ul>
          </div>
          <div style={styles.card}>
            <h2>Pipeline Status</h2>
            <ul style={styles.list}>
              <li>Blender Bridge: <span style={{color:'#2ecc71'}}>ONLINE :5000</span></li>
              <li>Ledger DB: <span style={{color:'#2ecc71'}}>ONLINE :5433</span></li>
              <li>Shopify: <span style={{color:'#f1c40f'}}>BUFFERED</span></li>
            </ul>
          </div>
          <div style={styles.card}>
            <h2>Command Queue</h2>
            <p style={{color:'#8b949e'}}>POST /api/render to enqueue</p>
            <p style={{color:'#8b949e'}}>POST / to trigger full pipeline</p>
          </div>
        </div>
      </main>
    </>
  );
}

const styles = {
  main: {
    maxWidth: 960, margin: '0 auto', padding: '2rem 1rem',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    background: '#0d1117', color: '#c9d1d9', minHeight: '100vh',
  },
  h1: { fontSize: '2rem', margin: 0, color: '#f0883e' },
  sub: { color: '#8b949e', marginTop: '0.25rem', marginBottom: '2rem' },
  grid: { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' },
  card: { background: '#161b22', border: '1px solid #30363d', borderRadius: 8, padding: '1.25rem' },
  list: { listStyle: 'none', padding: 0, lineHeight: 1.8 },
};
