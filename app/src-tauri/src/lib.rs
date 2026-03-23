// VOXIS V4.0.0 DENSE — Trinity V8.2 Tauri Host
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
// CEO: Gabriel B. Rodriguez

mod license;

use std::path::{Path, PathBuf};
use std::process::Command as StdCommand;
use std::sync::Mutex;
use tauri::{Emitter, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// ── App State ─────────────────────────────────────────────────────────────

struct AppState {
    active_child: Mutex<Option<CommandChild>>,
}

// ── Helpers ───────────────────────────────────────────────────────────────

fn home_dir() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn restored_dir() -> PathBuf {
    home_dir().join("Music").join("Voxis Restored")
}

fn derive_output_path(file_path: &str, format: &str) -> String {
    let path = Path::new(file_path);
    let stem = path
        .file_stem()
        .unwrap_or(std::ffi::OsStr::new("audio"))
        .to_string_lossy();
    let out_ext = match format {
        "FLAC" => "flac",
        "MP3" => "mp3",
        _ => "wav",
    };
    let dir = restored_dir();
    let _ = std::fs::create_dir_all(&dir);

    let base = dir.join(format!("{}_voxis_mastered.{}", stem, out_ext));
    if !base.exists() {
        return base.to_string_lossy().to_string();
    }

    let mut collision = 1u32;
    loop {
        let candidate = dir.join(format!(
            "{}_voxis_mastered_{}.{}",
            stem, collision, out_ext
        ));
        if !candidate.exists() {
            return candidate.to_string_lossy().to_string();
        }
        collision += 1;
    }
}

/// Stderr lines matching these patterns are suppressed (noisy but harmless)
const STDERR_SUPPRESS: &[&str] = &[
    "FutureWarning",
    "torch.cuda.amp.autocast",
    "torch.amp.autocast",
    "torch.nn.utils.weight_norm",
    "WeightNorm.apply",
    "rotary_embedding_torch",
    "warnings.warn",
    "% |",
    "it/s]",
    "it, ",
    "the following arguments are required",
];

fn is_suppressed(line: &str) -> bool {
    STDERR_SUPPRESS.iter().any(|pat| line.contains(pat))
}

// ── Commands ──────────────────────────────────────────────────────────────

#[tauri::command]
async fn run_trinity_engine(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    file_path: String,
    mode: String,
    stereo_width: f64,
    output_format: String,
    ram_limit: Option<u32>,
    denoise_steps: Option<u32>,
    denoise_strength: Option<f64>,
) -> Result<String, String> {
    // Guard: reject if already processing
    {
        let guard = state.active_child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Err("Engine is already running. Wait for the current job to finish.".to_string());
        }
    }

    // Validate inputs
    let safe_mode = if mode == "EXTREME" { "EXTREME" } else { "HIGH" };
    let safe_format = match output_format.as_str() {
        "WAV" | "FLAC" | "MP3" => output_format.as_str(),
        _ => "WAV",
    };
    let safe_width = stereo_width.clamp(0.0, 1.0);
    let safe_ram = ram_limit.unwrap_or(75).clamp(25, 100);
    let safe_cfg = denoise_strength.unwrap_or(0.55).clamp(0.1, 1.0);
    let safe_steps = denoise_steps.unwrap_or(16).clamp(8, 64);

    // Derive output path (~/Music/Voxis Restored/)
    let needs_mp3 = safe_format == "MP3";
    let engine_format = if needs_mp3 { "WAV" } else { safe_format };
    let out_path = derive_output_path(&file_path, safe_format);
    let engine_out_path = if needs_mp3 {
        out_path.replace(".mp3", ".wav")
    } else {
        out_path.clone()
    };

    // Build args
    let mut args = vec![
        "--input".to_string(),
        file_path.clone(),
        "--output".to_string(),
        engine_out_path.clone(),
        "--stereo-width".to_string(),
        format!("{:.2}", safe_width),
        "--format".to_string(),
        engine_format.to_string(),
        "--ram-limit".to_string(),
        safe_ram.to_string(),
        "--denoise-steps".to_string(),
        safe_steps.to_string(),
        "--denoise-strength".to_string(),
        format!("{:.2}", safe_cfg),
    ];
    if safe_mode == "EXTREME" {
        args.push("--extreme".to_string());
    }

    println!(
        "[VOXIS] Trinity V8.2 | file={} mode={} width={:.2} fmt={} steps={} str={:.2}",
        file_path, safe_mode, safe_width, safe_format, safe_steps, safe_cfg
    );

    let _ = app.emit(
        "trinity-log",
        ">> [VOXIS] Trinity V8.2 Engine starting...".to_string(),
    );

    // Spawn sidecar
    // macOS .app bundles inherit a minimal PATH that excludes Homebrew.
    // Prepend common FFmpeg locations so audio-separator and ingest can find it.
    let system_path = std::env::var("PATH").unwrap_or_default();
    let extended_path = format!(
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{}",
        system_path
    );

    let command = app
        .shell()
        .sidecar("trinity_v8_core")
        .map_err(|e| format!("Sidecar not found: {}. Rebuild the Python engine.", e))?
        .args(args)
        .envs([
            ("PYTORCH_ENABLE_MPS_FALLBACK", "1"),
            ("PYTHONUNBUFFERED", "1"),
            ("PYTHONFAULTHANDLER", "1"),
            ("PATH", &extended_path),
        ]);

    let (mut rx, child) = command
        .spawn()
        .map_err(|e| format!("Failed to launch Trinity Engine: {}", e))?;

    // Store child for cancellation
    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = Some(child);
    }

    // Stream stdout/stderr as events
    let mut exit_code: Option<i32> = None;

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() {
                    let _ = app.emit("trinity-log", msg);
                }
            }
            CommandEvent::Stderr(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() && !is_suppressed(&msg) {
                    let _ = app.emit("trinity-log", format!("[STDERR] {}", msg));
                }
            }
            CommandEvent::Error(err) => {
                let msg = format!("[ERROR] {}", err);
                eprintln!("{}", msg);
                let _ = app.emit("trinity-log", msg);
            }
            CommandEvent::Terminated(payload) => {
                exit_code = payload.code;
                let _ = app.emit(
                    "trinity-log",
                    format!(
                        ">> [VOXIS] Engine exited (code {})",
                        exit_code.unwrap_or(-1)
                    ),
                );
                break;
            }
            _ => {}
        }
    }

    // Clear active child
    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = None;
    }

    match exit_code {
        Some(0) => {
            // Post-process: WAV → MP3 if requested
            if needs_mp3 && Path::new(&engine_out_path).exists() {
                let _ = app.emit(
                    "trinity-log",
                    ">> [VOXIS] Converting to MP3 (320kbps)...".to_string(),
                );

                let ffmpeg_result = StdCommand::new("ffmpeg")
                    .args([
                        "-y",
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        &engine_out_path,
                        "-c:a",
                        "libmp3lame",
                        "-b:a",
                        "320k",
                        "-q:a",
                        "0",
                        &out_path,
                    ])
                    .output();

                match ffmpeg_result {
                    Ok(output) if output.status.success() => {
                        let _ = std::fs::remove_file(&engine_out_path);
                        let _ = app.emit(
                            "trinity-log",
                            ">> [VOXIS] MP3 export complete.".to_string(),
                        );
                        let _ = app.emit("trinity-done", out_path.clone());
                        Ok(out_path)
                    }
                    _ => {
                        let _ = app.emit(
                            "trinity-log",
                            "[WARN] MP3 conversion failed — returning WAV.".to_string(),
                        );
                        let _ = app.emit("trinity-done", engine_out_path.clone());
                        Ok(engine_out_path)
                    }
                }
            } else {
                let _ = app.emit("trinity-done", out_path.clone());
                Ok(out_path)
            }
        }
        Some(code) => Err(format!(
            "Trinity Engine exited with code {}. Check the activity log.",
            code
        )),
        None => Err("Trinity Engine terminated unexpectedly.".to_string()),
    }
}

