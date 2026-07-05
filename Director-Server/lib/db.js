/**
 * lib/db.js — PostgreSQL connection pool for director_ledger.
 *
 * Reads from .env.local: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD.
 * Falls back to hardcoded defaults matching the Docker container.
 */

const { Pool } = require('pg');

const pool = new Pool({
  host: process.env.PGHOST || '127.0.0.1',
  port: parseInt(process.env.PGPORT || '5433', 10),
  database: process.env.PGDATABASE || 'director_ledger',
  user: process.env.PGUSER || 'bjornjasper',
  password: process.env.PGPASSWORD || '1278458kaliko787',
  max: 5,                    // Keep it small — single-machine island
  idleTimeoutMillis: 30000,
  connectionTimeoutMillis: 5000,
});

/** Run a parameterised query and return rows. */
async function query(text, params) {
  const start = Date.now();
  const result = await pool.query(text, params);
  const duration = Date.now() - start;
  if (duration > 200) {
    console.warn(`[db] slow query (${duration}ms): ${text.substring(0, 80)}`);
  }
  return result;
}

/** Fetch a single row or null. */
async function queryOne(text, params) {
  const { rows } = await query(text, params);
  return rows[0] || null;
}

/** Quick health check — returns { ok, pendingCount, totalCount, tableCount }. */
async function healthCheck() {
  try {
    const { rows: pc } = await query(
      "SELECT COUNT(*)::int AS count FROM director_ledger WHERE status = 'pending'"
    );
    const { rows: tc } = await query(
      'SELECT COUNT(*)::int AS count FROM director_ledger'
    );
    const { rows: tbl } = await query(`
      SELECT COUNT(*)::int AS count
      FROM information_schema.tables
      WHERE table_schema = 'public'
    `);
    return {
      ok: true,
      pendingCount: pc[0].count,
      totalCount: tc[0].count,
      tableCount: tbl[0].count,
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

module.exports = { pool, query, queryOne, healthCheck };
