# DriveDrop — YouTube to Google Drive Uploader

A local Streamlit dashboard for transferring a list of YouTube videos to a Google Drive folder. Upload a CSV/Excel list, sign in to Google Drive, watch per-video progress, retry failed items, and export a result report.

> Only download and transfer videos that you own or are authorized to use. The app does not bypass access controls or restrictions.

## Features

- Friendly browser-based dashboard
- Upload a `.csv`, `.xlsx`, or `.xls` video list
- Preview and validate the video queue before processing
- Google Drive OAuth sign-in
- Download videos with `yt-dlp` and merge/remux with FFmpeg
- Upload to your chosen Drive folder with progress
- Reuse an existing non-empty MP4 in `downloads/`
- Retry failed videos
- Export `upload_results.csv`

## 1. Requirements

- Windows 10/11 (also works on macOS/Linux with equivalent commands)
- Python 3.10 or newer
- FFmpeg installed and available on PATH
- A Google Cloud project with the Google Drive API enabled
- OAuth 2.0 Desktop app credentials for the Google account that can access the destination folder

## 2. Install FFmpeg (Windows)

Install FFmpeg and ensure its `bin` directory is on PATH. Open a **new** PowerShell window and check:

```powershell
ffmpeg -version
```

If PowerShell says the command is not recognized, add the FFmpeg `bin` folder to your Windows PATH, then open a new terminal.

## 3. Set up Google Drive access

1. In Google Cloud Console, create/select a project.
2. Enable **Google Drive API**.
3. Configure the OAuth consent screen as required for your account.
4. Create an OAuth Client ID with application type **Desktop app**.
5. Download the JSON file.
6. Rename it to `credentials.json` and place it in the same folder as `app.py`.
7. Keep this file private. It is ignored by Git and must never be committed.
8. The first connection opens a Google sign-in/consent window. A local `token.json` is created after authorization and is also ignored by Git.

The Google account must have permission to upload into the destination folder. If the folder is in a Shared Drive, the app requests Shared Drive support.

## 4. Install and run (PowerShell)

Open PowerShell in the project folder:

```powershell
cd "C:\path\to\youtube_drive_uploader"
py -m venv .venv
```

Activate the environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, you can avoid changing the execution policy and use the environment's Python directly:

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

If activation works, install and launch with:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Streamlit prints a local URL, usually `http://localhost:8501`. Open it in your browser. Keep the terminal window running while using the dashboard.

## 5. Prepare your video list

Use `sample_videos.csv` as a template. Required column names:

| Column | Meaning |
|---|---|
| `video_name` | Unique output name for the video |
| `video_url` | YouTube video URL |
| `file_path` | Retained for compatibility with the CSV format; the app safely stores files in its local `downloads/` folder |

Every `video_name` must be unique. CSV and Excel files are accepted. You can use the same app for Conference, News, TEDx, or another authorized list—just upload the corresponding spreadsheet in the dashboard.

## 6. Use the dashboard

1. Start the app.
2. Upload your CSV/Excel list.
3. Confirm the video queue preview.
4. In the sidebar, check the destination Google Drive folder ID.
5. Click **Connect Google Drive** and complete sign-in.
6. Click **Start upload**.
7. When the run finishes, download the result CSV.
8. If any videos fail, click **Retry failed videos**.

Downloaded files are stored under `downloads/`. Existing non-empty MP4 files are reused, so a rerun can continue without downloading those videos again.

## Troubleshooting

### `credentials.json is missing`
Place your downloaded Google OAuth Desktop app JSON beside `app.py` and rename it `credentials.json`.

### FFmpeg not found
Install FFmpeg, add its `bin` directory to PATH, and restart PowerShell.

### PowerShell blocks `Activate.ps1`
Use the direct `.venv\Scripts\python.exe` commands above; activation is optional.

### Google Drive 404 or permission error
Check the folder ID, ensure the signed-in Google account can access it, and confirm the Drive API is enabled. A 404 can also mean the folder is not shared with that account.

### YouTube extraction warning about JavaScript runtime
Some YouTube formats may require a supported JavaScript runtime. Check the current `yt-dlp` documentation for supported runtimes and install one if needed. Keep `yt-dlp` updated with:

```powershell
python -m pip install --upgrade yt-dlp
```

### A video fails
Read the `error` column in the results CSV. Some videos may be private, unavailable, age/region restricted, or otherwise not accessible to the signed-in session. The app does not circumvent such restrictions.

## GitHub safety checklist

Before pushing:

- Confirm `credentials.json` and `token.json` are not staged.
- Do not upload `.venv/`, downloaded videos, or personal OAuth files.
- Keep `downloads/` and `upload_results.csv` out of the repository.
- If a credential file was ever pushed publicly, revoke/delete that OAuth client secret in Google Cloud and create a new one.

Check Git's view before committing:

```powershell
git status
```

Then:

```powershell
git add .
git commit -m "Add DriveDrop Streamlit dashboard"
git push
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

## Project structure

```text
youtube_drive_uploader/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── sample_videos.csv
└── downloads/              # created locally; ignored by Git
```
