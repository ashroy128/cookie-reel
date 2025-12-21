import streamlit as st
import yt_dlp
import os
import shutil
import zipfile
import tempfile
import ffmpeg
import re
import time
import mimetypes
import whisper
from pathlib import Path

# --- Page Config ---
st.set_page_config(page_title="Insta Tool: 1080p Batch + Transcriber", page_icon="📦", layout="wide")

# --- Helper Functions ---

@st.cache_resource
def load_whisper():
    return whisper.load_model("base")

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
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return cleaned if cleaned else "media_file"

def process_media(input_path, custom_name=None, index=0, mode="both"):
    """
    1. Upscales/Converts Videos to 1080p MP4.
    2. Transcribes Videos to .txt.
    3. Renames Images.
    mode: 'video_only', 'transcript_only', 'both'
    Returns: (media_path, transcript_path)
    """
    path_obj = Path(input_path)
    if not path_obj.exists(): return None, None

    # Detect media type
    mimetypes.init()
    kind, _ = mimetypes.guess_type(input_path)
    is_video = kind and kind.startswith('video')
    is_image = kind and kind.startswith('image')
    
    # Fallback detection
    if not kind:
        ext = path_obj.suffix.lower()
        if ext in ['.mp4', '.mov', '.mkv', '.webm']: is_video = True
        if ext in ['.jpg', '.jpeg', '.png', '.webp', '.heic']: is_image = True

    # Determine Output Filename
    if custom_name:
        safe_name = sanitize_filename(custom_name)
        if index > 0: safe_name = f"{safe_name}_{index+1}"
        
        if is_video: suffix = ".mp4"
        elif is_image: suffix = ".jpg"
        else: suffix = path_obj.suffix
        
        output_filename = f"{safe_name}{suffix}"
    else:
        if is_video: output_filename = f"{path_obj.stem}_mac.mp4"
        elif is_image: output_filename = f"{path_obj.stem}.jpg"
        else: output_filename = path_obj.name

    output_path = path_obj.parent / output_filename
    transcript_path = None

    # --- VIDEO PROCESSING ---
    if is_video:
        try:
            # 1. Convert/Upscale (Always needed for accurate transcription source or video output)
            # Optimization: If mode is transcript_only, we might skip full upscale? 
            # But converting to mp4/wav is usually safer for whisper. Let's keep standard conversion for stability.
            
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
            
            if output_path.exists():
                if str(input_path) != str(output_path): os.remove(input_path)
                
                # 2. Transcribe
                if mode in ["transcript_only", "both"]:
                    try:
                        model = load_whisper()
                        result = model.transcribe(str(output_path))
                        
                        txt_filename = output_path.stem + ".txt"
                        txt_full_path = output_path.parent / txt_filename
                        
                        with open(txt_full_path, "w", encoding="utf-8") as f:
                            f.write(result["text"].strip())
                        
                        transcript_path = str(txt_full_path)
                    except Exception as e:
                        print(f"Transcription failed: {e}")

                # If user only wanted transcript, we shouldn't return the video path (so it's not zipped)
                # But we still need the file on disk to transcribe it. 
                # We can return None for media_path if mode is transcript_only
                final_media_path = str(output_path) if mode in ["video_only", "both"] else None
                
                return final_media_path, transcript_path

        except Exception as e:
            print(f"Video fail: {e}")
            return str(input_path), None

    # --- IMAGE PROCESSING ---
    elif is_image:
        if mode == "transcript_only":
            return None, None # Can't transcribe images

        try:
            stream = ffmpeg.input(str(input_path))
            stream = ffmpeg.output(stream, str(output_path), loglevel='error')
            ffmpeg.run(stream, overwrite_output=True)
            if output_path.exists():
                if str(input_path) != str(output_path): os.remove(input_path)
                return str(output_path), None
        except:
            if str(input_path) != str(output_path):
                shutil.move(input_path, output_path)
            return str(output_path), None

    return str(input_path), None

def download_content(url, output_dir, cookies_path, custom_name=None, mode="both"):
    existing_files = set(os.listdir(output_dir))

    # Smart URL Cleaning
    if "youtube.com/watch" not in url and "youtu.be/" not in url:
        if "?" in url: url = url.split("?")[0]

    # Cookie Logic
    active_cookies = cookies_path if "instagram.com" in url else None

    ydl_opts = {
        'outtmpl': str(Path(output_dir) / '%(id)s.%(ext)s'),
        'noplaylist': False,
        'quiet': True,
        'no_warnings': True,
        'cookiefile': active_cookies,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'ignoreerrors': True,
        'format': 'bestvideo+bestaudio/best', 
    }

    if "youtube.com" in url or "youtu.be" in url:
        ydl_opts['format'] = 'best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
    except Exception as e:
        pass

    current_files = set(os.listdir(output_dir))
    new_files = list(current_files - existing_files)
    new_files = [f for f in new_files if not f.endswith('.part') and not f.endswith('.ytdl')]
    new_files.sort()

    if not new_files:
        return [], [], "No files found (Check cookies or link)"

    processed_media_files = []
    processed_transcript_files = []

    for i, f in enumerate(new_files):
        full_path = os.path.join(output_dir, f)
        media_p, trans_p = process_media(full_path, custom_name, i, mode)
        
        if media_p: processed_media_files.append(media_p)
        if trans_p: processed_transcript_files.append(trans_p)

    return processed_media_files, processed_transcript_files, None

