import { useState, useEffect } from 'react';
import Head from 'next/head';

// Resolved at build time via next.config.js env block.
const BLENDER_API = process.env.NEXT_PUBLIC_BLENDER_API || 'http://127.0.0.1:5000';
const ZEROCLAW_URL = process.env.NEXT_PUBLIC_ZEROCLAW_URL || 'http://127.0.0.1:42617/agent';

export default function DirectorDashboard() {
  const [ledger, setLedger] = useState(null);
  const [blenderStatus, setBlenderStatus] = useState(null);
  const [error, setError] = useState(null);

  // Fetch ledger summary on mount via our API route.
  useEffect(() => {
    fetch('/api/ledger-summary')
      .then((r) => r.json())
      .then(setLedger)
      .catch((e) => setError(e.message));

    // Ping the Blender bridge.
    fetch(`${BLENDER_API}/api/render`, { method: 'HEAD' })
      .then(() => setBlenderStatus('online'))
      .catch(() => setBlenderStatus('offline'));
  }, []);

  return (
    <>
      <Head>
        <title>Director-Server — Island Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <main style={styles.main}>
        <h1 style={styles.h1}>Director-Server</h1>
        <p style={styles.sub}>Island Strategy · Self-Contained · Port 8081</p>

        <div style={styles.grid}>
          {/* --- Ledger Card --- */}
          <div style={styles.card}>
            <h2>director_ledger :5433</h2>
            {error && <p style={styles.err}>{error}</p>}
            {ledger ? (
              <ul style={styles.list}>
                <li>Pending products: <strong>{ledger.pendingCount}</strong></li>
                <li>Total rows: <strong>{ledger.totalCount}</strong></li>
                <li>Tables: <strong>{ledger.tableCount}</strong></li>
              </ul>
            ) : (
              <p>Connecting...</p>
            )}
          </div>

          {/* --- Blender Card --- */}
          <div style={styles.card}>
            <h2>Blender Bridge :5000</h2>
            <p>
              Status:{' '}
              <span style={{
                color: blenderStatus === 'online' ? '#2ecc71' : '#e74c3c',
                fontWeight: 700,
              }}>
                {blenderStatus || 'checking...'}
              </span>
            </p>
            <p>Engine: Blender 5.1 headless</p>
            <p>Script: molecular_sweep.py</p>
          </div>

          {/* --- Open WebUI Card --- */}
          <div style={styles.card}>
            <h2>Open WebUI :3333</h2>
            <p>LLM chat interface</p>
            <a href="http://127.0.0.1:3333" target="_blank" rel="noreferrer" style={styles.link}>
              Open WebUI →
            </a>
          </div>

          {/* --- ZeroClaw Card --- */}
          <div style={styles.card}>
            <h2>ZeroClaw Agent :42617</h2>
            <p>Autonomous orchestrator dashboard</p>
            <a href={ZEROCLAW_URL} target="_blank" rel="noreferrer" style={styles.link}>
              ZeroClaw Dashboard →
            </a>
          </div>

          {/* --- Ghostfolio Card --- */}
          <div style={styles.card}>
            <h2>Ghostfolio :3334</h2>
            <p>Asset allocation & budget caps</p>
            <a href="http://127.0.0.1:3334" target="_blank" rel="noreferrer" style={styles.link}>
              Ghostfolio →
            </a>
          </div>

          {/* --- Shopify Card --- */}
          <div style={styles.card}>
            <h2>Shopify Publish :3002</h2>
            <p>Product staging buffer</p>
            <p style={{ fontSize: '0.8rem', color: '#888' }}>status: hidden (draft)</p>
          </div>
        </div>
      </main>
    </>
  );
}

// Inline styles — no external CSS dependencies.
const styles = {
  main: {
    maxWidth: 960,
    margin: '0 auto',
    padding: '2rem 1rem',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    background: '#0d1117',
    color: '#c9d1d9',
    minHeight: '100vh',
  },
  h1: { fontSize: '2rem', margin: 0, color: '#58a6ff' },
  sub: { color: '#8b949e', marginTop: '0.25rem', marginBottom: '2rem' },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: '1rem',
  },
  card: {
    background: '#161b22',
    border: '1px solid #30363d',
    borderRadius: 8,
    padding: '1.25rem',
  },
  list: { listStyle: 'none', padding: 0, lineHeight: 1.8 },
  link: { color: '#58a6ff', textDecoration: 'none' },
  err: { color: '#f85149' },
};
