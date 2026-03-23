// VOXIS 4.0 DENSE — License Manager (Rust)
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
//
// Handles: machine fingerprinting, AES-256-GCM local storage,
// online activation/validation, offline grace period.

use aes_gcm::{
    aead::{Aead, KeyInit, OsRng},
    Aes256Gcm, Nonce,
};
use hmac::{Hmac, Mac};
use pbkdf2::pbkdf2_hmac;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::Sha256;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

const OFFLINE_GRACE_DAYS: u64 = 7;
const SALT: &str = "voxis-glass-stone-llc-2026";
const PBKDF2_ROUNDS: u32 = 120_000;

// ── Types ─────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseData {
    pub key: String,
    pub token: String,
    pub email: String,
    pub tier: String,
    pub expiry: Option<String>,
    pub fingerprint: String,
    pub last_validated: u64, // Unix ms
    pub expires_in: u64,    // seconds
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LicenseStatus {
    pub valid: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tier: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub expiry: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub offline: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActivateResult {
    pub success: bool,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tier: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub email: Option<String>,
}

#[derive(Serialize, Deserialize)]
struct Envelope {
    v: u8,
    iv: String,
    data: String,
    tag: String,
}

// ── Paths ─────────────────────────────────────────────────────────────────

fn license_dir() -> PathBuf {
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join(".voxis")
}

fn license_file() -> PathBuf {
    license_dir().join("license.enc")
}

fn license_server_url() -> String {
    std::env::var("VOXIS_LICENSE_SERVER").unwrap_or_else(|_| "http://localhost:3847".to_string())
}

// ── Machine fingerprint ───────────────────────────────────────────────────

pub fn get_machine_fingerprint() -> String {
    let platform = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let hostname = hostname::get()
        .map(|h| h.to_string_lossy().to_string())
        .unwrap_or_else(|_| "unknown".to_string());

    let mut sys = sysinfo::System::new();
    sys.refresh_cpu_all();
    let cpus = sys.cpus();
    let cpu_model = cpus
        .first()
        .map(|c| c.brand().to_string())
        .unwrap_or_else(|| "cpu".to_string());
    let cpu_count = cpus.len();
    let total_mem = sysinfo::System::new_all().total_memory();

    let raw = format!(
        "{}|{}|{}|{}|{}|{}",
        platform, arch, cpu_model, cpu_count, total_mem, hostname
    );

    type HmacSha256 = Hmac<Sha256>;
    let mut mac =
        <HmacSha256 as hmac::Mac>::new_from_slice(SALT.as_bytes()).expect("HMAC key");
    hmac::Mac::update(&mut mac, raw.as_bytes());
    let result = mac.finalize().into_bytes();
    hex::encode(&result[..16])
}

// ── Encryption helpers (AES-256-GCM, machine-bound key) ───────────────────

fn derive_key(fingerprint: &str) -> [u8; 32] {
    let password = format!("{}{}", fingerprint, SALT);
    let mut key = [0u8; 32];
    pbkdf2_hmac::<Sha256>(password.as_bytes(), SALT.as_bytes(), PBKDF2_ROUNDS, &mut key);
    key
}

fn encrypt_data(obj: &LicenseData, key: &[u8; 32]) -> Result<String, String> {
    let cipher = Aes256Gcm::new_from_slice(key).map_err(|e| e.to_string())?;
    let mut iv_bytes = [0u8; 12];
    OsRng.fill_bytes(&mut iv_bytes);
    let nonce = Nonce::from_slice(&iv_bytes);

    let plaintext = serde_json::to_string(obj).map_err(|e| e.to_string())?;
    let ciphertext = cipher
        .encrypt(nonce, plaintext.as_bytes())
        .map_err(|e| e.to_string())?;

    // AES-GCM appends tag to ciphertext — split last 16 bytes as tag
    let (data_bytes, tag_bytes) = ciphertext.split_at(ciphertext.len() - 16);

    let envelope = Envelope {
        v: 1,
        iv: hex::encode(iv_bytes),
        data: hex::encode(data_bytes),
        tag: hex::encode(tag_bytes),
    };
    serde_json::to_string(&envelope).map_err(|e| e.to_string())
}

fn decrypt_data(encoded: &str, key: &[u8; 32]) -> Option<LicenseData> {
    let envelope: Envelope = serde_json::from_str(encoded).ok()?;
    let cipher = Aes256Gcm::new_from_slice(key).ok()?;
    let iv_bytes = hex::decode(&envelope.iv).ok()?;
    let nonce = Nonce::from_slice(&iv_bytes);
    let data_bytes = hex::decode(&envelope.data).ok()?;
    let tag_bytes = hex::decode(&envelope.tag).ok()?;

    // Reconstruct combined ciphertext+tag for aes-gcm
    let mut combined = data_bytes;
    combined.extend_from_slice(&tag_bytes);

    let plaintext = cipher.decrypt(nonce, combined.as_ref()).ok()?;
    serde_json::from_slice(&plaintext).ok()
}

// ── Local storage ─────────────────────────────────────────────────────────

fn read_stored_license() -> Option<LicenseData> {
    let path = license_file();
    let raw = fs::read_to_string(&path).ok()?;
    let key = derive_key(&get_machine_fingerprint());
    decrypt_data(&raw, &key)
}

fn write_stored_license(data: &LicenseData) -> Result<(), String> {
    let dir = license_dir();
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let key = derive_key(&get_machine_fingerprint());
    let encrypted = encrypt_data(data, &key)?;
    fs::write(license_file(), encrypted).map_err(|e| e.to_string())
}

fn clear_stored_license() {
    let _ = fs::remove_file(license_file());
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

// ── Activate ──────────────────────────────────────────────────────────────

pub async fn activate_license(license_key: &str, email: &str) -> ActivateResult {
    let fingerprint = get_machine_fingerprint();
    let server = license_server_url();

    let client = match reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(12))
        .build()
    {
        Ok(c) => c,
        Err(e) => {
            return ActivateResult {
                success: false,
                message: format!("HTTP client error: {}", e),
                tier: None,
                email: None,
            }
        }
    };

    let body = serde_json::json!({
        "key": license_key.trim().to_uppercase(),
        "email": email.trim().to_lowercase(),
        "fingerprint": fingerprint,
        "platform": format!("{}-{}", std::env::consts::OS, std::env::consts::ARCH),
    });

    match client
        .post(format!("{}/api/activate", server))
        .json(&body)
        .send()
        .await
    {
        Ok(res) => {
            let json: serde_json::Value = match res.json().await {
                Ok(j) => j,
                Err(e) => {
                    return ActivateResult {
                        success: false,
                        message: format!("Invalid response: {}", e),
                        tier: None,
                        email: None,
                    }
                }
            };

            if json["success"].as_bool() != Some(true) {
                return ActivateResult {
                    success: false,
                    message: json["error"]
                        .as_str()
                        .unwrap_or("Activation failed")
                        .to_string(),
                    tier: None,
                    email: None,
                };
            }

            let data = LicenseData {
                key: license_key.trim().to_uppercase(),
                token: json["token"].as_str().unwrap_or("").to_string(),
                email: json["email"]
                    .as_str()
                    .unwrap_or(email)
                    .to_string(),
                tier: json["tier"].as_str().unwrap_or("free").to_string(),
                expiry: json["expiry"].as_str().map(|s| s.to_string()),
                fingerprint,
                last_validated: now_ms(),
                expires_in: json["expiresIn"].as_u64().unwrap_or(0),
            };

            let _ = write_stored_license(&data);

            ActivateResult {
                success: true,
                message: "Activated".to_string(),
                tier: Some(data.tier),
                email: Some(data.email),
            }
        }
        Err(e) => ActivateResult {
            success: false,
            message: format!("Cannot reach license server: {}", e),
            tier: None,
            email: None,
        },
    }
}

// ── Validate ──────────────────────────────────────────────────────────────

pub async fn validate_license() -> LicenseStatus {
    let stored = match read_stored_license() {
        Some(s) => s,
        None => {
            return LicenseStatus {
                valid: false,
                tier: None,
                email: None,
                expiry: None,
                reason: Some("No license found".to_string()),
                offline: None,
            }
        }
    };

    let fp = get_machine_fingerprint();
    if stored.fingerprint != fp {
        clear_stored_license();
        return LicenseStatus {
            valid: false,
            tier: None,
            email: None,
            expiry: None,
            reason: Some("License is bound to a different device".to_string()),
            offline: None,
        };
    }

    let server = license_server_url();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .unwrap_or_default();

    let body = serde_json::json!({
        "token": stored.token,
        "fingerprint": fp,
    });

    match client
        .post(format!("{}/api/validate", server))
        .json(&body)
        .send()
        .await
    {
        Ok(res) => {
            let json: serde_json::Value = match res.json().await {
                Ok(j) => j,
                Err(_) => {
                    return offline_fallback(&stored);
                }
            };

            if json["valid"].as_bool() != Some(true) {
                clear_stored_license();
                return LicenseStatus {
                    valid: false,
                    tier: None,
                    email: None,
                    expiry: None,
                    reason: Some(
                        json["error"]
                            .as_str()
                            .unwrap_or("License validation failed")
                            .to_string(),
                    ),
                    offline: None,
                };
            }

            let updated = LicenseData {
                token: json["token"]
                    .as_str()
                    .unwrap_or(&stored.token)
                    .to_string(),
                tier: json["tier"]
                    .as_str()
                    .unwrap_or(&stored.tier)
                    .to_string(),
                last_validated: now_ms(),
                expires_in: json["expiresIn"].as_u64().unwrap_or(stored.expires_in),
                ..stored.clone()
            };
            let _ = write_stored_license(&updated);

            LicenseStatus {
                valid: true,
                tier: Some(updated.tier),
                email: json["email"]
                    .as_str()
                    .map(|s| s.to_string())
                    .or(Some(stored.email)),
                expiry: json["expiry"].as_str().map(|s| s.to_string()),
                reason: None,
                offline: None,
            }
        }
        Err(_) => offline_fallback(&stored),
    }
}

fn offline_fallback(stored: &LicenseData) -> LicenseStatus {
    let days_since = (now_ms() - stored.last_validated) as f64 / 86_400_000.0;
    if days_since <= OFFLINE_GRACE_DAYS as f64 {
        LicenseStatus {
            valid: true,
            tier: Some(stored.tier.clone()),
            email: Some(stored.email.clone()),
            expiry: stored.expiry.clone(),
            reason: None,
            offline: Some(true),
        }
    } else {
        LicenseStatus {
            valid: false,
            tier: None,
            email: None,
            expiry: None,
            reason: Some(format!(
                "License server unreachable — {}-day offline grace period exceeded.",
                OFFLINE_GRACE_DAYS
            )),
            offline: None,
        }
    }
}

// ── Deactivate ────────────────────────────────────────────────────────────

pub async fn deactivate_license() {
    let stored = match read_stored_license() {
        Some(s) => s,
        None => return,
    };

    let server = license_server_url();
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(8))
        .build()
        .unwrap_or_default();

    let body = serde_json::json!({
        "token": stored.token,
        "fingerprint": stored.fingerprint,
    });

    let _ = client
        .post(format!("{}/api/deactivate", server))
        .json(&body)
        .send()
        .await;

    clear_stored_license();
}
