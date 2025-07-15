from flask import Flask, request, render_template, jsonify, send_file
import os
import tempfile
import threading
import requests
import json
import re
from datetime import datetime
import yt_dlp
import instaloader
from werkzeug.utils import secure_filename
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this'

# Create downloads directory if it doesn't exist
DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

class UniversalDownloader:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
    def detect_platform(self, url):
        """Detect the platform from URL"""
        url = url.lower()
        if 'youtube.com' in url or 'youtu.be' in url:
            return 'youtube'
        elif 'instagram.com' in url:
            return 'instagram'
        elif 'facebook.com' in url or 'fb.watch' in url:
            return 'facebook'
        elif 'twitter.com' in url or 'x.com' in url:
            return 'twitter'
        elif 'tiktok.com' in url:
            return 'tiktok'
        elif 'pinterest.com' in url:
            return 'pinterest'
        elif 'linkedin.com' in url:
            return 'linkedin'
        elif 'snapchat.com' in url:
            return 'snapchat'
        elif 'reddit.com' in url:
            return 'reddit'
        elif 'twitch.tv' in url:
            return 'twitch'
        else:
            return 'unknown'
    
    def create_safe_filename(self, filename, max_length=100):
        """Create a safe filename"""
        # Remove invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip()
        if len(filename) > max_length:
            filename = filename[:max_length]
        return filename
    
    def download_youtube_content(self, url, path, audio_only=False):
        """Download YouTube videos, shorts, playlists"""
        try:
            if audio_only:
                # Check if FFmpeg is available
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    # Use FFmpeg for MP3 conversion
                    ydl_opts = {
                        'outtmpl': os.path.join(path, '%(uploader)s - %(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'writesubtitles': False,
                        'ignoreerrors': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    # Download audio without conversion
                    ydl_opts = {
                        'outtmpl': os.path.join(path, '%(uploader)s - %(title)s.%(ext)s'),
                        'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
                        'writesubtitles': False,
                        'ignoreerrors': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(uploader)s - %(title)s.%(ext)s'),
                    'format': 'best[height<=1080]',
                    'writesubtitles': True,
                    'writeautomaticsub': True,
                    'subtitleslangs': ['en'],
                    'ignoreerrors': True,
                }
            
            print(f"🎵 Audio extraction settings: FFmpeg available = {ffmpeg_available if audio_only else 'N/A'}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                content_type = 'audio' if audio_only else 'video'
                
                if 'entries' in info:  # Playlist
                    titles = [entry.get('title', 'Unknown') for entry in info['entries'] if entry]
                    message = f'Downloaded {len(titles)} {content_type}s from playlist'
                    if audio_only:
                        message += f' ({conversion_msg})'
                    return {
                        'status': 'success',
                        'message': message,
                        'titles': titles[:5],  # Show first 5 titles
                        'type': f'playlist_{content_type}'
                    }
                else:  # Single video
                    message = f'YouTube {content_type} downloaded successfully!'
                    if audio_only:
                        message += f' ({conversion_msg})'
                    return {
                        'status': 'success',
                        'message': message,
                        'title': info.get('title', 'Unknown'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'type': content_type
                    }
        except Exception as e:
            error_msg = str(e)
            print(f"❌ YouTube download error: {error_msg}")
            return {'status': 'error', 'message': f'YouTube error: {error_msg}'}
    
    def check_ffmpeg_availability(self):
        """Check if FFmpeg is available on the system"""
        try:
            import subprocess
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return False
    
    def download_instagram_content(self, url, path):
        """Download Instagram posts, reels, stories, IGTV"""
        try:
            loader = instaloader.Instaloader(
                dirname_pattern=path,
                filename_pattern='{profile}_{mediaid}_{date_utc}',
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=True,
                compress_json=False
            )
            
            # Handle different Instagram URL types
            if '/stories/' in url:
                # Story URL
                username = self.extract_instagram_username(url)
                if username:
                    profile = instaloader.Profile.from_username(loader.context, username)
                    for story in loader.get_stories([profile.userid]):
                        for item in story.get_items():
                            loader.download_storyitem(item, target=username)
                    return {
                        'status': 'success',
                        'message': f'Instagram stories downloaded for {username}',
                        'type': 'stories'
                    }
            elif '/reel/' in url or '/p/' in url or '/tv/' in url:
                # Post, Reel, or IGTV
                shortcode = self.extract_instagram_shortcode(url)
                post = instaloader.Post.from_shortcode(loader.context, shortcode)
                
                loader.download_post(post, target=post.owner_username)
                
                content_type = 'reel' if post.is_video else 'post'
                if post.typename == 'GraphSidecar':
                    content_type = 'carousel'
                
                return {
                    'status': 'success',
                    'message': f'Instagram {content_type} downloaded successfully!',
                    'username': post.owner_username,
                    'caption': post.caption[:100] + '...' if post.caption and len(post.caption) > 100 else post.caption,
                    'type': content_type
                }
            else:
                # Profile URL - download recent posts
                username = self.extract_instagram_username(url)
                profile = instaloader.Profile.from_username(loader.context, username)
                
                count = 0
                for post in profile.get_posts():
                    if count >= 10:  # Limit to 10 recent posts
                        break
                    loader.download_post(post, target=username)
                    count += 1
                
                return {
                    'status': 'success',
                    'message': f'Downloaded {count} recent posts from {username}',
                    'type': 'profile'
                }
                
        except Exception as e:
            return {'status': 'error', 'message': f'Instagram error: {str(e)}'}
    
    def download_tiktok_content(self, url, path, audio_only=False):
        """Download TikTok videos"""
        try:
            if audio_only:
                # Check FFmpeg availability for TikTok too
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'TikTok_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'TikTok_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'TikTok_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                content_type = 'audio' if audio_only else 'video'
                message = f'TikTok {content_type} downloaded successfully!'
                if audio_only:
                    message += f' ({conversion_msg})'
                return {
                    'status': 'success',
                    'message': message,
                    'title': info.get('title', 'TikTok Video'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'TikTok error: {str(e)}'}
    
    def download_twitter_content(self, url, path, audio_only=False):
        """Download Twitter/X videos, images, threads"""
        try:
            if audio_only:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                    'writesubtitles': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                content_type = 'audio' if audio_only else 'tweet'
                return {
                    'status': 'success',
                    'message': f'Twitter {content_type} downloaded successfully!',
                    'title': info.get('title', 'Twitter Content'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Twitter error: {str(e)}'}
    
    def download_facebook_content(self, url, path, audio_only=False):
        """Download Facebook videos, posts"""
        try:
            if audio_only:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Facebook_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Facebook_%(title)s.%(ext)s'),
                    'format': 'best',
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                content_type = 'audio' if audio_only else 'video'
                return {
                    'status': 'success',
                    'message': f'Facebook {content_type} downloaded successfully!',
                    'title': info.get('title', 'Facebook Content'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Facebook error: {str(e)}'}
    
    def download_reddit_content(self, url, path, audio_only=False):
        """Download Reddit videos, images, gifs"""
        try:
            if audio_only:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                content_type = 'audio' if audio_only else 'post'
                return {
                    'status': 'success',
                    'message': f'Reddit {content_type} downloaded successfully!',
                    'title': info.get('title', 'Reddit Post'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Reddit error: {str(e)}'}
    
    def download_generic_content(self, url, path, audio_only=False):
        """Download from any supported platform using yt-dlp"""
        try:
            if audio_only:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                    'format': 'best',
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                content_type = 'audio' if audio_only else 'media'
                return {
                    'status': 'success',
                    'message': f'{content_type.title()} downloaded successfully!',
                    'title': info.get('title', 'Unknown'),
                    'extractor': info.get('extractor', 'Unknown'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Download error: {str(e)}'}
    
    def extract_instagram_shortcode(self, url):
        """Extract shortcode from Instagram URL"""
        patterns = [
            r'/p/([^/?]+)',
            r'/reel/([^/?]+)',
            r'/tv/([^/?]+)'
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def extract_instagram_username(self, url):
        """Extract username from Instagram URL"""
        match = re.search(r'instagram\.com/([^/?]+)', url)
        if match:
            return match.group(1)
        return None
    
    def download_content(self, url, custom_path=None, audio_only=False):
        """Main download function"""
        path = custom_path or DOWNLOAD_DIR
        platform = self.detect_platform(url)
        
        # Create timestamped folder for this download
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        content_type = "audio" if audio_only else "video"
        download_folder = os.path.join(path, f"{platform}_{content_type}_{timestamp}")
        os.makedirs(download_folder, exist_ok=True)
        
        try:
            if platform == 'youtube':
                return self.download_youtube_content(url, download_folder, audio_only)
            elif platform == 'instagram':
                # Instagram doesn't support audio-only extraction directly
                if audio_only:
                    return {'status': 'error', 'message': 'Audio-only download not supported for Instagram'}
                return self.download_instagram_content(url, download_folder)
            elif platform == 'tiktok':
                return self.download_tiktok_content(url, download_folder, audio_only)
            elif platform == 'twitter':
                return self.download_twitter_content(url, download_folder, audio_only)
            elif platform == 'facebook':
                return self.download_facebook_content(url, download_folder, audio_only)
            elif platform == 'reddit':
                return self.download_reddit_content(url, download_folder, audio_only)
            else:
                # Try generic download for other platforms
                return self.download_generic_content(url, download_folder, audio_only)
                
        except Exception as e:
            return {'status': 'error', 'message': f'Unexpected error: {str(e)}'}

# Initialize downloader
downloader = UniversalDownloader()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    """Handle download requests"""
    try:
        print(f"📥 Download request received at {datetime.now()}")
        
        # Handle both JSON and form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
            
        url = data.get('url', '').strip()
        audio_only = data.get('audio_only', False)
        
        print(f"📎 URL: {url}")
        print(f"🎵 Audio only: {audio_only}")
        
        if not url:
            return jsonify({'status': 'error', 'message': 'URL is required'})
        
        # Detect platform automatically
        platform = downloader.detect_platform(url)
        print(f"🌐 Detected platform: {platform}")
        
        # Start download
        result = downloader.download_content(url, audio_only=audio_only)
        result['platform'] = platform
        
        print(f"📤 Download result: {result}")
        return jsonify(result)
        
    except Exception as e:
        error_msg = f'Server error: {str(e)}'
        print(f"❌ Error: {error_msg}")
        return jsonify({'status': 'error', 'message': error_msg})

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Server is running',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/download-audio', methods=['POST'])
def download_audio():
    """Handle audio-only download requests"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'status': 'error', 'message': 'URL is required'})
        
        # Detect platform automatically
        platform = downloader.detect_platform(url)
        
        # Start audio download
        result = downloader.download_content(url, audio_only=True)
        result['platform'] = platform
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Server error: {str(e)}'})

@app.route('/bulk-download', methods=['POST'])
def bulk_download():
    """Handle bulk download requests"""
    try:
        data = request.get_json()
        urls = data.get('urls', [])
        audio_only = data.get('audio_only', False)
        
        if not urls:
            return jsonify({'status': 'error', 'message': 'URLs list is required'})
        
        results = []
        for url in urls:
            if url.strip():
                result = downloader.download_content(url.strip(), audio_only=audio_only)
                result['url'] = url
                results.append(result)
        
        content_type = "audio" if audio_only else "video"
        return jsonify({
            'status': 'success',
            'message': f'Processed {len(results)} URLs for {content_type} download',
            'results': results
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Bulk download error: {str(e)}'})

@app.route('/download-file/<path:filepath>')
def download_file(filepath):
    """Download a specific file and delete it after download"""
    try:
        print(f"🔍 Looking for file: {filepath}")
        
        # Search for the file in all subdirectories
        actual_file_path = None
        
        # First, try to find the file directly
        for root, dirs, files in os.walk(DOWNLOAD_DIR):
            for file in files:
                if file == filepath:
                    actual_file_path = os.path.join(root, file)
                    print(f"✅ Found exact match: {actual_file_path}")
                    break
            if actual_file_path:
                break
        
        # If not found, try partial matching
        if not actual_file_path:
            print("🔍 Searching with partial matching...")
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for file in files:
                    if filepath in file or file in filepath:
                        actual_file_path = os.path.join(root, file)
                        print(f"🎯 Found partial match: {actual_file_path}")
                        break
                if actual_file_path:
                    break
        
        if not actual_file_path or not os.path.exists(actual_file_path):
            print(f"❌ File not found. Available files:")
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for file in files:
                    print(f"   - {file}")
            return jsonify({'error': f'File not found: {filepath}'}), 404
        
        print(f"📁 Final file path: {actual_file_path}")
        
        # Get the actual filename for download
        actual_filename = os.path.basename(actual_file_path)
        
        # Send file directly with proper headers
        try:
            print(f"📤 Sending file: {actual_filename}")
            
            # Delete original file after a delay
            def cleanup_after_download():
                try:
                    print(f"🧹 Starting cleanup for: {actual_file_path}")
                    
                    # Wait a bit to ensure download started
                    import time
                    time.sleep(2)
                    
                    # Delete the original file
                    if os.path.exists(actual_file_path):
                        os.remove(actual_file_path)
                        print(f"🗑️ Deleted original file: {actual_file_path}")
                    
                    # Clean up empty directories
                    parent_dir = os.path.dirname(actual_file_path)
                    while parent_dir != DOWNLOAD_DIR and os.path.exists(parent_dir):
                        try:
                            if not os.listdir(parent_dir):  # If directory is empty
                                os.rmdir(parent_dir)
                                print(f"🗂️ Removed empty directory: {parent_dir}")
                                parent_dir = os.path.dirname(parent_dir)
                            else:
                                break
                        except:
                            break
                    
                    print("✅ Cleanup completed")
                    
                except Exception as e:
                    print(f"⚠️ Cleanup error: {e}")
            
            # Schedule cleanup
            threading.Timer(5.0, cleanup_after_download).start()
            
            return send_file(
                actual_file_path, 
                as_attachment=True, 
                download_name=actual_filename,
                mimetype='application/octet-stream'
            )
            
        except Exception as e:
            print(f"❌ Failed to send file: {e}")
            return jsonify({'error': f'Failed to send file: {str(e)}'}), 500
        
    except Exception as e:
        error_msg = f'Download error: {str(e)}'
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/downloads')
def list_downloads():
    """List downloaded files"""
    try:
        print(f"📋 Listing downloads from: {DOWNLOAD_DIR}")
        items = []
        
        if os.path.exists(DOWNLOAD_DIR):
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for file in files:
                    # Skip hidden files and system files
                    if file.startswith('.') or file.endswith('.tmp') or file.endswith('.part'):
                        continue
                        
                    file_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(file_path)
                        relative_path = os.path.relpath(file_path, DOWNLOAD_DIR)
                        folder_name = os.path.basename(os.path.dirname(file_path)) if os.path.dirname(relative_path) else 'root'
                        
                        items.append({
                            'name': file,
                            'path': relative_path,
                            'size': file_size,
                            'folder': folder_name
                        })
                        print(f"📄 Found file: {file} ({file_size} bytes)")
                    except OSError as e:
                        print(f"⚠️ Skipping file {file}: {e}")
                        continue
        
        print(f"✅ Found {len(items)} downloadable files")
        return jsonify({'items': items})
        
    except Exception as e:
        error_msg = f'Error listing downloads: {str(e)}'
        print(f"❌ {error_msg}")
        return jsonify({'error': error_msg}), 500

@app.route('/debug-downloads')
def debug_downloads():
    """Debug endpoint to check downloads directory"""
    try:
        debug_info = {
            'download_dir': DOWNLOAD_DIR,
            'exists': os.path.exists(DOWNLOAD_DIR),
            'contents': []
        }
        
        if os.path.exists(DOWNLOAD_DIR):
            for root, dirs, files in os.walk(DOWNLOAD_DIR):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        debug_info['contents'].append({
                            'name': file,
                            'path': file_path,
                            'size': os.path.getsize(file_path),
                            'exists': os.path.exists(file_path)
                        })
                    except Exception as e:
                        debug_info['contents'].append({
                            'name': file,
                            'path': file_path,
                            'error': str(e)
                        })
        
        return jsonify(debug_info)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'error': f'Server error: {str(e)}'}), 500

if __name__ == '__main__':
    print("=" * 60)
    print("UNIVERSAL SOCIAL MEDIA DOWNLOADER")
    print("=" * 60)
    print("Starting server...")
    print("Supported platforms: YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, and more!")
    print("Features: Stories, Reels, Posts, Videos, Bulk downloads")
    print("Server running on: http://localhost:5000")
    print("=" * 60)
    
    # Ensure downloads directory exists
    if not os.path.exists(DOWNLOAD_DIR):
        os.makedirs(DOWNLOAD_DIR)
        print(f"✅ Created downloads directory: {DOWNLOAD_DIR}")
    
    # Test if required modules are available
    try:
        import yt_dlp
        print("✅ yt-dlp is available")
    except ImportError:
        print("❌ yt-dlp is not installed. Run: pip install yt-dlp")
    
    try:
        import instaloader
        print("✅ instaloader is available")
    except ImportError:
        print("❌ instaloader is not installed. Run: pip install instaloader")
    
    # Check FFmpeg availability
    try:
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        if result.returncode == 0:
            print("✅ FFmpeg is available - MP3 conversion supported")
        else:
            print("⚠️ FFmpeg found but not working properly")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("⚠️ FFmpeg is not installed - audio will be downloaded in original format")
        print("   To enable MP3 conversion, install FFmpeg:")
        print("   - Windows: Download from https://ffmpeg.org/download.html")
        print("   - Or using chocolatey: choco install ffmpeg")
        print("   - Or using winget: winget install ffmpeg")
    except Exception as e:
        print(f"⚠️ FFmpeg check failed: {e}")
    
    print("=" * 60)
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000)
    except Exception as e:
        print(f"❌ Failed to start server: {e}")
        print("Make sure port 5000 is not already in use")