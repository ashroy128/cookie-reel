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

def play_success_sound():
    """Plays a notification sound (Ding) using HTML5 Audio."""
    # Short pleasant chime sound
    sound_url = "[https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3](https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3)"
    st.markdown(f"""
        <audio autoplay style="display:none;">
            <source src="{sound_url}" type="audio/mp3">
        </audio>
    """, unsafe_allow_html=True)

def setup_notifications():
    """
    Renders a persistent HTML button to request notification permissions.
    This bypasses Streamlit's rerun cycle to ensure the 'User Gesture' is valid.
    """
    js_code = """
    <script>
        function requestPermission() {
            if (!("Notification" in window)) {
                alert("This browser does not support desktop notifications");
            } else {
                Notification.requestPermission().then(function (permission) {
                    if (permission === "granted") {
                        new Notification("InstaTool", { 
                            body: "✅ Notifications enabled! You will be alerted when downloads finish.",
                            icon: "[https://cdn-icons-png.flaticon.com/512/190/190411.png](https://cdn-icons-png.flaticon.com/512/190/190411.png)"
                        });
                    }
                });
            }
        }
        
        // Listen for specific message to trigger notification from Python
        window.addEventListener("message", function(event) {
            if (event.data.type === "show_notification") {
                if (Notification.permission === "granted") {
                    new Notification(event.data.title, {
                        body: event.data.body,
                        icon: "[https://cdn-icons-png.flaticon.com/512/190/190411.png](https://cdn-icons-png.flaticon.com/512/190/190411.png)"
                    });
                }
            }
        });
    </script>
    
    <div style="background-color: #262730; padding: 10px; border-radius: 5px; border: 1px solid #464b59; margin-bottom: 20px;">
        <p style="margin: 0 0 10px 0; color: white; font-size: 14px;"><strong>Enable Desktop Alerts:</strong></p>
        <button onclick="requestPermission()" style="
            background-color: #4CAF50; 
            border: none; 
            color: white; 
            padding: 8px 16px; 
            text-align: center; 
            text-decoration: none; 
            display: inline-block; 
            font-size: 14px; 
            border-radius: 4px; 
            cursor: pointer;
            width: 100%;">
            🔔 Allow Notifications
        </button>
    </div>
    """
    components.html(js_code, height=100)

def trigger_js_notification(title, body):
    """Triggers the pre-loaded JS listener to show a notification."""
    js_trigger = f"""
    <script>
        window.parent.postMessage({{
            type: "show_notification",
            title: "{title}",
            body: "{body}"
        }}, "*");
    </script>
    """
    components.html(js_trigger, height=0, width=0)

def convert_to_quicktime_mp4(input_path, custom_name=None):
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
            vf='scale=1080:-2:flags=lanczos',
            strict='experimental',
            loglevel='error'
        )
        ffmpeg.run(stream, overwrite_output=True)
        
        if output_path.exists() and output_path.stat().st_size > 0:
            path_obj.unlink()
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
            if not os.path.exists(filename):
                video_id = info.get('id')
                files = list(Path(output_dir).glob(f"*{video_id}*"))
                if files: filename = str(files[0])
                else: return None
            return convert_to_quicktime_mp4(filename, custom_name)
    except Exception as e:
        return None

# --- Main UI ---
def main():
    st.title("📦 InstaTool: Batch & Rename")
    st.markdown("Download Reels. **Auto-Upscale to 1080p.** Mac Ready.")

    # --- Sidebar ---
    with st.sidebar:
        st.header("🔐 Authentication")
        st.info("Upload `cookies.txt` to bypass Instagram login.")
        uploaded_cookie = st.file_uploader("Upload cookies.txt", type=["txt"])
        
        cookie_path = get_cookies_path(uploaded_cookie)
        
        st.markdown("---")
        # New Notification Setup UI
        setup_notifications()
        
        if not cookie_path:
            st.warning("⚠️ Please upload cookies.txt to start.")
            return

    # --- Main Input ---
    st.markdown("### Paste URLs below")
    st.caption("Format: `Link` OR `Link - Custom Filename`")
    
    raw_input = st.text_area(
        "Input Area", 
        height=200, 
        placeholder="[https://www.instagram.com/reel/C-abc123/](https://www.instagram.com/reel/C-abc123/) - My Viral Video\n[https://www.instagram.com/reel/D-xyz987/](https://www.instagram.com/reel/D-xyz987/)"
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
                
                f_path = download_single_video(url, batch_dir, cookie_path, custom_name)
                
                if f_path and os.path.exists(f_path):
                    valid_files.append(f_path)
                    st.toast(f"✅ Ready: {os.path.basename(f_path)}", icon="✨")
                else:
                    failed_lines.append(url)
                
                progress_bar.progress((i + 1) / len(lines), text=f"Finished {i+1}/{len(lines)}")
            
            progress_bar.empty()
            
            # --- Success Logic ---
            if valid_files:
                # 1. Play Sound
                play_success_sound()
                
                # 2. Trigger Desktop Notification
                trigger_js_notification(
                    "InstaTool Batch Complete", 
                    f"{len(valid_files)} videos are ready for download!"
                )
                
                # 3. Show Balloons
                st.balloons()
                st.success(f"🎉 All Done! {len(valid_files)} videos upscaled & ready.")
                
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
