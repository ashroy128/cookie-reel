import streamlit as st
import streamlit.components.v1 as components
import yt_dlp
import os
import shutil
import zipfile
import tempfile
import ffmpeg
import re
import time
from pathlib import Path

# --- Page Config ---
st.set_page_config(page_title="UniTool: All-in-One Downloader", page_icon="📦", layout="wide")

# --- Helper Functions ---

def cleanup_temp(paths):
    for p in paths:
        if p and os.path.exists(p):
            try:
                if os.path.isfile(p): os.remove(p)
                elif os.path.isdir(p): shutil.rmtree(p)
            except Exception as e: print(f"Cleanup error: {e}")

def get_cookies_path(uploaded_file):
    if not uploaded_file: return None
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='wb') as f:
        f.write(uploaded_file.getvalue())
        return f.name

def sanitize_filename(name):
    """Removes illegal characters from filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip()

def play_success_sound():
    """Plays a notification sound (Ding) using HTML5 Audio."""
    sound_url = "https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3"
    st.markdown(f"""
        <audio autoplay style="display:none;">
            <source src="{sound_url}" type="audio/mp3">
        </audio>
    """, unsafe_allow_html=True)

def trigger_js_notification(title, body):
    """Directly triggers a notification via JS injection."""
    js_code = f"""
    <script>
        if (Notification.permission === "granted") {{
            new Notification("{title}", {{
                body: "{body}",
                icon: "https://cdn-icons-png.flaticon.com/512/190/190411.png"
            }});
        }} else {{
            console.log("Notification permission not granted.");
        }}
    </script>
    """
    components.html(js_code, height=0, width=0)

def convert_to_quicktime_mp4(input_path, custom_name=None):
    """
    Standardizes ANY video input to Mac-compatible H.264/AAC 1080p MP4.
    """
    path_obj = Path(input_path)
    if not path_obj.exists(): return None

    if custom_name:
        safe_name = sanitize_filename(custom_name)
        output_filename = f"{safe_name}.mp4"
    else:
        output_filename = f"{path_obj.stem}_mac.mp4"
        
    output_path = path_obj.parent / output_filename

    try:
        stream = ffmpeg.input(str(input_path))
        stream = ffmpeg.output(
            stream, 
            str(output_path), 
            vcodec='libx264', 
            acodec='aac', 
            pix_fmt='yuv420p',
            vf='scale=1080:-2:flags=lanczos', # Force 1080p width
            strict='experimental',
            loglevel='error'
        )
        ffmpeg.run(stream, overwrite_output=True)
        
        if output_path.exists() and output_path.stat().st_size > 0:
            path_obj.unlink() # Delete original raw download
            return str(output_path)
        return str(input_path)
    except Exception as e:
        print(f"Conversion Error: {e}")
        return str(input_path)

def download_single_video(url, output_dir, cookies_path, custom_name=None):
    # Sanitize URL (remove tracking params)
    if "?" in url:
        url = url.split("?")[0]

    # Determine domain for specific handling if needed
    domain = "Generic"
    if "instagram" in url: domain = "Instagram"
    elif "tiktok" in url: domain = "TikTok"
    elif "youtube" in url or "youtu.be" in url: domain = "YouTube"
    elif "pinterest" in url: domain = "Pinterest"

    # Universal Options
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best', 
        'outtmpl': str(Path(output_dir) / '%(id)s.%(ext)s'), 
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'cookiefile': cookies_path,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            # Verify file existence
            if not os.path.exists(filename):
                video_id = info.get('id')
                files = list(Path(output_dir).glob(f"*{video_id}*"))
                if files: 
                    filename = str(files[0])
                else:
                    # RAISE ERROR to trigger the fallback block below
                    raise FileNotFoundError("Initial download failed to produce file")
            
            # Pass to converter
            converted_path = convert_to_quicktime_mp4(filename, custom_name)
            return converted_path, None # Success, No Error

    except Exception as e:
        # --- YouTube Specific Fallback ---
        # If 'bestvideo+bestaudio' fails (common on servers), try 'best' (single file)
        if domain == "YouTube":
            try:
                print(f"Retrying YouTube with fallback format...")
                # 'best' selects the best single file containing both video+audio
                # This avoids the ffmpeg merge step which often fails on cloud instances
                ydl_opts['format'] = 'best' 
                
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    
                    if not os.path.exists(filename):
                        video_id = info.get('id')
                        files = list(Path(output_dir).glob(f"*{video_id}*"))
                        if files: filename = str(files[0])
                        else: return None, "Fallback failed: File still not found"
                    
                    converted_path = convert_to_quicktime_mp4(filename, custom_name)
                    return converted_path, None
            except Exception as e2:
                return None, f"YouTube Fallback Failed: {e2}"

        return None, str(e)

# --- Main UI ---
def main():
    st.title("📦 UniTool: All-in-One Downloader")
    st.markdown("Supports **Instagram, TikTok, YouTube & Pinterest**. Auto-Upscales to 1080p.")

    # --- Sidebar ---
    with st.sidebar:
        st.header("🔐 Authentication")
        st.info("Upload cookies if you face login issues (Required for Instagram).")
        uploaded_cookie = st.file_uploader("Upload cookies.txt", type=["txt"])
        
        cookie_path = get_cookies_path(uploaded_cookie)
        
        # Optional: Allow running without cookies for TikTok/Pinterest
        if not cookie_path:
            st.warning("⚠️ No cookies uploaded. Instagram links will likely fail. TikTok/YouTube might work.")

    # --- Main Input ---
    st.markdown("### Paste URLs below")
    st.caption("Format: `Link` OR `Link - Custom Filename`")
    
    raw_input = st.text_area(
        "Input Area", 
        height=200, 
        placeholder="https://www.instagram.com/reel/C-abc123/ - Insta Video\nhttps://www.tiktok.com/@user/video/12345 - TikTok Video\nhttps://youtu.be/dQw4w9WgXcQ - YouTube Video"
    )
    
    if st.button("Download All", type="primary"):
        lines = [line.strip() for line in raw_input.splitlines() if line.strip()]
        
        if not lines:
            st.warning("No links provided.")
        else:
            progress_bar = st.progress(0, text="Starting...")
            batch_dir = tempfile.mkdtemp()
            valid_files = []
            failed_lines = []

            for i, line in enumerate(lines):
                if " - " in line:
                    parts = line.split(" - ", 1)
                    url = parts[0].strip()
                    custom_name = parts[1].strip()
                else:
                    url = line
                    custom_name = None

                progress_bar.progress((i) / len(lines), text=f"Downloading: {custom_name if custom_name else url}...")
                
                # Unpack tuple (path, error)
                f_path, error_msg = download_single_video(url, batch_dir, cookie_path, custom_name)
                
                if f_path and os.path.exists(f_path):
                    valid_files.append(f_path)
                    st.toast(f"✅ Ready: {os.path.basename(f_path)}", icon="✨")
                else:
                    failed_lines.append((url, error_msg))
                
                progress_bar.progress((i + 1) / len(lines), text=f"Finished {i+1}/{len(lines)}")
            
            progress_bar.empty()
            
            # --- Success Logic ---
            if valid_files:
                # 1. Play Sound (Native Player)
                play_success_sound()
                
                # 2. Trigger Notification (Direct Injection)
                trigger_js_notification(
                    "Batch Complete", 
                    f"{len(valid_files)} videos downloaded & converted!"
                )
                
                # 3. Show Balloons
                st.balloons()
                st.success(f"🎉 All Done! {len(valid_files)} videos upscaled & ready.")
                
                zip_name = "universal_downloads.zip"
                zip_path = os.path.join(tempfile.gettempdir(), zip_name)
                
                with zipfile.ZipFile(zip_path, 'w') as zipf:
                    for file_path in valid_files:
                        zipf.write(file_path, arcname=os.path.basename(file_path))
                
                with open(zip_path, "rb") as f:
                    st.download_button(
                        label="📦 Download ZIP",
                        data=f,
                        file_name=zip_name,
                        mime="application/zip"
                    )
            
            if failed_lines:
                st.error(f"Failed to download {len(failed_lines)} videos.")
                with st.expander("See Failed Links & Errors"):
                    for url, err in failed_lines:
                        st.markdown(f"**Link:** `{url}`")
                        st.caption(f"Error: {err}")
                        st.divider()

if __name__ == "__main__":
    main()
