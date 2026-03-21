#!/usr/bin/env node
// VOXIS License Key Generator — Admin CLI
// Usage:
//   node generate-key.js                          # interactive
//   node generate-key.js --email user@x.com --tier PRO --devices 2
//   node generate-key.js --list
//   node generate-key.js --revoke <id>

'use strict';

require('dotenv').config();

const { DatabaseSync } = require('node:sqlite');
const crypto    = require('crypto');
const path      = require('path');
const os        = require('os');
const fs        = require('fs');

const DB_PATH            = process.env.DB_PATH || path.join(os.homedir(), '.voxis-server', 'licenses.db');
const LICENSE_HMAC_SECRET = process.env.LICENSE_HMAC_SECRET || 'fallback';

fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
const db = new DatabaseSync(DB_PATH);
db.exec('PRAGMA journal_mode = WAL');
db.exec('PRAGMA foreign_keys = ON');

// Ensure schema exists
db.exec(`
  CREATE TABLE IF NOT EXISTS licenses (
    id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL,
    email TEXT, tier TEXT NOT NULL DEFAULT 'PRO',
    max_activations INTEGER NOT NULL DEFAULT 2,
    expiry TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at TEXT NOT NULL DEFAULT (datetime('now')), notes TEXT
  );
  CREATE TABLE IF NOT EXISTS activations (
    id TEXT PRIMARY KEY, license_id TEXT NOT NULL REFERENCES licenses(id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL, activated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen TEXT, ip TEXT, platform TEXT, UNIQUE(license_id, fingerprint)
  );
  CREATE INDEX IF NOT EXISTS idx_licenses_key ON licenses(key);
`);

function uid() { return crypto.randomUUID(); }

function generateKey(id, tier, expiry) {
  const payload = `${id}|${tier}|${expiry || 'lifetime'}|voxis`;
  const hmac = crypto.createHmac('sha256', LICENSE_HMAC_SECRET)
    .update(payload).digest('hex').toUpperCase().replace(/[^A-Z0-9]/g, '');
  return `VOXIS-${hmac.slice(0,4)}-${hmac.slice(4,8)}-${hmac.slice(8,12)}`;
}

const args = process.argv.slice(2);
const get  = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : null; };
const has  = (flag) => args.includes(flag);

// ── List ─────────────────────────────────────────────────────────────────────
if (has('--list') || has('-l')) {
  const licenses = db.prepare(`
    SELECT l.*, COUNT(a.id) as devices
    FROM licenses l LEFT JOIN activations a ON l.id = a.license_id
    GROUP BY l.id ORDER BY l.created_at DESC
  `).all();

  if (licenses.length === 0) {
    console.log('No licenses found.');
    process.exit(0);
  }

  console.log('\n  VOXIS License Database\n');
  console.log('  ' + '─'.repeat(80));
  console.log(`  ${'KEY'.padEnd(20)} ${'TIER'.padEnd(12)} ${'EMAIL'.padEnd(28)} ${'STATUS'.padEnd(10)} DEV`);
  console.log('  ' + '─'.repeat(80));
  for (const l of licenses) {
    const key    = l.key.padEnd(20);
    const tier   = l.tier.padEnd(12);
    const email  = (l.email || '—').padEnd(28);
    const status = l.status.padEnd(10);
    const devs   = `${l.devices}/${l.max_activations}`;
    console.log(`  ${key} ${tier} ${email} ${status} ${devs}`);
  }
  console.log('  ' + '─'.repeat(80));
  console.log(`  Total: ${licenses.length} licenses\n`);
  process.exit(0);
}

// ── Revoke ────────────────────────────────────────────────────────────────────
if (has('--revoke')) {
  const id = get('--revoke');
  if (!id) { console.error('Usage: --revoke <license-id>'); process.exit(1); }
  const changes = db.prepare("UPDATE licenses SET status = 'REVOKED' WHERE id = ?").run(id);
  if (changes.changes === 0) { console.error('License not found:', id); process.exit(1); }
  console.log(`✓ License ${id} revoked.`);
  process.exit(0);
}

// ── Generate ─────────────────────────────────────────────────────────────────
const email    = get('--email')   || null;
const tier     = (get('--tier')   || 'PRO').toUpperCase();
const devices  = parseInt(get('--devices') || '2');
const expiry   = get('--expiry')  || null; // ISO date string e.g. 2027-01-01
const notes    = get('--notes')   || '';

const validTiers = ['PRO', 'STUDIO', 'ENTERPRISE'];
if (!validTiers.includes(tier)) {
  console.error(`Invalid tier. Must be one of: ${validTiers.join(', ')}`);
  process.exit(1);
}

const id  = uid();
const key = generateKey(id, tier, expiry);

db.prepare(
  'INSERT INTO licenses (id, key, email, tier, max_activations, expiry, notes) VALUES (?, ?, ?, ?, ?, ?, ?)'
).run(id, key, email, tier, devices, expiry, notes);

console.log('');
console.log('  ╔══════════════════════════════════════════════╗');
console.log('  ║  New VOXIS License Key Generated             ║');
console.log('  ╚══════════════════════════════════════════════╝');
console.log('');
console.log(`  Key     : ${key}`);
console.log(`  ID      : ${id}`);
console.log(`  Tier    : ${tier}`);
console.log(`  Devices : ${devices}`);
console.log(`  Email   : ${email || '(not set)'}`);
console.log(`  Expiry  : ${expiry || 'lifetime'}`);
console.log(`  Notes   : ${notes || '—'}`);
console.log('');
