// VOXIS 4.0 DENSE — License Activation Screen
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import './LoginScreen.css';

// Bauhaus logo (same mark as main app)
const Logo = () => (
  <svg viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg" className="ls-logo">
    <line x1="30" y1="0"  x2="30"  y2="120" stroke="#1A1A1A" strokeWidth="5" />
    <line x1="0"  y1="48" x2="120" y2="48"  stroke="#1A1A1A" strokeWidth="5" />
    <line x1="0"  y1="78" x2="120" y2="78"  stroke="#1A1A1A" strokeWidth="5" />
    <rect x="8"  y="10" width="52" height="50" fill="#C9382D" stroke="#1A1A1A" strokeWidth="2" />
    <circle cx="68" cy="38" r="10" fill="#2B5EA0" stroke="#1A1A1A" strokeWidth="2" />
    <polygon points="85,28 98,48 72,48" fill="#F5B731" stroke="#1A1A1A" strokeWidth="2" />
    <circle cx="28" cy="82" r="20" fill="#2B5EA0" stroke="#1A1A1A" strokeWidth="2" />
    <polygon points="60,52 90,110 30,110" fill="#F5B731" stroke="#1A1A1A" strokeWidth="2" />
  </svg>
);

interface Props { onActivated: () => void; }

// Auto-format key input: VOXIS-XXXX-XXXX-XXXX
function formatKey(raw: string): string {
  const clean = raw.replace(/[^A-Za-z0-9]/g, '').toUpperCase().slice(0, 15);
  const prefix = 'VOXIS';
  if (clean.startsWith(prefix)) {
    const rest   = clean.slice(5);
    const groups = rest.match(/.{1,4}/g) ?? [];
    const seg    = groups.slice(0, 3).join('-');
    return seg.length ? `VOXIS-${seg}` : 'VOXIS-';
  }
  if (prefix.startsWith(clean)) return clean;
  return clean.slice(0, 5);
}

export default function LoginScreen({ onActivated }: Props) {
  const [key,      setKey]      = useState('');
  const [email,    setEmail]    = useState('');
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [badField, setBadField] = useState<'key' | 'email' | null>(null);

  const api = typeof window !== 'undefined' ? (window as any).electronAPI : undefined;

  const handleActivate = async () => {
    setError(null);
    setBadField(null);

    if (!key || key.replace(/-/g, '').length < 15) {
      setBadField('key');
      setError('Enter a complete license key  (VOXIS-XXXX-XXXX-XXXX)');
      return;
    }
    const emailTrimmed = email.trim();
    if (!emailTrimmed || !emailTrimmed.includes('@') || !emailTrimmed.includes('.')) {
      setBadField('email');
      setError('Enter a valid email address');
      return;
    }

    setLoading(true);
    try {
      const result = await api?.license.activate(key, emailTrimmed);
      if (result?.success) {
        onActivated();
      } else {
        setError(result?.message ?? 'Activation failed — check your key and try again.');
      }
    } catch {
      setError('Could not reach the license server. Check your internet connection.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ls-shell">

      {/* Background geometric shapes */}
      <div className="ls-bg-shape ls-bg-rect"  />
      <div className="ls-bg-shape ls-bg-circle" />
      <div className="ls-bg-shape ls-bg-tri"   />

      <motion.div
        className="ls-card"
        initial={{ opacity: 0, scale: 0.90, y: 32 }}
        animate={{ opacity: 1, scale: 1.00, y: 0  }}
        transition={{ type: 'spring', stiffness: 260, damping: 26 }}
      >
        {/* Brand header */}
        <div className="ls-header">
          <Logo />
          <div className="ls-brand">
            <div className="ls-brand-line">
              <span className="ls-brand-voxis">VOXIS</span>
              <span className="ls-brand-dense">DENSE</span>
            </div>
            <div className="ls-brand-sub">VOICE RESTORATION V4.0.0</div>
          </div>
        </div>

        <div className="ls-divider" />

        <h2 className="ls-title">ACTIVATE LICENSE</h2>
        <p className="ls-subtitle">Enter your license key to unlock full access</p>

        {/* License key field */}
        <div className={`ls-field ${badField === 'key' ? 'ls-field-err' : ''}`}>
          <label className="ls-label">LICENSE KEY</label>
          <input
            className="ls-input ls-input-mono"
            type="text"
            placeholder="VOXIS-XXXX-XXXX-XXXX"
            value={key}
            onChange={e => setKey(formatKey(e.target.value))}
            maxLength={19}
            disabled={loading}
            autoComplete="off"
            spellCheck={false}
            onKeyDown={e => e.key === 'Enter' && handleActivate()}
          />
        </div>

        {/* Email field */}
        <div className={`ls-field ${badField === 'email' ? 'ls-field-err' : ''}`}>
          <label className="ls-label">EMAIL ADDRESS</label>
          <input
            className="ls-input"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={e => setEmail(e.target.value)}
            disabled={loading}
            autoComplete="email"
            onKeyDown={e => e.key === 'Enter' && handleActivate()}
          />
        </div>

        {/* Error message */}
        <AnimatePresence mode="wait">
          {error && (
            <motion.div
              key={error}
              className="ls-error"
              initial={{ opacity: 0, y: -4, height: 0 }}
              animate={{ opacity: 1, y:  0, height: 'auto' }}
              exit={{    opacity: 0, height: 0 }}
              transition={{ duration: 0.18 }}
            >
              {error}
            </motion.div>
          )}
        </AnimatePresence>

        {/* Activate button */}
        <motion.button
          className="ls-btn-activate"
          onClick={handleActivate}
          disabled={loading}
          whileHover={!loading ? { scale: 1.025, y: -2 } : {}}
          whileTap={!loading ? { scale: 0.975 } : {}}
        >
          {loading ? (
            <motion.span
              animate={{ opacity: [1, 0.5, 1] }}
              transition={{ repeat: Infinity, duration: 1 }}
            >
              ACTIVATING...
            </motion.span>
          ) : 'ACTIVATE'}
        </motion.button>

        {/* Footer info */}
        <div className="ls-info-grid">
          <div className="ls-info-chip">
            <span className="ls-info-label">DEVICES</span>
            <span className="ls-info-val">2 / LICENSE</span>
          </div>
          <div className="ls-info-chip">
            <span className="ls-info-label">OFFLINE</span>
            <span className="ls-info-val">7-DAY GRACE</span>
          </div>
          <div className="ls-info-chip">
            <span className="ls-info-label">SUPPORT</span>
            <span className="ls-info-val">GLASSSTONE.IO</span>
          </div>
        </div>

        <p className="ls-purchase">
          Don't have a license?{' '}
          <span
            className="ls-purchase-link"
            onClick={() => (window as any).electronAPI?.shell?.openFile('https://voxis.glassstone.io')}
          >
            Purchase at voxis.glassstone.io
          </span>
        </p>
      </motion.div>
    </div>
  );
}
