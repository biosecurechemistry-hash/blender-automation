#!/usr/bin/env node
/**
 * test_ledger.js — direct PostgreSQL connection verification.
 *
 * Tests the Docker-managed director_ledger database on port 5433.
 * Run: node test_ledger.js
 */

const { Client } = require('pg');

// Resolve from .env.local if dotenv is available, otherwise use defaults.
const client = new Client({
  host: process.env.PGHOST || '127.0.0.1',
  port: parseInt(process.env.PGPORT || '5433', 10),
  database: process.env.PGDATABASE || 'director_ledger',
  user: process.env.PGUSER || 'bjornjasper',
  password: process.env.PGPASSWORD || '1278458kaliko787',
  // Time out fast if the container isn't running.
  connectionTimeoutMillis: 5000,
});

async function main() {
  console.log('[test_ledger] Connecting to director_ledger on port 5433...');
  const start = Date.now();

  try {
    await client.connect();
    const latency = Date.now() - start;
    console.log(`[test_ledger] Connected in ${latency}ms`);

    // Verify the database name
    const { rows: dbRows } = await client.query('SELECT current_database() AS db');
    console.log(`[test_ledger] Database: ${dbRows[0].db}`);

    // Count pending products
    const { rows: pending } = await client.query(
      "SELECT COUNT(*)::int AS count FROM director_ledger WHERE status = 'pending'"
    );
    console.log(`[test_ledger] Pending products: ${pending[0].count}`);

    // Count total rows
    const { rows: total } = await client.query(
      'SELECT COUNT(*)::int AS count FROM director_ledger'
    );
    console.log(`[test_ledger] Total rows: ${total[0].count}`);

    // List tables in public schema
    const { rows: tables } = await client.query(`
      SELECT table_name
      FROM information_schema.tables
      WHERE table_schema = 'public'
      ORDER BY table_name
    `);
    console.log(`[test_ledger] Tables (${tables.length}):`);
    for (const t of tables) {
      console.log(`  - ${t.table_name}`);
    }

    // Verify service registry
    const { rows: services } = await client.query(
      'SELECT service_name, port, is_active FROM service_registry WHERE is_active = true ORDER BY service_name'
    );
    console.log(`[test_ledger] Active services (${services.length}):`);
    for (const s of services) {
      console.log(`  ${s.service_name}  :${s.port}  active=${s.is_active}`);
    }

    console.log('[test_ledger] PASSED — all checks successful');

  } catch (err) {
    console.error(`[test_ledger] FAILED: ${err.message}`);
    console.error('[test_ledger] Is the Docker container running?');
    console.error('[test_ledger]   docker ps | grep postgres');
    console.error('[test_ledger]   docker start director_ledger');
    process.exit(1);
  } finally {
    await client.end();
  }
}

main();
