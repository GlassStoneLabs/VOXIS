#!/usr/bin/env node
// ╔══════════════════════════════════════════════════════════════╗
// ║  VOXIS License Server v1.0.0                                 ║
// ║  Copyright © 2026 Glass Stone LLC. All Rights Reserved.      ║
// ║  Hardware-locked license activation & JWT validation         ║
// ╚══════════════════════════════════════════════════════════════╝

'use strict';

require('dotenv').config();

const express    = require('express');
const { DatabaseSync } = require('node:sqlite');
const crypto     = require('crypto');
const jwt        = require('jsonwebtoken');
const rateLimit  = require('express-rate-limit');
const path       = require('path');
const os         = require('os');
const fs         = require('fs');

// ── Config ─────────────────────────────────────────────────────────────────
const PORT               = parseInt(process.env.PORT || '3847');
const JWT_SECRET          = process.env.JWT_SECRET          || 'voxis-dev-jwt-secret-change-in-prod';
const LICENSE_HMAC_SECRET = process.env.LICENSE_HMAC_SECRET || 'voxis-dev-hmac-secret-change-in-prod';
const ADMIN_KEY           = process.env.ADMIN_KEY           || 'change-this-admin-key';
const TOKEN_TTL_DAYS     = parseInt(process.env.TOKEN_TTL_DAYS || '7');
const DB_PATH            = process.env.DB_PATH
  || path.join(os.homedir(), '.voxis-server', 'licenses.db');

if (!JWT_SECRET || JWT_SECRET === 'change-this-to-a-long-random-string-before-production') {
  console.warn('[WARN] JWT_SECRET is not set or is using default. Set it in .env before deploying.');
}
if (!ADMIN_KEY || ADMIN_KEY === 'change-this-admin-key') {
  console.warn('[WARN] ADMIN_KEY is using default. Change it in .env before deploying.');
}

// ── Database ────────────────────────────────────────────────────────────────
fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new DatabaseSync(DB_PATH);
db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

db.exec(`
  CREATE TABLE IF NOT EXISTS licenses (
    id              TEXT PRIMARY KEY,
    key             TEXT UNIQUE NOT NULL,
    email           TEXT,
    tier            TEXT NOT NULL DEFAULT 'PRO',
    max_activations INTEGER NOT NULL DEFAULT 2,
    expiry          TEXT,
    status          TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    notes           TEXT
  );

  CREATE TABLE IF NOT EXISTS activations (
    id           TEXT PRIMARY KEY,
    license_id   TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    fingerprint  TEXT NOT NULL,
    activated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT,
    ip           TEXT,
    platform     TEXT,
    UNIQUE(license_id, fingerprint)
  );

  CREATE INDEX IF NOT EXISTS idx_licenses_key    ON licenses(key);
  CREATE INDEX IF NOT EXISTS idx_licenses_email  ON licenses(email);
  CREATE INDEX IF NOT EXISTS idx_activations_lid ON activations(license_id);
`);

// ── Helpers ─────────────────────────────────────────────────────────────────
function uid() {
  return crypto.randomUUID();
}

function generateLicenseKey(id, tier, expiry) {
  const payload = `${id}|${tier}|${expiry || 'lifetime'}|voxis`;
  const hmac = crypto
    .createHmac('sha256', LICENSE_HMAC_SECRET || 'fallback')
    .update(payload)
    .digest('hex')
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, '');
  return `VOXIS-${hmac.slice(0,4)}-${hmac.slice(4,8)}-${hmac.slice(8,12)}`;
}

function isExpired(license) {
  return license.expiry && new Date(license.expiry) < new Date();
}

function clientIP(req) {
  return (req.headers['x-forwarded-for'] || req.ip || '').toString().split(',')[0].trim();
}

// ── Express setup ────────────────────────────────────────────────────────────
const app = express();
app.set('trust proxy', 1);
app.use(express.json({ limit: '16kb' }));

// CORS
app.use((req, res, next) => {
  const origins = (process.env.ALLOWED_ORIGINS || '*').split(',');
  const origin = req.headers.origin;
  if (origins.includes('*') || origins.includes(origin)) {
    res.setHeader('Access-Control-Allow-Origin', origin || '*');
  }
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-Admin-Key');
  if (req.method === 'OPTIONS') return res.sendStatus(204);
  next();
});

