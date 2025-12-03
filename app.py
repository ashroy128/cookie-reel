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
st.set_page_config(page_title="InstaTool: Batch & Rename", page_icon="📦", layout="wide")

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

def send_browser_notification(title, body):
    """Injects JavaScript to trigger a browser-level notification."""
    js_code = f"""
    <script>
        (function() {{
            if (!("Notification" in window)) {{
                console.log("This browser does not support desktop notification");
                return;
            }}
            
            function spawnNotification() {{
                new Notification("{title}", {{
                    body: "{body}",
                    icon: "https://cdn-icons-png.flaticon.com/512/2921/2921222.png"
                }});
            }}

            // If granted, show. If not, try to request (might be blocked without user click context, but worth trying)
            if (Notification.permission === "granted") {{
                spawnNotification();
            }} else if (Notification.permission !== "denied") {{
                Notification.requestPermission().then(function (permission) {{
                    if (permission === "granted") {{
                        spawnNotification();
                    }}
                }});
            }}
        }})();
    </script>
    """
    components.html(js_code, height=0, width=0)

def convert_to_quicktime_mp4(input_path, custom_name=None):
    """
    1. Converts to H.264/AAC for Mac compatibility.
    2. Upscales to 1080p width using Lanczos algorithm.
    3. Renames the file if a custom name is provided.
    """
    path_obj = Path(input_path)
    if not path_obj.exists(): return None

    # Determine final filename
    if custom_name:
        safe_name = sanitize_filename(custom_name)
        output_filename = f"{safe_name}.mp4"
    else:
        output_filename = f"{path_obj.stem}_mac.mp4"
        
    output_path = path_obj.parent / output_filename

    try:
        # Run FFmpeg conversion with Upscaling
        # scale=1080:-2 means: Force width to 1080px, calculate height automatically to keep aspect ratio.
        # flags=lanczos means: Use high-quality scaling algorithm (sharper than default).
        stream = ffmpeg.input(str(input_path))
        stream = ffmpeg.output(
            stream, 
            str(output_path), 
            vcodec='libx264', 
            acodec='aac', 
            pix_fmt='yuv420p',
            vf='scale=1080:-2:flags=lanczos', # <--- THE UPSCALING MAGIC
            strict='experimental',
            loglevel='error'
        )
        ffmpeg.run(stream, overwrite_output=True)
        
        if output_path.exists() and output_path.stat().st_size > 0:
            path_obj.unlink() # Delete original
            return str(output_path)
        return str(input_path)
    except Exception as e:
        print(f"Conversion Error: {e}")
        return str(input_path)

def download_single_video(url, output_dir, cookies_path, custom_name=None):
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
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
                if files: filename = str(files[0])
                else: return None

            # Convert, Upscale and Rename
            return convert_to_quicktime_mp4(filename, custom_name)
            
    except Exception as e:
        return None

# --- Main UI ---
def main():
    st.title("📦 InstaTool: Batch & Rename")
    st.markdown("Download Reels. **Auto-Upscale to 1080p.** Mac Ready.")

    # --- Sidebar: Cookies ---
    with st.sidebar:
        st.header("🔐 Authentication")
        st.info("Upload `cookies.txt` to bypass Instagram login.")
        uploaded_cookie = st.file_uploader("Upload cookies.txt", type=["txt"])
        
        cookie_path = get_cookies_path(uploaded_cookie)
        
        st.markdown("---")
        st.header("🔔 Notifications")
        if st.button("Test Notification"):
            send_browser_notification("InstaTool Test", "If you see this, notifications are working!")
            st.success("Notification sent! Check your desktop/notification center.")
        
        if not cookie_path:
            st.warning("⚠️ Please upload cookies.txt to start.")
            return

    # --- Main Input ---
    st.markdown("### Paste URLs below")
    st.caption("Format: `Link` OR `Link - Custom Filename`")
    
    raw_input = st.text_area(
        "Input Area", 
        height=200, 
        placeholder="https://www.instagram.com/reel/C-abc123/ - My Viral Video\nhttps://www.instagram.com/reel/D-xyz987/"
    )
    
    if st.button("Download All", type="primary"):
        # Parse inputs lines
        lines = [line.strip() for line in raw_input.splitlines() if line.strip()]
        
        if not lines:
            st.warning("No links provided.")
        else:
            progress_bar = st.progress(0, text="Starting...")
            batch_dir = tempfile.mkdtemp()
            valid_files = []
            failed_lines = []

            for i, line in enumerate(lines):
                # 1. Parse Link and Name
                if " - " in line:
                    parts = line.split(" - ", 1)
                    url = parts[0].strip()
                    custom_name = parts[1].strip()
                else:
                    url = line
                    custom_name = None

                progress_bar.progress((i) / len(lines), text=f"Downloading: {custom_name if custom_name else url}...")
                
                # 2. Download
                f_path = download_single_video(url, batch_dir, cookie_path, custom_name)
                
                if f_path and os.path.exists(f_path):
                    valid_files.append(f_path)
                    st.toast(f"✅ Ready: {os.path.basename(f_path)}", icon="✨")
                else:
                    failed_lines.append(url)
                
                progress_bar.progress((i + 1) / len(lines), text=f"Finished {i+1}/{len(lines)}")
            
            progress_bar.empty()
            
            # 3. Zip and Serve
            if valid_files:
                # --- CELEBRATION & NOTIFICATION ---
                st.balloons() 
                st.success(f"🎉 All Done! {len(valid_files)} videos upscaled & ready.")
                
                # Trigger Browser Notification
                send_browser_notification(
                    "InstaTool: Batch Complete!", 
                    f"Successfully processed {len(valid_files)} videos."
                )
                
                zip_name = "reels_download.zip"
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
                with st.expander("See Failed Links"):
                    for fail in failed_lines:
                        st.write(fail)

if __name__ == "__main__":
    main()