#[tauri::command]
async fn cancel_engine(state: State<'_, AppState>) -> Result<(), String> {
    let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
    if let Some(child) = guard.take() {
        child.kill().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn get_version() -> String {
    "VOXIS 4.0 DENSE | Trinity V8.2 | Glass Stone LLC © 2026".to_string()
}

#[tauri::command]
async fn open_file_dialog(app: tauri::AppHandle) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let file = app
        .dialog()
        .file()
        .add_filter(
            "Voice & Audio Files",
            &[
                "wav", "mp3", "flac", "aac", "ogg", "m4a", "aiff", "mp4", "mov", "mkv", "avi",
            ],
        )
        .blocking_pick_file();

    Ok(file.map(|f| f.to_string()))
}

#[tauri::command]
async fn save_file_dialog(
    app: tauri::AppHandle,
    default_name: String,
    ext: String,
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let safe_ext = match ext.as_str() {
        "wav" | "flac" | "mp3" => ext.as_str(),
        _ => "wav",
    };
    let format_name = match safe_ext {
        "wav" => "WAV Audio",
        "flac" => "FLAC Audio",
        "mp3" => "MP3 Audio",
        _ => "Audio",
    };

    let music_dir = home_dir().join("Music");

    let file = app
        .dialog()
        .file()
        .add_filter(format_name, &[safe_ext])
        .add_filter("All Files", &["*"])
        .set_file_name(&default_name)
        .set_directory(&music_dir)
        .blocking_save_file();

    Ok(file.map(|f| f.to_string()))
}

#[tauri::command]
async fn copy_file(src: String, dest: String) -> Result<(), String> {
    std::fs::copy(&src, &dest)
        .map(|_| ())
        .map_err(|e| format!("Copy failed: {}", e))
}

#[tauri::command]
async fn reveal_in_folder(path: String) -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        StdCommand::new("open")
            .args(["-R", &path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "windows")]
    {
        StdCommand::new("explorer")
            .args(["/select,", &path])
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    #[cfg(target_os = "linux")]
    {
        StdCommand::new("xdg-open")
            .arg(Path::new(&path).parent().unwrap_or(Path::new("/")))
            .spawn()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
async fn open_file_native(path: String) -> Result<(), String> {
    open::that(&path).map_err(|e| format!("Failed to open file: {}", e))
}

// ── Model Management Commands ────────────────────────────────────────────

/// Check which ML models are installed and which are missing.
/// Runs the sidecar with --check-models --json to get structured status.
#[tauri::command]
async fn check_models(app: tauri::AppHandle) -> Result<String, String> {
    let voxis_dir = home_dir().join(".voxis");
    let models_dir = voxis_dir.join("dependencies").join("models");
    let _ = std::fs::create_dir_all(&models_dir);

    // Spawn sidecar in check-models mode
    let system_path = std::env::var("PATH").unwrap_or_default();
    let extended_path = format!(
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{}",
        system_path
    );

    let command = app
        .shell()
        .sidecar("trinity_v8_core")
        .map_err(|e| format!("Sidecar not found: {}", e))?
        .args(["--check-models", "--json"])
        .envs([
            ("PYTORCH_ENABLE_MPS_FALLBACK", "1"),
            ("PYTHONUNBUFFERED", "1"),
            ("PATH", &extended_path),
        ]);

    let output = command
        .output()
        .await
        .map_err(|e| format!("Failed to check models: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();

    // Find the JSON line in stdout (may have other log lines)
    for line in stdout.lines().rev() {
        let trimmed = line.trim();
        if trimmed.starts_with('{') && trimmed.ends_with('}') {
            return Ok(trimmed.to_string());
        }
    }

    // Fallback: if sidecar isn't available, check filesystem directly
    let has_models = models_dir
        .read_dir()
        .map(|mut d| d.any(|e| e.is_ok()))
        .unwrap_or(false);

    Ok(format!(
        r#"{{"all_installed":{},"models":[],"total_size_mb":9800,"missing_size_mb":{},"models_dir":"{}"}}"#,
        has_models,
        if has_models { 0 } else { 9800 },
        models_dir.display()
    ))
}

/// Download all missing ML models. Streams progress events.
/// Runs the sidecar with --download-models, streaming stdout as events.
#[tauri::command]
async fn download_models(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    // Guard: don't download while engine is processing
    {
        let guard = state.active_child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Err("Engine is currently processing. Wait for it to finish.".to_string());
        }
    }

    let system_path = std::env::var("PATH").unwrap_or_default();
    let extended_path = format!(
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{}",
        system_path
    );

    let command = app
        .shell()
        .sidecar("trinity_v8_core")
        .map_err(|e| format!("Sidecar not found: {}", e))?
        .args(["--download-models"])
        .envs([
            ("PYTORCH_ENABLE_MPS_FALLBACK", "1"),
            ("PYTHONUNBUFFERED", "1"),
            ("PATH", &extended_path),
        ]);

    let (mut rx, child) = command
        .spawn()
        .map_err(|e| format!("Failed to start model download: {}", e))?;

    // Store child for potential cancellation
    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = Some(child);
    }

    let mut last_status = String::new();

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if msg.starts_with("[MODEL_STATUS]") {
                    // Structured event — forward to frontend
                    let json_part = msg.trim_start_matches("[MODEL_STATUS]").trim();
                    let _ = app.emit("model-download", json_part.to_string());
                    last_status = json_part.to_string();
                } else if !msg.is_empty() {
                    let _ = app.emit("model-log", msg);
                }
            }
            CommandEvent::Stderr(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() && !is_suppressed(&msg) {
                    let _ = app.emit("model-log", format!("[STDERR] {}", msg));
                }
            }
            CommandEvent::Terminated(payload) => {
                let code = payload.code.unwrap_or(-1);
                let _ = app.emit("model-log", format!("Download process exited (code {})", code));
                break;
            }
            _ => {}
        }
    }

    // Clear active child
    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = None;
    }

    Ok(last_status)
}