// ── Rate limiters ────────────────────────────────────────────────────────────
const activationLimiter = rateLimit({
  windowMs: 60 * 60 * 1000,
  max: 10,
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many activation attempts. Try again in 1 hour.' },
});

const validateLimiter = rateLimit({
  windowMs: 60 * 1000,
  max: 60,
  message: { error: 'Rate limit exceeded.' },
});

const adminLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  message: { error: 'Admin rate limit exceeded.' },
});

// ── Middleware ───────────────────────────────────────────────────────────────
function adminOnly(req, res, next) {
  const key = req.headers['x-admin-key'];
  if (!ADMIN_KEY || key !== ADMIN_KEY) {
    return res.status(403).json({ error: 'Forbidden' });
  }
  next();
}

// ── Routes ───────────────────────────────────────────────────────────────────

// Health
app.get('/health', (_req, res) => {
  res.json({
    status: 'ok',
    version: '1.0.0',
    product: 'VOXIS 4.0 DENSE',
    timestamp: new Date().toISOString(),
  });
});

// ── POST /api/activate ───────────────────────────────────────────────────────
app.post('/api/activate', activationLimiter, (req, res) => {
  const { key, email, fingerprint, platform } = req.body;

  if (!key || typeof key !== 'string') {
    return res.status(400).json({ error: 'License key is required' });
  }
  if (!fingerprint || typeof fingerprint !== 'string' || fingerprint.length < 8) {
    return res.status(400).json({ error: 'Device fingerprint is required' });
  }

  const normalizedKey = key.trim().toUpperCase();
  const license = db.prepare('SELECT * FROM licenses WHERE key = ?').get(normalizedKey);

  if (!license) {
    return res.status(404).json({ error: 'Invalid license key. Purchase at voxis.glassstone.io' });
  }
  if (license.status === 'REVOKED') {
    return res.status(403).json({ error: 'This license has been revoked.' });
  }
  if (isExpired(license)) {
    db.prepare('UPDATE licenses SET status = ? WHERE id = ?').run('EXPIRED', license.id);
    return res.status(403).json({ error: 'License expired on ' + license.expiry });
  }

  // Check if this device is already activated
  const existing = db
    .prepare('SELECT * FROM activations WHERE license_id = ? AND fingerprint = ?')
    .get(license.id, fingerprint);

  if (!existing) {
    const count = db
      .prepare('SELECT COUNT(*) AS n FROM activations WHERE license_id = ?')
      .get(license.id).n;
    if (count >= license.max_activations) {
      return res.status(403).json({
        error: `Activation limit reached (${license.max_activations} devices). Deactivate an existing device first.`,
        code: 'LIMIT_EXCEEDED',
      });
    }
    db.prepare(
      'INSERT INTO activations (id, license_id, fingerprint, ip, platform) VALUES (?, ?, ?, ?, ?)'
    ).run(uid(), license.id, fingerprint, clientIP(req), platform || 'unknown');
  } else {
    db.prepare(
      "UPDATE activations SET last_seen = datetime('now'), ip = ? WHERE id = ?"
    ).run(clientIP(req), existing.id);
  }

  // Store email on license if not set
  if (email && !license.email) {
    db.prepare('UPDATE licenses SET email = ? WHERE id = ?').run(email.trim().toLowerCase(), license.id);
  }

  const resolvedEmail = email?.trim() || license.email || '';
  const tokenPayload = {
    sub: license.id,
    fp:  fingerprint,
    tier: license.tier,
    email: resolvedEmail,
  };
  const token = jwt.sign(tokenPayload, JWT_SECRET || 'fallback', {
    expiresIn: `${TOKEN_TTL_DAYS}d`,
  });

  res.json({
    success: true,
    token,
    tier: license.tier,
    email: resolvedEmail,
    expiry: license.expiry || null,
    expiresIn: TOKEN_TTL_DAYS * 86400,
  });
});

