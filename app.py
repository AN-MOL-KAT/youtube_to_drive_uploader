from __future__ import annotations

import csv
import io
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st
import yt_dlp
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
TOKEN_FILE = BASE_DIR / "token.json"
CREDENTIALS_FILE = BASE_DIR / "credentials.json"
RESULT_FILE = BASE_DIR / "upload_results.csv"
DEFAULT_FOLDER_ID = "1JyEbPFztZAxd1UuOPwb4DtmNdKileb4x"
SCOPES = ["https://www.googleapis.com/auth/drive"]
REQUIRED_COLUMNS = ["video_name", "video_url", "file_path"]


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value)).strip(" .")
    return cleaned[:150] or "video"


def load_table(uploaded_file) -> pd.DataFrame:
    uploaded_file.seek(0)
    filename = uploaded_file.name.lower()
    if filename.endswith(".csv"):
        df = pd.read_csv(uploaded_file, encoding="utf-8-sig")
    elif filename.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Please upload a CSV or Excel (.xlsx) file.")

    df.columns = [str(c).strip().lower() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError("Missing required columns: " + ", ".join(missing))

    df = df[REQUIRED_COLUMNS].fillna("")
    for col in REQUIRED_COLUMNS:
        df[col] = df[col].astype(str).str.strip()
    return df


def validate_videos(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        raise ValueError("The uploaded sheet has no video rows.")
    rows = []
    seen = set()
    for index, row in df.iterrows():
        name, url, file_path = (row[c].strip() for c in REQUIRED_COLUMNS)
        if not name or not url:
            raise ValueError(f"Row {index + 2}: video_name and video_url are required.")
        if not re.match(r"^https?://(www\.)?(youtube\.com|youtu\.be)/", url, re.I):
            raise ValueError(f"Row {index + 2}: URL does not look like a YouTube link.")
        filename = safe_filename(name)
        if filename.lower() in seen:
            raise ValueError(f"Duplicate video_name '{name}'. Give every video a unique name.")
        seen.add(filename.lower())
        # Always write downloads inside this project; never trust paths from an uploaded spreadsheet.
        output_path = DOWNLOAD_DIR / f"{filename}.mp4"
        rows.append({
            "video_name": name,
            "video_url": url,
            "file_path": str(output_path.relative_to(BASE_DIR)).replace("\\", "/"),
            "_output_path": output_path,
        })
    return rows


def authenticate_drive():
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            "credentials.json is missing. Add your Google OAuth Desktop app file "
            "to the project folder (keep it private; never commit it to GitHub)."
        )

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and not creds.has_scopes(SCOPES):
        creds = None
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    return build("drive", "v3", credentials=creds)


def check_drive_folder(service, folder_id: str) -> str:
    folder = service.files().get(
        fileId=folder_id, supportsAllDrives=True, fields="id,name,mimeType"
    ).execute()
    if folder.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError("The configured Google Drive ID is not a folder.")
    return folder["name"]


def download_video(url: str, output_path: Path, progress_callback: Callable | None = None):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path, "Reused existing MP4"

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found. Install FFmpeg and add its bin folder to PATH.")

    output_template = str(output_path.with_suffix("")) + ".%(ext)s"

    def hook(data):
        if progress_callback:
            status = data.get("status")
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes", 0)
                pct = min(downloaded / total, 1.0) if total else 0.0
                progress_callback(pct, data.get("_percent_str", "").strip(), data.get("_speed_str", "").strip())
            elif status == "finished":
                progress_callback(1.0, "Download finished; preparing MP4…", "")

    options = {
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
        "outtmpl": output_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,
        "retries": 3,
        "fragment_retries": 3,
        "progress_hooks": [hook],
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        ydl.download([url])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError("yt-dlp finished but the expected MP4 file was not created.")
    return output_path, "Downloaded"


def upload_video(service, file_path: Path, folder_id: str, progress_callback: Callable | None = None):
    media = MediaFileUpload(str(file_path), mimetype="video/mp4", resumable=True, chunksize=8 * 1024 * 1024)
    metadata = {"name": file_path.name, "parents": [folder_id]}
    request = service.files().create(
        body=metadata, media_body=media, supportsAllDrives=True,
        fields="id,name,webViewLink"
    )
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status and progress_callback:
            progress_callback(float(status.progress()), f"{int(status.progress() * 100)}% uploaded")
    return response.get("webViewLink") or f"https://drive.google.com/file/d/{response['id']}/view"


def process_one(row, service, folder_id, on_stage):
    name = row["video_name"]
    result = {
        "video_name": name,
        "video_url": row["video_url"],
        "file_path": row["file_path"],
        "status": "FAILED",
        "drive_link": "",
        "error": "",
    }
    try:
        on_stage("download", 0.0, "Preparing download…")
        file_path, download_note = download_video(
            row["video_url"], row["_output_path"],
            lambda p, msg, speed: on_stage("download", p, f"{msg} {speed}".strip())
        )
        on_stage("upload", 0.0, "Starting Google Drive upload…")
        result["drive_link"] = upload_video(
            service, file_path, folder_id,
            lambda p, msg: on_stage("upload", p, msg)
        )
        result["status"] = "SUCCESS"
        result["error"] = download_note if download_note.startswith("Reused") else ""
    except Exception as exc:
        result["error"] = str(exc)
    return result


def save_results(results: list[dict]):
    fields = ["video_name", "video_url", "file_path", "status", "drive_link", "error"]
    with RESULT_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows([{k: r.get(k, "") for k in fields} for r in results])


st.set_page_config(page_title="DriveDrop | Video Uploader", page_icon="🎬", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@500;600;700;800&display=swap');
:root { --ink:#172033; --muted:#697386; --line:#e8ebf2; --violet:#6d5ce8; }
html, body, [class*="css"] { font-family:'DM Sans',sans-serif; }
.stApp { background:linear-gradient(180deg,#f7f8ff 0%,#fbfcff 42%,#fff 100%); color:var(--ink); }
.block-container { max-width:1200px; padding-top:2rem; padding-bottom:3rem; }
.hero { padding:1.7rem 1.9rem; border-radius:24px; color:white; background:linear-gradient(115deg,#171b36 0%,#39326f 55%,#6d5ce8 100%); box-shadow:0 18px 45px #37316c22; margin-bottom:1.4rem; }
.hero h1 { font-family:Manrope,sans-serif; font-size:2.25rem; font-weight:800; letter-spacing:-1.2px; margin:0 0 .4rem; color:white; }
.hero p { color:#e5e4ff; margin:0; font-size:1rem; }
.eyebrow { color:#c5c0ff; text-transform:uppercase; font-size:.72rem; font-weight:700; letter-spacing:2px; margin-bottom:.6rem; }
.metric { background:white; border:1px solid var(--line); padding:1rem 1.15rem; border-radius:17px; box-shadow:0 5px 20px #1e2a4a08; }
.metric .label { color:var(--muted); font-size:.78rem; font-weight:600; }
.metric .value { font-family:Manrope,sans-serif; color:var(--ink); font-size:1.65rem; font-weight:800; margin-top:.2rem; }
.section-title { font-family:Manrope,sans-serif; font-weight:800; font-size:1.15rem; margin:.4rem 0 .8rem; color:#1c2440; }
.panel { background:white; border:1px solid var(--line); border-radius:18px; padding:1.15rem 1.25rem; }
div[data-testid="stFileUploader"] { background:#fff; border:1.5px dashed #c9c7ef; border-radius:16px; padding:.8rem; }
.stButton>button { border-radius:12px; font-weight:700; min-height:2.8rem; }
.stButton>button[kind="primary"] { background:linear-gradient(100deg,#5d50d8,#8475fa); border:0; }
small, .hint { color:var(--muted); }
[data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:14px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="eyebrow">YOUR VIDEO TRANSFER WORKSPACE</div>
  <h1>DriveDrop 🎬</h1>
  <p>Bring your YouTube video list in. Download, upload, and track everything in one place.</p>
</div>
""", unsafe_allow_html=True)

if "results" not in st.session_state:
    st.session_state.results = []
if "videos" not in st.session_state:
    st.session_state.videos = []
if "source_name" not in st.session_state:
    st.session_state.source_name = ""

with st.sidebar:
    st.markdown("## ⚙️ Workspace settings")
    folder_id = st.text_input("Google Drive folder ID", value=DEFAULT_FOLDER_ID, help="The destination folder must already exist and be accessible to the Google account you connect.")
    st.caption("Destination folder")
    st.markdown(f"[Open folder in Google Drive](https://drive.google.com/drive/folders/{folder_id})" if folder_id.strip() else "Enter a folder ID to show its link.")
    st.divider()
    st.markdown("### Before you start")
    st.write("• Google OAuth file: `credentials.json`")
    st.write("• FFmpeg installed and available in PATH")
    st.write("• Internet connection")
    st.caption("OAuth files stay on this computer and are excluded from Git.")

col1, col2, col3 = st.columns([1.25, 1, 1])
with col1:
    st.markdown('<div class="section-title">1. Add your video list</div>', unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"], help="Required columns: video_name, video_url, file_path")
    st.caption("Use the sample CSV as a template. Each video needs a unique name and YouTube URL.")
with col2:
    st.markdown('<div class="section-title">2. Connect Google Drive</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.write("Sign in with the Google account that can access your destination folder.")
    connect_clicked = st.button("Connect Google Drive", use_container_width=True)
    if connect_clicked:
        try:
            with st.spinner("Opening Google sign-in…"):
                drive_service = authenticate_drive()
                folder_name = check_drive_folder(drive_service, folder_id.strip())
            st.session_state.drive_connected = True
            st.session_state.folder_name = folder_name
            st.success(f"Connected · {folder_name}")
        except Exception as exc:
            st.session_state.drive_connected = False
            st.error(str(exc))
    if st.session_state.get("drive_connected"):
        st.success(f"Connected to {st.session_state.get('folder_name', 'Drive folder')}")
    else:
        st.caption("Not connected yet")
    st.markdown('</div>', unsafe_allow_html=True)
with col3:
    st.markdown('<div class="section-title">3. Transfer videos</div>', unsafe_allow_html=True)
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.write("Existing non-empty MP4 files are reused to avoid downloading them again.")
    start_clicked = st.button("Start upload", type="primary", use_container_width=True, disabled=not st.session_state.get("drive_connected"))
    retry_clicked = st.button("Retry failed videos", use_container_width=True, disabled=not st.session_state.results or not any(r["status"] == "FAILED" for r in st.session_state.results))
    st.markdown('</div>', unsafe_allow_html=True)

if uploaded is not None:
    try:
        df = load_table(uploaded)
        rows = validate_videos(df)
        st.session_state.videos = rows
        st.session_state.source_name = uploaded.name
        st.success(f"Loaded {len(rows)} videos from {uploaded.name}")
    except Exception as exc:
        st.session_state.videos = []
        st.error(str(exc))

videos = st.session_state.videos
if videos:
    total = len(videos)
    completed = sum(1 for r in st.session_state.results if r["status"] == "SUCCESS")
    failed = sum(1 for r in st.session_state.results if r["status"] == "FAILED")
    m1, m2, m3, m4 = st.columns(4)
    for col, label, value in [
        (m1, "VIDEOS IN LIST", total),
        (m2, "SUCCESSFUL", completed),
        (m3, "FAILED", failed),
        (m4, "READY TO PROCESS", max(total - len(st.session_state.results), 0)),
    ]:
        with col:
            st.markdown(f'<div class="metric"><div class="label">{label}</div><div class="value">{value}</div></div>', unsafe_allow_html=True)

    st.markdown('<div class="section-title">Your video queue</div>', unsafe_allow_html=True)
    preview = pd.DataFrame([{k: r[k] for k in REQUIRED_COLUMNS} for r in videos])
    st.dataframe(preview, use_container_width=True, hide_index=True, height=min(360, 38 + 36 * len(preview)))

if start_clicked or retry_clicked:
    if not videos:
        st.error("Upload a valid CSV or Excel file first.")
    elif not folder_id.strip():
        st.error("Enter your Google Drive folder ID.")
    else:
        try:
            service = authenticate_drive()
            check_drive_folder(service, folder_id.strip())
            if retry_clicked:
                failed_names = {r["video_name"] for r in st.session_state.results if r["status"] == "FAILED"}
                queue = [r for r in videos if r["video_name"] in failed_names]
                st.session_state.results = [r for r in st.session_state.results if r["status"] == "SUCCESS"]
            else:
                queue = videos
                st.session_state.results = []

            st.markdown('<div class="section-title">Transfer progress</div>', unsafe_allow_html=True)
            overall = st.progress(0, text="Preparing transfer…")
            current_title = st.empty()
            stage_text = st.empty()
            stage_progress = st.progress(0)
            log_box = st.container()

            total_queue = len(queue)
            for idx, row in enumerate(queue, start=1):
                current_title.markdown(f"**Video {idx} of {total_queue}: {row['video_name']}**")
                state = {"stage": "download", "pct": 0.0, "message": "Starting…"}
                def update_stage(stage, pct, message):
                    state.update(stage=stage, pct=pct, message=message)
                    stage_text.caption(f"{'Downloading' if stage == 'download' else 'Uploading'} · {message}")
                    stage_progress.progress(max(0, min(100, int(pct * 100))))
                result = process_one(row, service, folder_id.strip(), update_stage)
                st.session_state.results.append(result)
                overall.progress(int(idx / total_queue * 100), text=f"Finished {idx} of {total_queue}")
                with log_box:
                    if result["status"] == "SUCCESS":
                        st.success(f"✓ {row['video_name']} uploaded")
                    else:
                        st.error(f"✕ {row['video_name']}: {result['error']}")
                save_results(st.session_state.results)

            st.balloons()
            st.success("Transfer run finished. Download the report below.")
        except Exception as exc:
            st.error(f"Could not start transfer: {exc}")

if st.session_state.results:
    st.markdown('<div class="section-title">Transfer report</div>', unsafe_allow_html=True)
    results_df = pd.DataFrame(st.session_state.results)
    st.dataframe(results_df, use_container_width=True, hide_index=True)
    csv_bytes = results_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ Download results CSV", csv_bytes, file_name="upload_results.csv", mime="text/csv")
    if RESULT_FILE.exists():
        st.caption(f"Local report also saved to: {RESULT_FILE.name}")

st.divider()
st.caption("DriveDrop · Runs locally on your computer. Only videos you are authorized to download should be processed.")