#[tauri::command]
async fn update_models(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<String, String> {
    // Guard: don't download while engine is processing
    {
        let guard = state.active_child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Err("Engine is currently processing. Wait for it to finish.".to_string());
        }
    }

    let system_path = std::env::var("PATH").unwrap_or_default();
    let extended_path = format!(
        "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{}",
        system_path
    );

    let command = app
        .shell()
        .sidecar("trinity_v8_core")
        .map_err(|e| format!("Sidecar not found: {}", e))?
        .args(["--update-models"])
        .envs([
            ("PYTORCH_ENABLE_MPS_FALLBACK", "1"),
            ("PYTHONUNBUFFERED", "1"),
            ("PATH", &extended_path),
        ]);

    let (mut rx, child) = command
        .spawn()
        .map_err(|e| format!("Failed to start model update: {}", e))?;

    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = Some(child);
    }

    let mut last_status = String::new();

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if msg.starts_with("[MODEL_STATUS]") {
                    let json_part = msg.trim_start_matches("[MODEL_STATUS]").trim();
                    let _ = app.emit("model-download", json_part.to_string());
                    last_status = json_part.to_string();
                } else if !msg.is_empty() {
                    let _ = app.emit("model-log", msg);
                }
            }
            CommandEvent::Stderr(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() && !is_suppressed(&msg) {
                    let _ = app.emit("model-log", format!("[STDERR] {}", msg));
                }
            }
            CommandEvent::Terminated(payload) => {
                let code = payload.code.unwrap_or(-1);
                let _ = app.emit("model-log", format!("Update process exited (code {})", code));
                break;
            }
            _ => {}
        }
    }

    {
        let mut guard = state.active_child.lock().map_err(|e| e.to_string())?;
        *guard = None;
    }

    Ok(last_status)
}

// ── License Commands ──────────────────────────────────────────────────────

#[tauri::command]
fn license_fingerprint() -> String {
    license::get_machine_fingerprint()
}

#[tauri::command]
async fn license_activate(key: String, email: String) -> Result<license::ActivateResult, String> {
    Ok(license::activate_license(&key, &email).await)
}

#[tauri::command]
async fn license_validate() -> Result<license::LicenseStatus, String> {
    Ok(license::validate_license().await)
}

#[tauri::command]
async fn license_deactivate() -> Result<(), String> {
    license::deactivate_license().await;
    Ok(())
}

// ── Entry Point ───────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .manage(AppState {
            active_child: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            run_trinity_engine,
            cancel_engine,
            get_version,
            open_file_dialog,
            save_file_dialog,
            copy_file,
            reveal_in_folder,
            open_file_native,
            check_models,
            download_models,
            update_models,
            license_fingerprint,
            license_activate,
            license_validate,
            license_deactivate,
        ])
        .run(tauri::generate_context!())
        .expect("Error initializing Voxis 4.0 DENSE");
}