// ── POST /api/validate ───────────────────────────────────────────────────────
app.post('/api/validate', validateLimiter, (req, res) => {
  const { token, fingerprint } = req.body;

  if (!token) return res.status(400).json({ valid: false, error: 'token required' });
  if (!fingerprint) return res.status(400).json({ valid: false, error: 'fingerprint required' });

  let payload;
  try {
    payload = jwt.verify(token, JWT_SECRET || 'fallback');
  } catch (e) {
    return res.status(401).json({ valid: false, error: 'Token expired or invalid' });
  }

  if (payload.fp !== fingerprint) {
    return res.status(403).json({ valid: false, error: 'Device fingerprint mismatch' });
  }

  const license = db.prepare('SELECT * FROM licenses WHERE id = ?').get(payload.sub);
  if (!license) {
    return res.status(404).json({ valid: false, error: 'License not found' });
  }
  if (license.status !== 'ACTIVE') {
    return res.status(403).json({ valid: false, error: `License is ${license.status.toLowerCase()}` });
  }
  if (isExpired(license)) {
    db.prepare('UPDATE licenses SET status = ? WHERE id = ?').run('EXPIRED', license.id);
    return res.status(403).json({ valid: false, error: 'License has expired' });
  }

  // Update last seen
  db.prepare(
    "UPDATE activations SET last_seen = datetime('now') WHERE license_id = ? AND fingerprint = ?"
  ).run(license.id, fingerprint);

  // Re-issue fresh token
  const newToken = jwt.sign(
    { sub: license.id, fp: fingerprint, tier: license.tier, email: payload.email },
    JWT_SECRET || 'fallback',
    { expiresIn: `${TOKEN_TTL_DAYS}d` }
  );

  res.json({
    valid: true,
    token: newToken,
    tier: license.tier,
    email: payload.email || '',
    expiry: license.expiry || null,
    expiresIn: TOKEN_TTL_DAYS * 86400,
  });
});

// ── POST /api/deactivate ─────────────────────────────────────────────────────
app.post('/api/deactivate', (req, res) => {
  const { token, fingerprint } = req.body;
  if (!token || !fingerprint) {
    return res.status(400).json({ error: 'token and fingerprint required' });
  }
  try {
    const payload = jwt.verify(token, JWT_SECRET || 'fallback', { ignoreExpiration: true });
    db.prepare(
      'DELETE FROM activations WHERE license_id = ? AND fingerprint = ?'
    ).run(payload.sub, fingerprint);
    res.json({ success: true });
  } catch {
    res.status(401).json({ error: 'Invalid token' });
  }
});

// ── Admin: generate key ───────────────────────────────────────────────────────
app.post('/admin/generate', adminLimiter, adminOnly, (req, res) => {
  const {
    email           = null,
    tier            = 'PRO',
    max_activations = 2,
    expiry          = null,
    notes           = '',
  } = req.body;

  const validTiers = ['PRO', 'STUDIO', 'ENTERPRISE'];
  if (!validTiers.includes(tier)) {
    return res.status(400).json({ error: `tier must be one of: ${validTiers.join(', ')}` });
  }

  const id  = uid();
  const key = generateLicenseKey(id, tier, expiry);

  db.prepare(
    'INSERT INTO licenses (id, key, email, tier, max_activations, expiry, notes) VALUES (?, ?, ?, ?, ?, ?, ?)'
  ).run(id, key, email, tier, Number(max_activations), expiry, notes);

  res.status(201).json({ id, key, tier, max_activations, expiry, email });
});

// ── Admin: list licenses ──────────────────────────────────────────────────────
app.get('/admin/licenses', adminLimiter, adminOnly, (req, res) => {
  const { status, tier, search } = req.query;
  let query = `
    SELECT l.*, COUNT(a.id) AS active_devices
    FROM licenses l
    LEFT JOIN activations a ON l.id = a.license_id
    WHERE 1=1
  `;
  const params = [];
  if (status) { query += ' AND l.status = ?'; params.push(status); }
  if (tier)   { query += ' AND l.tier = ?';   params.push(tier);   }
  if (search) { query += ' AND (l.key LIKE ? OR l.email LIKE ?)'; params.push(`%${search}%`, `%${search}%`); }
  query += ' GROUP BY l.id ORDER BY l.created_at DESC';

  res.json(db.prepare(query).all(...params));
});

