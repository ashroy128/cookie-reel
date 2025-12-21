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
st.set_page_config(page_title="Insta Tool", page_icon="📸", layout="wide")

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
    1. Upscales Videos to 1080p MP4.
    2. Transcribes Videos to .txt (if requested).
    3. Renames Images (no conversion).
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
        if is_video: output_filename = f"{path_obj.stem}_1080p.mp4"
        elif is_image: output_filename = f"{path_obj.stem}.jpg"
        else: output_filename = path_obj.name

    output_path = path_obj.parent / output_filename
    transcript_path = None

    # --- VIDEO PROCESSING ---
    if is_video:
        try:
            # 1. Convert/Upscale
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
                
                # 2. Transcribe (Conditional)
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

                final_media_path = str(output_path) if mode in ["video_only", "both"] else None
                return final_media_path, transcript_path

        except Exception as e:
            print(f"Video fail: {e}")
            return str(input_path), None

    # --- IMAGE PROCESSING ---
    elif is_image:
        if mode == "transcript_only":
            return None, None 

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

    # Standardize URL (Strip query params for Instagram)
    if "?" in url: url = url.split("?")[0]

    ydl_opts = {
        'outtmpl': str(Path(output_dir) / '%(id)s.%(ext)s'),
        'noplaylist': False, # Allows downloading carousels
        'quiet': True,
        'no_warnings': True,
        'cookiefile': cookies_path,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'ignoreerrors': True,
        'format': 'bestvideo+bestaudio/best', 
    }

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
    st.title("Insta Tool")
    st.markdown("Instagram 1080p Batch Downloader + Transcriber")

    with st.sidebar:
        st.header("🔐 Authentication")
        st.info("Upload cookies")
        uploaded_cookie = st.file_uploader("Upload cookies.txt", type=["txt"], key="cookie_uploader")
        cookie_path = get_cookies_path(uploaded_cookie)
        if not cookie_path:
            st.warning("⚠️ No cookies uploaded.")

    # --- Session State Initialization ---
    if 'processed_items' not in st.session_state:
        st.session_state.processed_items = []
    if 'failed_lines' not in st.session_state:
        st.session_state.failed_lines = []
    if 'batch_dir' not in st.session_state:
        st.session_state.batch_dir = None

    # --- INPUT SECTION ---
    # Only show input if we haven't processed anything yet, OR if we want to add more?
    # Usually better to hide it to avoid confusion, or keep it at top.
    # Let's keep it visible but disable buttons if processing to prevent double-clicks.
    
    st.markdown("### Paste URLs below")
    st.caption("Format: `Link` OR `Link - Custom Filename`")
    
    raw_input = st.text_area(
        "Input Area", 
        height=150, 
        placeholder="https://www.instagram.com/reel/C-abc123/ - My Reel\nhttps://www.instagram.com/p/D-xyz987/ - Carousel"
    )
    
    col1, col2 = st.columns(2)
    start_processing = False
    process_mode = "both"
    
    with col1:
        if st.button("Download All", type="primary", use_container_width=True):
            start_processing = True
            process_mode = "video_only"
            
    with col2:
        if st.button("Download & Transcribe All", use_container_width=True):
            start_processing = True
            process_mode = "both"
    
    # --- PROCESSING LOGIC ---
    if start_processing:
        # Clear previous results if any
        st.session_state.processed_items = []
        st.session_state.failed_lines = []
        if st.session_state.batch_dir:
             cleanup_temp([st.session_state.batch_dir])
        
        st.session_state.batch_dir = tempfile.mkdtemp()
        lines = [line.strip() for line in raw_input.splitlines() if line.strip()]
        
        if not lines:
            st.warning("No links provided.")
        else:
            progress_bar = st.progress(0, text="Starting...")
            
            for i, line in enumerate(lines):
                if " - " in line:
                    parts = line.split(" - ", 1)
                    url = parts[0].strip()
                    custom_name = parts[1].strip()
                else:
                    url = line
                    custom_name = None

                if i > 0: time.sleep(5) 

                progress_bar.progress((i) / len(lines), text=f"Processing: {custom_name if custom_name else url}...")
                
                m_paths, t_paths, error_msg = download_content(url, st.session_state.batch_dir, cookie_path, custom_name, process_mode)
                
                if m_paths or t_paths:
                    # Store result in session state
                    # If multiple files returned (carousel), store each one
                    # We store a dict for each "item" (video + transcript pair)
                    # Since m_paths and t_paths lists correspond, we zip them if possible, or handle mismatched lengths
                    
                    # Usually 1 video -> 1 transcript.
                    # Carousel -> 3 videos -> 3 transcripts.
                    # We will treat them as individual items for display
                    
                    # Handle separate lists safely
                    count = max(len(m_paths), len(t_paths))
                    for idx in range(count):
                        item = {
                            "media": m_paths[idx] if idx < len(m_paths) else None,
                            "transcript": t_paths[idx] if idx < len(t_paths) else None,
                            "name": os.path.basename(m_paths[idx]) if idx < len(m_paths) and m_paths[idx] else f"Item {idx+1}"
                        }
                        st.session_state.processed_items.append(item)
                else:
                    st.session_state.failed_lines.append((url, error_msg))
                
                progress_bar.progress((i + 1) / len(lines), text=f"Finished {i+1}/{len(lines)}")
            
            progress_bar.empty()
            st.rerun() # Force reload to show results immediately

    # --- RESULTS DISPLAY ---
    if st.session_state.processed_items:
        st.divider()
        st.subheader("🎉 Ready for Download")
        
        # Display "Start Fresh" at the top of results for easy access
        if st.button("🔄 Start Fresh Session", type="secondary", use_container_width=True):
            if st.session_state.batch_dir:
                cleanup_temp([st.session_state.batch_dir])
            st.session_state.processed_items = []
            st.session_state.failed_lines = []
            st.rerun()

        st.write(f"Processed {len(st.session_state.processed_items)} items.")
        
        for idx, item in enumerate(st.session_state.processed_items):
            with st.container():
                st.markdown(f"**{idx + 1}. {item['name']}**")
                
                cols = st.columns([2, 1, 1])
                
                # Column 1: Preview
                with cols[0]:
                    if item['media']:
                        ext = Path(item['media']).suffix.lower()
                        if ext in ['.jpg', '.jpeg', '.png']:
                            st.image(item['media'], width=300)
                        else:
                            st.video(item['media'])
                
                # Column 2: Media Download
                with cols[1]:
                    if item['media'] and os.path.exists(item['media']):
                        with open(item['media'], "rb") as f:
                            st.download_button(
                                label="Download Media",
                                data=f,
                                file_name=os.path.basename(item['media']),
                                mime="application/octet-stream",
                                key=f"dl_media_{idx}"
                            )
                
                # Column 3: Transcript Download
                with cols[2]:
                    if item['transcript'] and os.path.exists(item['transcript']):
                        with open(item['transcript'], "rb") as f:
                            st.download_button(
                                label="Download Transcript",
                                data=f,
                                file_name=os.path.basename(item['transcript']),
                                mime="text/plain",
                                key=f"dl_trans_{idx}"
                            )
                st.divider()

    # --- FAILED ITEMS ---
    if st.session_state.failed_lines:
        st.error(f"Failed to process {len(st.session_state.failed_lines)} items.")
        with st.expander("See Failed Links"):
            for url, err in st.session_state.failed_lines:
                st.markdown(f"**Link:** `{url}`")
                st.caption(f"Error: {err}")

if __name__ == "__main__":
    main()