# --- Main UI ---
def main():
    st.title("📦 Insta Tool - Instagram 1080p Batch Downloader + Transcriber")
    st.markdown("Supports **Instagram, TikTok, YouTube & Pinterest**. Auto-Upscales to 1080p.")

    with st.sidebar:
        st.header("🔐 Authentication")
        st.info("Upload cookies if you face login issues (Required for Instagram).")
        uploaded_cookie = st.file_uploader("Upload cookies.txt", type=["txt"])
        cookie_path = get_cookies_path(uploaded_cookie)
        if not cookie_path:
            st.warning("⚠️ No cookies uploaded. Instagram links will likely fail.")

    st.markdown("### Paste URLs below")
    st.caption("Format: `Link` OR `Link - Custom Filename`")
    
    raw_input = st.text_area(
        "Input Area", 
        height=200, 
        placeholder="https://www.instagram.com/reel/C-abc123/ - Insta Video\nhttps://www.tiktok.com/@user/video/12345 - TikTok Video"
    )
    
    # --- Triple Button Logic ---
    col1, col2, col3 = st.columns(3)
    
    start_processing = False
    process_mode = "both" # Default
    
    with col1:
        if st.button("Download Video Only", type="primary", use_container_width=True):
            start_processing = True
            process_mode = "video_only"
            
    with col2:
        if st.button("Download Transcript Only", use_container_width=True):
            start_processing = True
            process_mode = "transcript_only"

    with col3:
        if st.button("Download Video + Transcript", use_container_width=True):
            start_processing = True
            process_mode = "both"
    
    if start_processing:
        lines = [line.strip() for line in raw_input.splitlines() if line.strip()]
        
        if not lines:
            st.warning("No links provided.")
        else:
            progress_bar = st.progress(0, text="Starting...")
            batch_dir = tempfile.mkdtemp()
            
            all_media = []
            all_transcripts = []
            failed_lines = []

            for i, line in enumerate(lines):
                if " - " in line:
                    parts = line.split(" - ", 1)
                    url = parts[0].strip()
                    custom_name = parts[1].strip()
                else:
                    url = line
                    custom_name = None

                if i > 0 and ("instagram" in url or "tiktok" in url): 
                    time.sleep(5) # Delay for rate limits

                progress_bar.progress((i) / len(lines), text=f"Processing: {custom_name if custom_name else url}...")
                
                # Retrieve both lists
                m_paths, t_paths, error_msg = download_content(url, batch_dir, cookie_path, custom_name, process_mode)
                
                if m_paths:
                    all_media.extend(m_paths)
                    for p in m_paths:
                        st.toast(f"✅ Downloaded: {os.path.basename(p)}", icon="📹")
                
                if t_paths:
                    all_transcripts.extend(t_paths)
                    st.toast(f"✅ Transcribed: {len(t_paths)} files", icon="📝")

                if not m_paths and not t_paths:
                    failed_lines.append((url, error_msg))
                
                progress_bar.progress((i + 1) / len(lines), text=f"Finished {i+1}/{len(lines)}")
            
            progress_bar.empty()
            
            # --- Success Logic ---
            if all_media or all_transcripts:
                st.balloons()
                msg = "🎉 Success!"
                if all_media: msg += f" Processed {len(all_media)} media files."
                if all_transcripts: msg += f" Generated {len(all_transcripts)} transcripts."
                st.success(msg)
                
                download_col1, download_col2 = st.columns(2)
                
                # 1. Video/Image ZIP
                if all_media:
                    media_zip_name = "universal_media.zip"
                    media_zip_path = os.path.join(tempfile.gettempdir(), media_zip_name)
                    with zipfile.ZipFile(media_zip_path, 'w') as zipf:
                        for f in all_media:
                            zipf.write(f, arcname=os.path.basename(f))
                    
                    with download_col1:
                        with open(media_zip_path, "rb") as f:
                            st.download_button(
                                label="📦 Download Media (ZIP)",
                                data=f,
                                file_name=media_zip_name,
                                mime="application/zip",
                                type="primary",
                                use_container_width=True
                            )

                # 2. Transcript ZIP (Only show if transcripts exist)
                if all_transcripts:
                    trans_zip_name = "transcripts.zip"
                    trans_zip_path = os.path.join(tempfile.gettempdir(), trans_zip_name)
                    with zipfile.ZipFile(trans_zip_path, 'w') as zipf:
                        for f in all_transcripts:
                            zipf.write(f, arcname=os.path.basename(f))
                    
                    with download_col2:
                        with open(trans_zip_path, "rb") as f:
                            st.download_button(
                                label="📄 Download Transcripts (ZIP)",
                                data=f,
                                file_name=trans_zip_name,
                                mime="application/zip",
                                use_container_width=True
                            )
            
            if failed_lines:
                st.error(f"Failed to process {len(failed_lines)} items.")
                with st.expander("See Failed Links"):
                    for url, err in failed_lines:
                        st.markdown(f"**Link:** `{url}`")
                        st.caption(f"Error: {err}")
                        st.divider()

if __name__ == "__main__":
    main()
