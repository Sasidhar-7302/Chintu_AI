import os
import sys
import zipfile
import shutil
import requests

def install_ffmpeg():
    print("🎬 Starting Automatic FFmpeg Installation...")
    
    # Target directory (venv/Scripts matches PATH in bat)
    target_dir = os.path.join("venv", "Scripts")
    if not os.path.exists(target_dir):
        print(f"❌ Error: Target directory {target_dir} not found.")
        return False

    # Using gyan.dev essentials build
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    zip_path = "ffmpeg.zip"

    try:
        print(f"⬇️ Downloading FFmpeg from {url}...")
        
        # Stream download with requests
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))
            if os.path.exists(zip_path):
                # Resume support not implemented, overwrite
                pass
                
            block_size = 8192
            downloaded = 0
            
            with open(zip_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=block_size): 
                    f.write(chunk)
                    downloaded += len(chunk)
                    # Simple progress
                    done = int(50 * downloaded / total_size) if total_size else 0
                    if total_size:
                        sys.stdout.write(f"\r   [{'=' * done}{' ' * (50-done)}] {downloaded//1024//1024}MB / {total_size//1024//1024}MB")
                        sys.stdout.flush()
        
        print("\n📦 Extracting...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Find the bin folder inside zip
            ffmpeg_path = None
            ffprobe_path = None
            
            for file in zip_ref.namelist():
                if file.endswith("bin/ffmpeg.exe"):
                    ffmpeg_path = file
                if file.endswith("bin/ffprobe.exe"):
                    ffprobe_path = file
            
            if not ffmpeg_path or not ffprobe_path:
                print("❌ Error: Could not find ffmpeg.exe in zip.")
                return False

            # Extract specific files
            zip_ref.extract(ffmpeg_path, ".")
            zip_ref.extract(ffprobe_path, ".")
            
            # Move to target
            print(f"📂 Installing to {target_dir}...")
            # Clean up existing if any
            if os.path.exists(os.path.join(target_dir, "ffmpeg.exe")):
                os.remove(os.path.join(target_dir, "ffmpeg.exe"))
            if os.path.exists(os.path.join(target_dir, "ffprobe.exe")):
                os.remove(os.path.join(target_dir, "ffprobe.exe"))

            shutil.move(ffmpeg_path, os.path.join(target_dir, "ffmpeg.exe"))
            shutil.move(ffprobe_path, os.path.join(target_dir, "ffprobe.exe"))
            
            # Cleanup extracted folders (the root folder from zip)
            extract_root = ffmpeg_path.split("/")[0]
            if os.path.isdir(extract_root):
                shutil.rmtree(extract_root)

        # Cleanup zip
        if os.path.exists(zip_path):
            os.remove(zip_path)
            
        print("✅ FFmpeg Installed Successfully!")
        return True

    except Exception as e:
        print(f"\n❌ Error installing FFmpeg: {e}")
        # Cleanup incomplete zip
        if os.path.exists(zip_path):
            os.remove(zip_path)
        return False

if __name__ == "__main__":
    success = install_ffmpeg()
    sys.exit(0 if success else 1)
