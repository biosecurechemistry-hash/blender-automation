/**
 * GET /api/ledger-summary — lightweight health check + counts.
 * No raw data is leaked; only aggregate integers are returned.
 */
import { healthCheck } from '../../lib/db';

export default async function handler(req, res) {
  if (req.method !== 'GET') {
    return res.status(405).json({ error: 'Method not allowed' });
  }
  const result = await healthCheck();
  if (!result.ok) {
    return res.status(503).json({ error: result.error });
  }
  return res.status(200).json(result);
}
