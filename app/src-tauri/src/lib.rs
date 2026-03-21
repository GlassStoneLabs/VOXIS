// VOXIS V4.0.0 DENSE — Trinity V8.1 Rust Host
// Copyright © 2026 Glass Stone LLC. All Rights Reserved.
// CEO: Gabriel B. Rodriguez
use tauri::Emitter;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

#[tauri::command]
async fn run_trinity_engine(
    app: tauri::AppHandle,
    file_path: String,
    mode: String,
    stereo_width: f64,
    output_format: String,
    denoise_steps: Option<u32>,
    denoise_strength: Option<f64>,
) -> Result<String, String> {
    println!(
        "[VOXIS] Invoking Trinity V8.1 Engine | file={} mode={} width={:.2} fmt={} steps={:?} str={:?}",
        file_path, mode, stereo_width, output_format, denoise_steps, denoise_strength
    );

    // Derive output path: same directory, suffix _voxis_mastered
    let path = std::path::Path::new(&file_path);
    let dir = path.parent().unwrap_or(std::path::Path::new(""));
    let stem = path
        .file_stem()
        .unwrap_or(std::ffi::OsStr::new("audio"))
        .to_string_lossy();
    let out_ext = if output_format == "FLAC" { "flac" } else { "wav" };
    let out_name = format!("{}_voxis_mastered.{}", stem, out_ext);
    let out_path = dir.join(out_name).to_string_lossy().to_string();

    // Build argument list for sidecar
    let width_str = format!("{:.2}", stereo_width);
    let mut args = vec![
        "--input".to_string(),
        file_path.clone(),
        "--output".to_string(),
        out_path.clone(),
        "--stereo-width".to_string(),
        width_str,
        "--format".to_string(),
        output_format.clone(),
    ];
    if mode == "EXTREME" {
        args.push("--extreme".to_string());
    }
    if let Some(steps) = denoise_steps {
        args.push("--denoise-steps".to_string());
        args.push(steps.to_string());
    }
    if let Some(strength) = denoise_strength {
        args.push("--denoise-strength".to_string());
        args.push(format!("{:.2}", strength));
    }

    let _ = app.emit("trinity-log", ">> [VOXIS] Trinity V8.1 Engine starting up...".to_string());

    // Spawn bundled Python sidecar
    let command = app
        .shell()
        .sidecar("trinity_v8_core")
        .map_err(|e| format!("Sidecar not found: {}. Rebuild the Python engine.", e))?
        .args(args);

    let (mut rx, _child) = command
        .spawn()
        .map_err(|e| format!("Failed to launch Trinity Engine: {}", e))?;

    // Stream stdout/stderr as events to the React frontend in real time
    let mut exit_code: Option<i32> = None;

    while let Some(event) = rx.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() {
                    println!("trinity: {}", msg);
                    let _ = app.emit("trinity-log", msg);
                }
            }
            CommandEvent::Stderr(line) => {
                let msg = String::from_utf8_lossy(&line).trim().to_string();
                if !msg.is_empty() {
                    // Python libs (tqdm, torch) write progress to stderr — not fatal
                    let _ = app.emit("trinity-log", format!("[INFO] {}", msg));
                }
            }
            CommandEvent::Error(err) => {
                let msg = format!("[ERROR] {}", err);
                eprintln!("{}", msg);
                let _ = app.emit("trinity-log", msg);
            }
            CommandEvent::Terminated(payload) => {
                exit_code = payload.code;
                println!("[VOXIS] Engine terminated (code {:?})", exit_code);
                let _ = app.emit(
                    "trinity-log",
                    format!(">> [VOXIS] Engine exited (code {})", exit_code.unwrap_or(-1)),
                );
                break;
            }
            _ => {}
        }
    }

    match exit_code {
        Some(0) => {
            let _ = app.emit("trinity-done", out_path.clone());
            Ok(out_path)
        }
        Some(code) => Err(format!(
            "Trinity Engine exited with code {}. Check the activity log.",
            code
        )),
        None => Err("Trinity Engine terminated unexpectedly.".to_string()),
    }
}

#[tauri::command]
fn get_version() -> String {
    "Voxis 4.0 DENSE | Trinity V8.1 | Glass Stone LLC © 2026".to_string()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![run_trinity_engine, get_version])
        .run(tauri::generate_context!())
        .expect("Error initializing Voxis 4.0 DENSE");
}