// ── Admin: get license detail ─────────────────────────────────────────────────
app.get('/admin/licenses/:id', adminLimiter, adminOnly, (req, res) => {
  const license = db.prepare('SELECT * FROM licenses WHERE id = ?').get(req.params.id);
  if (!license) return res.status(404).json({ error: 'Not found' });
  const activations = db.prepare('SELECT * FROM activations WHERE license_id = ? ORDER BY activated_at DESC').all(req.params.id);
  res.json({ ...license, activations });
});

// ── Admin: revoke / restore ───────────────────────────────────────────────────
app.post('/admin/licenses/:id/revoke', adminLimiter, adminOnly, (req, res) => {
  const changes = db.prepare('UPDATE licenses SET status = ? WHERE id = ?').run('REVOKED', req.params.id);
  if (changes.changes === 0) return res.status(404).json({ error: 'Not found' });
  res.json({ success: true, status: 'REVOKED' });
});

app.post('/admin/licenses/:id/restore', adminLimiter, adminOnly, (req, res) => {
  const changes = db.prepare("UPDATE licenses SET status = 'ACTIVE' WHERE id = ?").run(req.params.id);
  if (changes.changes === 0) return res.status(404).json({ error: 'Not found' });
  res.json({ success: true, status: 'ACTIVE' });
});

// ── Admin: delete device activation ──────────────────────────────────────────
app.delete('/admin/activations/:id', adminLimiter, adminOnly, (req, res) => {
  db.prepare('DELETE FROM activations WHERE id = ?').run(req.params.id);
  res.json({ success: true });
});

// ── Admin: stats ──────────────────────────────────────────────────────────────
app.get('/admin/stats', adminLimiter, adminOnly, (_req, res) => {
  const total       = db.prepare('SELECT COUNT(*) AS n FROM licenses').get().n;
  const active      = db.prepare("SELECT COUNT(*) AS n FROM licenses WHERE status = 'ACTIVE'").get().n;
  const revoked     = db.prepare("SELECT COUNT(*) AS n FROM licenses WHERE status = 'REVOKED'").get().n;
  const devices     = db.prepare('SELECT COUNT(*) AS n FROM activations').get().n;
  const byTier      = db.prepare('SELECT tier, COUNT(*) AS n FROM licenses GROUP BY tier').all();
  res.json({ total, active, revoked, devices, byTier });
});

// ── 404 fallback ─────────────────────────────────────────────────────────────
app.use((_req, res) => res.status(404).json({ error: 'Not found' }));

// ── Start ────────────────────────────────────────────────────────────────────
app.listen(PORT, '0.0.0.0', () => {
  console.log('');
  console.log('  ╔══════════════════════════════════════════════╗');
  console.log('  ║  VOXIS License Server v1.0.0                 ║');
  console.log('  ║  Glass Stone LLC © 2026                      ║');
  console.log('  ╚══════════════════════════════════════════════╝');
  console.log('');
  console.log(`  Port   : ${PORT}`);
  console.log(`  DB     : ${DB_PATH}`);
  console.log(`  JWT TTL: ${TOKEN_TTL_DAYS} days`);
  console.log(`  Admin  : ${ADMIN_KEY && ADMIN_KEY !== 'change-this-admin-key' ? '✓ set' : '⚠ using default — change in .env'}`);
  console.log('');
  console.log('  Endpoints:');
  console.log(`    POST   http://0.0.0.0:${PORT}/api/activate`);
  console.log(`    POST   http://0.0.0.0:${PORT}/api/validate`);
  console.log(`    POST   http://0.0.0.0:${PORT}/api/deactivate`);
  console.log(`    POST   http://0.0.0.0:${PORT}/admin/generate   (x-admin-key required)`);
  console.log(`    GET    http://0.0.0.0:${PORT}/admin/licenses    (x-admin-key required)`);
  console.log(`    GET    http://0.0.0.0:${PORT}/admin/stats       (x-admin-key required)`);
  console.log('');
});

module.exports = app; // for testing
