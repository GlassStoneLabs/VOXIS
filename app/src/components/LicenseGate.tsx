// VOXIS 4.0 DENSE — License Gate
// Wraps the full app; shows LoginScreen if no valid license is found.

import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import LoginScreen from './LoginScreen';

type GateState = 'checking' | 'locked' | 'unlocked';

interface Props { children: React.ReactNode; }

export default function LicenseGate({ children }: Props) {
  const [state, setState]     = useState<GateState>('checking');
  const [offline, setOffline] = useState(false);
  const [tier,    setTier]    = useState<string>('');

  const api = typeof window !== 'undefined' ? (window as any).electronAPI : undefined;

  const verify = async () => {
    // Browser preview (no Electron context) — pass through
    if (!api?.license) { setState('unlocked'); return; }
    try {
      const result = await api.license.validate();
      if (result.valid) {
        setOffline(!!result.offline);
        setTier(result.tier || '');
        setState('unlocked');
      } else {
        setState('locked');
      }
    } catch {
      setState('locked');
    }
  };

  useEffect(() => { verify(); }, []);

  // ── Checking splash ────────────────────────────────────────────────────
  if (state === 'checking') {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        height: '100vh', background: '#EDE8D0', gap: '1rem',
      }}>
        <motion.div
          style={{ width: 8, height: 8, borderRadius: '50%', background: '#C9382D' }}
          animate={{ scale: [1, 1.6, 1], opacity: [1, 0.4, 1] }}
          transition={{ repeat: Infinity, duration: 1.2 }}
        />
        <span style={{
          fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
          fontSize: '0.58rem', fontWeight: 700, letterSpacing: '3px',
          color: '#888070', textTransform: 'uppercase',
        }}>
          VERIFYING LICENSE...
        </span>
      </div>
    );
  }

  // ── Locked — show login ────────────────────────────────────────────────
  if (state === 'locked') {
    return <LoginScreen onActivated={verify} />;
  }

  // ── Unlocked — render app ──────────────────────────────────────────────
  return (
    <>
      {offline && (
        <div style={{
          background: '#F5B731', color: '#1A1A1A', textAlign: 'center',
          fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
          fontSize: '0.55rem', fontWeight: 700, letterSpacing: '2px',
          padding: '0.25rem', textTransform: 'uppercase', flexShrink: 0,
        }}>
          OFFLINE MODE — LICENSE SERVER UNREACHABLE · {tier}
        </div>
      )}
      {children}
    </>
  );
}
