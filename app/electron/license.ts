// VOXIS 4.0 DENSE — License Manager
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
//
// Handles: machine fingerprinting, AES-256-GCM local storage,
// online activation/validation, offline grace period.

import * as crypto from 'crypto';
import * as fs     from 'fs';
import * as os     from 'os';
import * as path   from 'path';

// ── Config ─────────────────────────────────────────────────────────────────
const LICENSE_DIR       = path.join(os.homedir(), '.voxis');
const LICENSE_FILE      = path.join(LICENSE_DIR, 'license.enc');
const OFFLINE_GRACE_DAYS = 7;
const SALT              = 'voxis-glass-stone-llc-2026';

// Resolved at runtime — set VOXIS_LICENSE_SERVER env var in production
export function getLicenseServerUrl(): string {
  return process.env.VOXIS_LICENSE_SERVER || 'http://localhost:3847';
}

// ── Types ──────────────────────────────────────────────────────────────────
export interface LicenseData {
  key:           string;
  token:         string;
  email:         string;
  tier:          string;
  expiry:        string | null;
  fingerprint:   string;
  lastValidated: number;   // Unix ms
  expiresIn:     number;   // seconds
}

export interface LicenseStatus {
  valid:    boolean;
  tier?:    string;
  email?:   string;
  expiry?:  string | null;
  reason?:  string;
  offline?: boolean;
}

export interface ActivateResult {
  success: boolean;
  message: string;
  tier?:   string;
  email?:  string;
}

// ── Machine fingerprint ────────────────────────────────────────────────────
export function getMachineFingerprint(): string {
  const cpus = os.cpus();
  const raw  = [
    os.platform(),
    os.arch(),
    cpus[0]?.model ?? 'cpu',
    String(cpus.length),
    String(os.totalmem()),
    os.hostname(),
  ].join('|');
  return crypto
    .createHmac('sha256', SALT)
    .update(raw)
    .digest('hex')
    .slice(0, 32);
}

// ── Encryption helpers (AES-256-GCM, machine-bound key) ───────────────────
function deriveKey(fingerprint: string): Buffer {
  return crypto.pbkdf2Sync(fingerprint + SALT, SALT, 120_000, 32, 'sha256');
}

interface Envelope { v: number; iv: string; data: string; tag: string; }

function encryptData(obj: object, key: Buffer): string {
  const iv     = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', key, iv);
  const enc    = Buffer.concat([cipher.update(JSON.stringify(obj), 'utf8'), cipher.final()]);
  const tag    = cipher.getAuthTag();
  const env: Envelope = {
    v:    1,
    iv:   iv.toString('hex'),
    data: enc.toString('hex'),
    tag:  tag.toString('hex'),
  };
  return JSON.stringify(env);
}

function decryptData(encoded: string, key: Buffer): LicenseData | null {
  try {
    const { iv, data, tag } = JSON.parse(encoded) as Envelope;
    const dec = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(iv, 'hex'));
    dec.setAuthTag(Buffer.from(tag, 'hex'));
    const plain = Buffer.concat([dec.update(Buffer.from(data, 'hex')), dec.final()]);
    return JSON.parse(plain.toString('utf8'));
  } catch {
    return null;
  }
}

// ── Local storage ──────────────────────────────────────────────────────────
export function readStoredLicense(): LicenseData | null {
  try {
    if (!fs.existsSync(LICENSE_FILE)) return null;
    const raw = fs.readFileSync(LICENSE_FILE, 'utf8');
    const key = deriveKey(getMachineFingerprint());
    return decryptData(raw, key);
  } catch {
    return null;
  }
}

export function writeStoredLicense(data: LicenseData): void {
  fs.mkdirSync(LICENSE_DIR, { recursive: true });
  const key = deriveKey(getMachineFingerprint());
  fs.writeFileSync(LICENSE_FILE, encryptData(data, key), 'utf8');
}

export function clearStoredLicense(): void {
  try { fs.unlinkSync(LICENSE_FILE); } catch { /* already absent */ }
}

// ── Activate ───────────────────────────────────────────────────────────────
export async function activateLicense(
  licenseKey: string,
  email: string
): Promise<ActivateResult> {
  const fingerprint = getMachineFingerprint();
  const server      = getLicenseServerUrl();

  try {
    const res = await fetch(`${server}/api/activate`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        key:         licenseKey.trim().toUpperCase(),
        email:       email.trim().toLowerCase(),
        fingerprint,
        platform:    `${os.platform()}-${os.arch()}`,
      }),
      signal: AbortSignal.timeout(12_000),
    });

    const json = await res.json() as any;

    if (!res.ok || !json.success) {
      return { success: false, message: json.error || 'Activation failed' };
    }

    writeStoredLicense({
      key:           licenseKey.trim().toUpperCase(),
      token:         json.token,
      email:         json.email || email,
      tier:          json.tier,
      expiry:        json.expiry ?? null,
      fingerprint,
      lastValidated: Date.now(),
      expiresIn:     json.expiresIn,
    });

    return { success: true, message: 'Activated', tier: json.tier, email: json.email };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { success: false, message: `Cannot reach license server: ${msg}` };
  }
}

// ── Validate ───────────────────────────────────────────────────────────────
export async function validateLicense(): Promise<LicenseStatus> {
  const stored = readStoredLicense();
  if (!stored) return { valid: false, reason: 'No license found' };

  const fp = getMachineFingerprint();
  if (stored.fingerprint !== fp) {
    clearStoredLicense();
    return { valid: false, reason: 'License is bound to a different device' };
  }

  const server = getLicenseServerUrl();

  // Online check
  try {
    const res = await fetch(`${server}/api/validate`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ token: stored.token, fingerprint: fp }),
      signal:  AbortSignal.timeout(8_000),
    });

    const json = await res.json() as any;

    if (!res.ok || !json.valid) {
      clearStoredLicense();
      return { valid: false, reason: json.error || 'License validation failed' };
    }

    // Refresh token + timestamp
    writeStoredLicense({
      ...stored,
      token:         json.token,
      tier:          json.tier,
      lastValidated: Date.now(),
      expiresIn:     json.expiresIn,
    });

    return {
      valid:  true,
      tier:   json.tier,
      email:  json.email,
      expiry: json.expiry ?? null,
    };
  } catch {
    // Offline fallback — grace period
    const daysSince = (Date.now() - stored.lastValidated) / 86_400_000;
    if (daysSince <= OFFLINE_GRACE_DAYS) {
      return {
        valid:   true,
        tier:    stored.tier,
        email:   stored.email,
        expiry:  stored.expiry,
        offline: true,
      };
    }
    return {
      valid:  false,
      reason: `License server unreachable — ${OFFLINE_GRACE_DAYS}-day offline grace period exceeded.`,
    };
  }
}

// ── Deactivate ─────────────────────────────────────────────────────────────
export async function deactivateLicense(): Promise<void> {
  const stored = readStoredLicense();
  if (!stored) return;

  try {
    await fetch(`${getLicenseServerUrl()}/api/deactivate`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ token: stored.token, fingerprint: stored.fingerprint }),
      signal:  AbortSignal.timeout(8_000),
    });
  } catch { /* offline deactivation ok — just clear locally */ }

  clearStoredLicense();
}
