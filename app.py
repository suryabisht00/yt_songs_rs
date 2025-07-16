from flask import Flask, request, render_template, jsonify, send_file, session
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
import uuid
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this-in-production'

# Create base downloads directory if it doesn't exist
BASE_DOWNLOAD_DIR = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(BASE_DOWNLOAD_DIR):
    os.makedirs(BASE_DOWNLOAD_DIR)

def get_user_download_dir():
    """Get or create user-specific download directory"""
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    
    user_dir = os.path.join(BASE_DOWNLOAD_DIR, session['user_id'])
    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
    
    return user_dir

def cleanup_old_user_folders():
    """Clean up user folders older than 1 hour"""
    current_time = time.time()
    for folder_name in os.listdir(BASE_DOWNLOAD_DIR):
        folder_path = os.path.join(BASE_DOWNLOAD_DIR, folder_name)
        if os.path.isdir(folder_path):
            # Check if folder is older than 2 hours (increased from 1 hour to accommodate 10-minute file retention)
            folder_age = current_time - os.path.getctime(folder_path)
            if folder_age > 7200:  # 2 hours in seconds
                try:
                    shutil.rmtree(folder_path)
                    print(f"🧹 Cleaned up old user folder: {folder_name}")
                except Exception as e:
                    print(f"⚠️ Error cleaning up folder {folder_name}: {e}")

class UniversalDownloader:
    def __init__(self):
        self.session = requests.Session()
        # Rotate user agents to bypass restrictions
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0'
        ]
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.downloaded_files = {}  # Track downloaded files for auto-deletion

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

    def schedule_file_deletion(self, file_path, delay_seconds=600):
        """Schedule a file for deletion after specified delay"""
        def delete_file():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"🗑️ Auto-deleted file after {delay_seconds}s: {os.path.basename(file_path)}")
                    
                    # Clean up empty directories up to user directory
                    parent_dir = os.path.dirname(file_path)
                    user_download_dir = get_user_download_dir()
                    
                    while parent_dir != user_download_dir and parent_dir != BASE_DOWNLOAD_DIR and os.path.exists(parent_dir):
                        try:
                            if not os.listdir(parent_dir):  # If directory is empty
                                os.rmdir(parent_dir)
                                print(f"🗂️ Removed empty directory: {os.path.basename(parent_dir)}")
                                parent_dir = os.path.dirname(parent_dir)
                            else:
                                break
                        except:
                            break
                else:
                    print(f"⚠️ File already deleted: {os.path.basename(file_path)}")
                    
                # Remove from tracking
                if file_path in self.downloaded_files:
                    del self.downloaded_files[file_path]
                    
            except Exception as e:
                print(f"❌ Error auto-deleting file {file_path}: {e}")
        
        # Schedule deletion
        timer = threading.Timer(delay_seconds, delete_file)
        timer.daemon = True
        timer.start()
        
        # Track the file and timer
        self.downloaded_files[file_path] = {
            'timer': timer,
            'created_at': datetime.now(),
            'downloaded': False,
            'auto_delete_time': datetime.now().timestamp() + delay_seconds
        }
        
        print(f"⏰ Scheduled auto-deletion for {os.path.basename(file_path)} in {delay_seconds} seconds")
    
    def mark_file_as_downloaded(self, file_path):
        """Mark a file as downloaded to prevent auto-deletion"""
        if file_path in self.downloaded_files:
            self.downloaded_files[file_path]['downloaded'] = True
            # Cancel the auto-deletion timer
            if self.downloaded_files[file_path]['timer']:
                self.downloaded_files[file_path]['timer'].cancel()
                print(f"✅ Cancelled auto-deletion for downloaded file: {os.path.basename(file_path)}")
    
    def get_file_deletion_info(self, user_download_dir):
        """Get deletion timing info for files in user directory"""
        deletion_info = []
        current_time = datetime.now().timestamp()
        
        for file_path, info in self.downloaded_files.items():
            if file_path.startswith(user_download_dir) and not info['downloaded']:
                remaining_time = max(0, info['auto_delete_time'] - current_time)
                deletion_info.append({
                    'file': os.path.basename(file_path),
                    'remaining_seconds': int(remaining_time),
                    'auto_delete_time': info['auto_delete_time']
                })
        
        return deletion_info
    
    def schedule_downloaded_files_deletion(self, path):
        """Schedule deletion for all files in the given path"""
        try:
            # Find all files in the path and schedule them for deletion
            for root, dirs, files in os.walk(path):
                for file in files:
                    # Skip hidden files and system files
                    if file.startswith('.') or file.endswith('.tmp') or file.endswith('.part'):
                        continue
                    
                    file_path = os.path.join(root, file)
                    if os.path.exists(file_path):
                        # Schedule subtitle files for immediate deletion (shorter delay)
                        file_ext = os.path.splitext(file)[1].lower()
                        if file_ext in {'.vtt', '.srt', '.ass', '.ssa', '.sub', '.idx', '.smi', '.rt', '.txt'} or file.endswith('.info.json'):
                            self.schedule_file_deletion(file_path, 30)  # 30 seconds for subtitle files
                            print(f"⏰ Scheduled subtitle file for quick deletion: {os.path.basename(file_path)}")
                        else:
                            self.schedule_file_deletion(file_path, 600)  # 10 minutes for media files
                        
        except Exception as e:
            print(f"❌ Error scheduling file deletion: {e}")
    
    def cleanup_subtitle_files(self, media_file_path):
        """Clean up subtitle files associated with a specific media file"""
        try:
            base_name = os.path.splitext(media_file_path)[0]
            directory = os.path.dirname(media_file_path)
            subtitle_extensions = {'.vtt', '.srt', '.ass', '.ssa', '.sub', '.idx', '.smi', '.rt', '.txt'}
            
            for ext in subtitle_extensions:
                subtitle_file = base_name + ext
                if os.path.exists(subtitle_file):
                    os.remove(subtitle_file)
                    print(f"🧹 Deleted subtitle file: {os.path.basename(subtitle_file)}")
            
            # Also clean up any .info.json files
            info_file = base_name + '.info.json'
            if os.path.exists(info_file):
                os.remove(info_file)
                print(f"🧹 Deleted info file: {os.path.basename(info_file)}")
            
            # Look for any files in the directory that might be related subtitle files
            if os.path.exists(directory):
                for file in os.listdir(directory):
                    file_path = os.path.join(directory, file)
                    if os.path.isfile(file_path):
                        file_ext = os.path.splitext(file)[1].lower()
                        if file_ext in subtitle_extensions and base_name in file:
                            try:
                                os.remove(file_path)
                                print(f"🧹 Deleted related subtitle file: {file}")
                            except:
                                pass
                        
        except Exception as e:
            print(f"❌ Error cleaning up subtitle files: {e}")
    
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
        """Check if FFmpeg is available - simplified for Vercel"""
        try:
            import subprocess
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=3)
            return result.returncode == 0
        except:
            return False
    
    def download_instagram_content(self, url, path, audio_only=False):
        """Download Instagram posts, reels, stories, IGTV"""
        print(f"🔄 Starting Instagram download for: {url}")
        
        # Instagram doesn't support audio extraction
        if audio_only:
            return {'status': 'error', 'message': 'Audio extraction not supported for Instagram. Instagram content is primarily visual.'}
        
        # Try multiple approaches in order of preference
        methods = [
            ("instaloader_anonymous", self._try_instaloader_anonymous),
            ("instaloader_basic", self._try_instaloader_basic),
            ("ytdlp_fallback", self._instagram_ytdlp_fallback),
            ("direct_api", self._try_direct_instagram_api)
        ]
        
        age_restricted = False
        private_content = False
        last_error_msg = None
        
        for method_name, method_func in methods:
            try:
                print(f"🔄 Trying method: {method_name}")
                result = method_func(url, path)
                
                if result['status'] == 'success':
                    print(f"✅ Success with method: {method_name}")
                    return result
                else:
                    error_msg = result.get('message', '').lower()
                    last_error_msg = result.get('message', '')
                    
                    # Track specific error types
                    if 'age-restricted' in error_msg or '18 years old' in error_msg or 'restricted video' in error_msg:
                        age_restricted = True
                    elif 'private' in error_msg or 'login' in error_msg:
                        private_content = True
                    
                    print(f"❌ Failed with method: {method_name} - {result.get('message', 'Unknown error')}")
                    
            except Exception as e:
                print(f"❌ Exception with method {method_name}: {str(e)}")
                last_error_msg = str(e)
                continue
        
        # Provide specific error messages based on what was detected
        if age_restricted:
            return {
                'status': 'error',
                'message': 'This Instagram content is age-restricted (18+). Age-restricted content requires authentication and cannot be downloaded through this service.'
            }
        elif private_content:
            return {
                'status': 'error',
                'message': 'This Instagram content is private and requires login to access. Private content cannot be downloaded through this service.'
            }
        else:
            # Generic error message with more helpful information
            return {
                'status': 'error',
                'message': f'Instagram download failed with all methods. Last error: {last_error_msg or "Unknown error"}. This may be due to: 1) Content restrictions, 2) Instagram API changes, 3) Network issues, or 4) Content not available. Please try again later or check if the content is public.'
            }
    
    def _instagram_audio_download(self, url, path):
        """Download Instagram audio using yt-dlp"""
        try:
            ffmpeg_available = self.check_ffmpeg_availability()
            
            if ffmpeg_available:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Instagram_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }],
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
                conversion_msg = "converted to MP3"
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Instagram_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
                conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
            
            print(f"🎵 Instagram audio extraction settings: FFmpeg available = {ffmpeg_available}")
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    message = f'Instagram audio downloaded successfully! ({conversion_msg})'
                    return {
                        'status': 'success',
                        'message': message,
                        'title': info.get('title', 'Instagram Audio'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'type': 'audio'
                    }
                else:
                    return {'status': 'error', 'message': 'Failed to extract Instagram audio'}
                    
        except Exception as e:
            return {'status': 'error', 'message': f'Instagram audio extraction failed: {str(e)}'}
    
    def _try_instaloader_anonymous(self, url, path):
        """Try instaloader with anonymous session and optimized settings"""
        try:
            # Create a more robust loader configuration
            loader = instaloader.Instaloader(
                dirname_pattern=path,
                filename_pattern='{profile}_{mediaid}',
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                max_connection_attempts=1,  # Reduce connection attempts
                request_timeout=15.0,
                resume_prefix=None,
                user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1'
            )
            
            # Disable verbose logging
            loader.context.log = lambda *args, **kwargs: None
            
            # Add delay to avoid rate limiting
            import time
            time.sleep(1)
            
            # Handle different URL types
            if '/stories/' in url:
                return self._download_instagram_stories(loader, url, path)
            elif '/reel/' in url or '/p/' in url or '/tv/' in url:
                return self._download_instagram_post_robust(loader, url, path)
            else:
                return self._download_instagram_profile(loader, url, path)
                
        except Exception as e:
            return {'status': 'error', 'message': f'Anonymous instaloader failed: {str(e)}'}
    
    def _try_instaloader_basic(self, url, path):
        """Try basic instaloader with minimal configuration"""
        try:
            loader = instaloader.Instaloader(
                dirname_pattern=path,
                filename_pattern='{mediaid}',
                download_videos=True,
                save_metadata=False,
                max_connection_attempts=1,
                request_timeout=10.0
            )
            
            # Disable all logging
            loader.context.log = lambda *args, **kwargs: None
            
            shortcode = self.extract_instagram_shortcode(url)
            if not shortcode:
                return {'status': 'error', 'message': 'Could not extract post ID from URL'}
            
            # Simple direct download without retries
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            loader.download_post(post, target="instagram_download")
            
            return {
                'status': 'success',
                'message': 'Instagram content downloaded successfully with basic method!',
                'type': 'basic'
            }
            
        except Exception as e:
            return {'status': 'error', 'message': f'Basic instaloader failed: {str(e)}'}
    
    def _download_instagram_post_robust(self, loader, url, path):
        """Download Instagram post with enhanced error handling"""
        try:
            shortcode = self.extract_instagram_shortcode(url)
            if not shortcode:
                return {'status': 'error', 'message': 'Could not extract post ID from URL'}
            
            print(f"📱 Extracted shortcode: {shortcode}")
            
            # Single attempt with proper timeout handling for Windows
            try:
                # Use threading timeout instead of signal for Windows compatibility
                import threading
                import time
                
                result = {'post': None, 'error': None}
                
                def fetch_post():
                    try:
                        result['post'] = instaloader.Post.from_shortcode(loader.context, shortcode)
                    except Exception as e:
                        result['error'] = e
                
                # Start the fetch in a separate thread
                thread = threading.Thread(target=fetch_post)
                thread.daemon = True
                thread.start()
                thread.join(timeout=30)  # 30 second timeout
                
                if thread.is_alive():
                    return {'status': 'error', 'message': 'Post fetching timed out - content may be private or unavailable'}
                
                if result['error']:
                    raise result['error']
                
                if not result['post']:
                    return {'status': 'error', 'message': 'Failed to fetch post data'}
                
                post = result['post']
                
                # Download the post
                loader.download_post(post, target=post.owner_username)
                
                content_type = 'reel' if post.is_video else 'post'
                if hasattr(post, 'typename') and post.typename == 'GraphSidecar':
                    content_type = 'carousel'
                
                return {
                    'status': 'success',
                    'message': f'Instagram {content_type} downloaded successfully!',
                    'username': post.owner_username,
                    'type': content_type
                }
                
            except Exception as e:
                error_msg = str(e).lower()
                if 'private' in error_msg or 'login' in error_msg:
                    return {'status': 'error', 'message': 'This Instagram content appears to be private or requires login'}
                elif 'not found' in error_msg or '404' in error_msg:
                    return {'status': 'error', 'message': 'Instagram post not found - it may have been deleted'}
                elif 'rate limit' in error_msg or 'too many requests' in error_msg:
                    return {'status': 'error', 'message': 'Instagram rate limit exceeded - please wait and try again'}
                elif 'forbidden' in error_msg or '403' in error_msg:
                    return {'status': 'error', 'message': 'Instagram access forbidden - content may be restricted or private'}
                else:
                    return {'status': 'error', 'message': f'Post download failed: {str(e)}'}
            
        except Exception as e:
            return {'status': 'error', 'message': f'Robust post download failed: {str(e)}'}
    
    def _instagram_ytdlp_fallback(self, url, path):
        """Enhanced yt-dlp fallback with better error handling"""
        try:
            print("🔄 Trying enhanced yt-dlp fallback for Instagram...")
            
            # Multiple yt-dlp configurations to try
            configs = [
                {
                    'name': 'basic',
                    'opts': {
                        'outtmpl': os.path.join(path, 'Instagram_%(title)s.%(ext)s'),
                        'format': 'best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'extract_flat': False,
                    }
                },
                {
                    'name': 'mobile',
                    'opts': {
                        'outtmpl': os.path.join(path, 'Instagram_%(id)s.%(ext)s'),
                        'format': 'best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15'
                        }
                    }
                },
                {
                    'name': 'age_restricted',
                    'opts': {
                        'outtmpl': os.path.join(path, 'Instagram_%(id)s.%(ext)s'),
                        'format': 'best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'age_limit': 18,
                        'http_headers': {
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                        }
                    }
                },
                {
                    'name': 'simple',
                    'opts': {
                        'outtmpl': os.path.join(path, 'Instagram_content.%(ext)s'),
                        'format': 'worst',
                        'ignoreerrors': True,
                        'no_warnings': True,
                        'retries': 1
                    }
                }
            ]
            
            last_error = None
            
            for config in configs:
                try:
                    print(f"🔄 Trying yt-dlp config: {config['name']}")
                    
                    with yt_dlp.YoutubeDL(config['opts']) as ydl:
                        info = ydl.extract_info(url, download=True)
                        
                        if info:
                            return {
                                'status': 'success',
                                'message': f'Instagram content downloaded successfully using yt-dlp ({config["name"]} config)!',
                                'title': info.get('title', 'Instagram Content'),
                                'uploader': info.get('uploader', 'Unknown'),
                                'type': 'ytdlp_fallback'
                            }
                            
                except Exception as e:
                    error_msg = str(e).lower()
                    last_error = str(e)
                    print(f"❌ yt-dlp config {config['name']} failed: {str(e)}")
                    
                    # Check for specific error types
                    if 'restricted video' in error_msg or '18 years old' in error_msg:
                        return {
                            'status': 'error',
                            'message': 'This Instagram content is age-restricted (18+). Age-restricted content cannot be downloaded without authentication.'
                        }
                    elif 'private' in error_msg or 'login' in error_msg:
                        return {
                            'status': 'error',
                            'message': 'This Instagram content is private and requires login to access.'
                        }
                    elif 'not found' in error_msg or '404' in error_msg:
                        return {
                            'status': 'error',
                            'message': 'Instagram content not found - it may have been deleted or made private.'
                        }
                    
                    continue
            
            # If all configs failed, provide specific error message
            if last_error:
                if 'restricted video' in last_error.lower() or '18 years old' in last_error.lower():
                    return {
                        'status': 'error',
                        'message': 'This Instagram content is age-restricted (18+) and cannot be downloaded without authentication.'
                    }
                elif 'private' in last_error.lower():
                    return {
                        'status': 'error',
                        'message': 'This Instagram content is private and requires login to access.'
                    }
            
            return {
                'status': 'error',
                'message': 'All yt-dlp configurations failed for Instagram content'
            }
                
        except Exception as e:
            return {
                'status': 'error', 
                'message': f'yt-dlp fallback completely failed: {str(e)}'
            }
    
    def _try_direct_instagram_api(self, url, path):
        """Try direct Instagram API approach as last resort"""
        try:
            print("🔄 Attempting direct Instagram API method...")
            
            # This is a basic implementation - in production, you'd want more sophisticated API handling
            shortcode = self.extract_instagram_shortcode(url)
            if not shortcode:
                return {'status': 'error', 'message': 'Could not extract post ID'}
            
            # Try to get basic post info without full download
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Mobile/15E148 Safari/604.1',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = self.session.get(f"https://www.instagram.com/p/{shortcode}/", headers=headers, timeout=10)
            
            if response.status_code == 200:
                return {
                    'status': 'error',
                    'message': 'Instagram post is accessible but download failed. This content may require special handling or may be protected.'
                }
            else:
                return {
                    'status': 'error',
                    'message': f'Instagram post not accessible (HTTP {response.status_code})'
                }
                
        except Exception as e:
            return {'status': 'error', 'message': f'Direct API method failed: {str(e)}'}
    
    def _download_instagram_stories(self, loader, url, path):
        """Download Instagram stories with error handling"""
        try:
            username = self.extract_instagram_username(url)
            if not username:
                return {'status': 'error', 'message': 'Could not extract username from URL'}
            
            profile = instaloader.Profile.from_username(loader.context, username)
            stories_downloaded = 0
            
            for story in loader.get_stories([profile.userid]):
                for item in story.get_items():
                    try:
                        loader.download_storyitem(item, target=username)
                        stories_downloaded += 1
                    except Exception as e:
                        print(f"⚠️ Failed to download story item: {e}")
                        continue
            
            if stories_downloaded > 0:
                return {
                    'status': 'success',
                    'message': f'Downloaded {stories_downloaded} Instagram stories for {username}',
                    'type': 'stories'
                }
            else:
                return {'status': 'error', 'message': 'No stories found or all downloads failed'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Stories download failed: {str(e)}'}
    
    def _download_instagram_profile(self, loader, url, path):
        """Download Instagram profile posts with error handling"""
        try:
            username = self.extract_instagram_username(url)
            if not username:
                return {'status': 'error', 'message': 'Could not extract username from URL'}
            
            profile = instaloader.Profile.from_username(loader.context, username)
            
            count = 0
            errors = 0
            max_posts = 5  # Reduced to avoid rate limiting
            
            for post in profile.get_posts():
                if count >= max_posts:
                    break
                try:
                    loader.download_post(post, target=username)
                    count += 1
                except Exception as e:
                    print(f"⚠️ Failed to download post {count + errors + 1}: {e}")
                    errors += 1
                    if errors > 3:  # Stop if too many errors
                        break
            
            if count > 0:
                return {
                    'status': 'success',
                    'message': f'Downloaded {count} posts from {username} (with {errors} errors)',
                    'type': 'profile'
                }
            else:
                return {'status': 'error', 'message': 'No posts could be downloaded'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Profile download failed: {str(e)}'}
    
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
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'ignoreerrors': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Twitter audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'writesubtitles': True,
                    'ignoreerrors': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                content_type = 'audio' if audio_only else 'tweet'
                message = f'Twitter {content_type} downloaded successfully!'
                if audio_only:
                    message += f' ({conversion_msg})'
                
                return {
                    'status': 'success',
                    'message': message,
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
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Facebook_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'ignoreerrors': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Facebook_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Facebook audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Facebook_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                content_type = 'audio' if audio_only else 'video'
                message = f'Facebook {content_type} downloaded successfully!'
                if audio_only:
                    message += f' ({conversion_msg})'
                
                return {
                    'status': 'success',
                    'message': message,
                    'title': info.get('title', 'Facebook Content'),
                    'uploader': info.get('uploader', 'Unknown'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Facebook error: {str(e)}'}
    
    def download_generic_content(self, url, path, audio_only=False):
        """Download from other platforms with bypass techniques"""
        try:
            base_opts = self.get_bypass_options(url)
            
            if audio_only:
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'ignoreerrors': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Reddit audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                    'ignoreerrors': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                content_type = 'audio' if audio_only else 'post'
                message = f'Reddit {content_type} downloaded successfully!'
                if audio_only:
                    message += f' ({conversion_msg})'
                
                return {
                    'status': 'success',
                    'message': message,
                    'title': info.get('title', 'Reddit Post'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Platform download error: {str(e)}'}
    
    def download_instagram_content(self, url, path, audio_only=False):
        """Download Instagram content with Vercel optimization"""
        try:
            if audio_only:
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'ignoreerrors': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Generic audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                content_type = 'audio' if audio_only else 'media'
                message = f'{content_type.title()} downloaded successfully!'
                if audio_only:
                    message += f' ({conversion_msg})'
                
                return {
                    'status': 'success',
                    'message': message,
                    'title': info.get('title', 'Unknown'),
                    'extractor': info.get('extractor', 'Unknown'),
                    'type': content_type
                }
        except Exception as e:
            return {'status': 'error', 'message': f'Instagram error: {str(e)}'}
    
    def download_content(self, url, custom_path=None, audio_only=False):
        """Main download function"""
        path = custom_path or get_user_download_dir()
        platform = self.detect_platform(url)
        
        # For direct downloads without folder creation
        try:
            if platform == 'youtube':
                result = self.download_youtube_content(url, path, audio_only)
            elif platform == 'instagram':
                if audio_only:
                    return {'status': 'error', 'message': 'Audio extraction not supported for Instagram. Instagram content is primarily visual.'}
                result = self.download_instagram_content(url, path, audio_only)
            elif platform == 'tiktok':
                result = self.download_tiktok_content(url, path, audio_only)
            elif platform == 'twitter':
                result = self.download_twitter_content(url, path, audio_only)
            elif platform == 'facebook':
                result = self.download_facebook_content(url, path, audio_only)
            elif platform == 'reddit':
                result = self.download_reddit_content(url, path, audio_only)
            else:
                # Try generic download for other platforms
                result = self.download_generic_content(url, path, audio_only)
            
            # Schedule auto-deletion for downloaded files and add timer info
            if result.get('status') == 'success':
                self.schedule_downloaded_files_deletion(path)
                # Add deletion timing info to response
                result['deletion_info'] = self.get_file_deletion_info(path)
                result['auto_delete_seconds'] = 600
            
            return result
                
        except Exception as e:
            return {'status': 'error', 'message': f'Unexpected error: {str(e)}'}

# Initialize downloader
downloader = UniversalDownloader()

@app.before_request
def before_request():
    """Run before each request"""
    # Clean up old user folders periodically
    if hasattr(app, 'last_cleanup'):
        if time.time() - app.last_cleanup > 7200:  # Clean up every 2 hours
            cleanup_old_user_folders()
            app.last_cleanup = time.time()
    else:
        app.last_cleanup = time.time()

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    """Handle download requests"""
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
            
        url = data.get('url', '').strip()
        audio_only = data.get('audio_only', False)
        
        if not url:
            return jsonify({'status': 'error', 'message': 'URL is required'})
        
        platform = downloader.detect_platform(url)
        result = downloader.download_content(url, audio_only=audio_only)
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
        for url in urls[:5]:  # Limit to 5 URLs for Vercel
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
        
        # Get user-specific download directory
        user_download_dir = get_user_download_dir()
        
        # Search for the file in user's directory only
        actual_file_path = None
        
        # First, try to find the file directly
        for root, dirs, files in os.walk(user_download_dir):
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
            for root, dirs, files in os.walk(user_download_dir):
                for file in files:
                    if filepath in file or file in filepath:
                        actual_file_path = os.path.join(root, file)
                        print(f"🎯 Found partial match: {actual_file_path}")
                        break
                if actual_file_path:
                    break
        
        if not actual_file_path or not os.path.exists(actual_file_path):
            print(f"❌ File not found in user directory. Available files:")
            for root, dirs, files in os.walk(user_download_dir):
                for file in files:
                    print(f"   - {file}")
            return jsonify({'error': f'File not found: {filepath}'}), 404
        
        print(f"📁 Final file path: {actual_file_path}")
        
        # Mark file as downloaded to prevent auto-deletion
        downloader.mark_file_as_downloaded(actual_file_path)
        
        # Get the actual filename for download
        actual_filename = os.path.basename(actual_file_path)
        
        # Send file directly with proper headers
        try:
            print(f"📤 Sending file: {actual_filename}")
            
            # Delete original file and cleanup folders after download
            def cleanup_after_download():
                try:
                    print(f"🧹 Starting cleanup for downloaded file: {actual_file_path}")
                    
                    # Wait a bit to ensure download completed
                    import time
                    time.sleep(2)
                    
                    # Clean up subtitle files first
                    downloader.cleanup_subtitle_files(actual_file_path)
                    
                    # Delete the original file
                    if os.path.exists(actual_file_path):
                        os.remove(actual_file_path)
                        print(f"🗑️ Deleted downloaded file: {actual_file_path}")
                    
                    # Clean up ALL subtitle files and metadata files in the directory
                    parent_dir = os.path.dirname(actual_file_path)
                    if os.path.exists(parent_dir):
                        excluded_extensions = {'.vtt', '.srt', '.ass', '.ssa', '.sub', '.idx', '.smi', '.rt', '.txt',
                                             '.info.json', '.description', '.annotations.xml', '.thumbnail'}
                        
                        for file in os.listdir(parent_dir):
                            file_path = os.path.join(parent_dir, file)
                            if os.path.isfile(file_path):
                                file_ext = os.path.splitext(file)[1].lower()
                                if file_ext in excluded_extensions or file.endswith('.info.json'):
                                    try:
                                        os.remove(file_path)
                                        print(f"🧹 Deleted subtitle/metadata file: {file}")
                                    except:
                                        pass
                    
                    # Clean up empty directories up to user directory
                    while parent_dir != user_download_dir and parent_dir != BASE_DOWNLOAD_DIR and os.path.exists(parent_dir):
                        try:
                            if not os.listdir(parent_dir):  # If directory is empty
                                os.rmdir(parent_dir)
                                print(f"🗂️ Removed empty directory: {os.path.basename(parent_dir)}")
                                parent_dir = os.path.dirname(parent_dir)
                            else:
                                break
                        except:
                            break
                    
                    print("✅ Download cleanup completed")
                    
                except Exception as e:
                    print(f"⚠️ Download cleanup error: {e}")
            
            # Schedule cleanup after file is sent
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
    """List downloaded files for current user"""
    try:
        user_download_dir = get_user_download_dir()
        print(f"📋 Listing downloads from user directory: {user_download_dir}")
        items = []
        
        # Define allowed media file extensions
        allowed_extensions = {
            # Video formats
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.m2ts',
            # Audio formats
            '.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma', '.opus', '.aiff', '.au',
            # Image formats (for Instagram posts)
            '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.svg'
        }
        
        # Define subtitle and metadata files to exclude
        excluded_extensions = {
            '.vtt', '.srt', '.ass', '.ssa', '.sub', '.idx', '.smi', '.rt', '.txt',
            '.info.json', '.description', '.annotations.xml', '.thumbnail'
        }
        
        if os.path.exists(user_download_dir):
            for root, dirs, files in os.walk(user_download_dir):
                for file in files:
                    # Skip hidden files and system files
                    if file.startswith('.') or file.endswith('.tmp') or file.endswith('.part'):
                        continue
                    
                    # Get file extension
                    file_ext = os.path.splitext(file)[1].lower()
                    
                    # Skip subtitle files and other excluded files
                    if file_ext in excluded_extensions:
                        print(f"⏭️ Skipping excluded file: {file} (extension: {file_ext})")
                        continue
                    
                    # Only include media files
                    if file_ext not in allowed_extensions:
                        print(f"⏭️ Skipping non-media file: {file} (extension: {file_ext})")
                        continue
                        
                    file_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(file_path)
                        relative_path = os.path.relpath(file_path, user_download_dir)
                        folder_name = os.path.basename(os.path.dirname(file_path)) if os.path.dirname(relative_path) else 'root'
                        
                        items.append({
                            'name': file,
                            'path': relative_path,
                            'size': file_size,
                            'folder': folder_name,
                            'type': 'video' if file_ext in ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.m2ts'] else 'audio' if file_ext in ['.mp3', '.wav', '.aac', '.ogg', '.flac', '.m4a', '.wma', '.opus', '.aiff', '.au'] else 'image'
                        })
                        print(f"📄 Found media file: {file} ({file_size} bytes)")
                    except OSError as e:
                        print(f"⚠️ Skipping file {file}: {e}")
                        continue
        
        # Add deletion timing info
        deletion_info = downloader.get_file_deletion_info(user_download_dir)
        
        print(f"✅ Found {len(items)} downloadable media files for user")
        return jsonify({
            'items': items,
            'deletion_info': deletion_info
        })
        
    except Exception as e:
        return jsonify({'error': f'Error listing downloads: {str(e)}'})

@app.route('/cleanup-files', methods=['POST'])
def cleanup_files():
    """Manual cleanup endpoint to remove undownloaded files for current user"""
    try:
        user_download_dir = get_user_download_dir()
        files_to_cleanup = []
        
        # Get all files in user directory
        for root, dirs, files in os.walk(user_download_dir):
            for file in files:
                file_path = os.path.join(root, file)
                if file_path in downloader.downloaded_files:
                    if not downloader.downloaded_files[file_path]['downloaded']:
                        files_to_cleanup.append(file_path)
        
        cleanup_count = 0
        
        for file_path in files_to_cleanup:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    cleanup_count += 1
                    print(f"🧹 Manually cleaned up: {os.path.basename(file_path)}")
                    
                    # Remove from tracking
                    if file_path in downloader.downloaded_files:
                        del downloader.downloaded_files[file_path]
                        
            except Exception as e:
                print(f"❌ Error cleaning up {file_path}: {e}")
        
        # Clean up ALL subtitle files and metadata files regardless of tracking
        excluded_extensions = {'.vtt', '.srt', '.ass', '.ssa', '.sub', '.idx', '.smi', '.rt', '.txt',
                             '.info.json', '.description', '.annotations.xml', '.thumbnail'}
        
        for root, dirs, files in os.walk(user_download_dir):
            for file in files:
                file_ext = os.path.splitext(file)[1].lower()
                if file_ext in excluded_extensions or file.endswith('.info.json'):
                    file_path = os.path.join(root, file)
                    try:
                        if os.path.exists(file_path):
                            os.remove(file_path)
                            cleanup_count += 1
                            print(f"🧹 Cleaned up subtitle/metadata file: {os.path.basename(file_path)}")
                    except Exception as e:
                        print(f"❌ Error cleaning up subtitle/metadata file {file_path}: {e}")
        
        # Clean up empty directories
        for root, dirs, files in os.walk(user_download_dir, topdown=False):
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                try:
                    if os.path.exists(dir_path) and not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        print(f"🗂️ Removed empty directory: {dir}")
                except Exception as e:
                    print(f"❌ Error removing empty directory {dir_path}: {e}")
        
        return jsonify({
            'status': 'success',
            'message': f'Cleaned up {cleanup_count} files (including subtitle and metadata files)',
            'cleaned_count': cleanup_count
        })
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Cleanup error: {str(e)}'}), 500

@app.route('/clear-downloads', methods=['POST'])
def clear_downloads():
    """Clear all downloads for current user"""
    try:
        user_download_dir = get_user_download_dir()
        files_removed = 0
        dirs_removed = 0
        
        if os.path.exists(user_download_dir):
            # Cancel any pending auto-deletion timers for this user
            user_files = [f for f in downloader.downloaded_files.keys() if f.startswith(user_download_dir)]
            for file_path in user_files:
                if file_path in downloader.downloaded_files:
                    timer = downloader.downloaded_files[file_path].get('timer')
                    if timer:
                        timer.cancel()
                        print(f"⏰ Cancelled auto-deletion timer for: {os.path.basename(file_path)}")
                    del downloader.downloaded_files[file_path]
            
            # Remove all files and subdirectories
            for root, dirs, files in os.walk(user_download_dir, topdown=False):
                # Remove all files first
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        os.remove(file_path)
                        files_removed += 1
                        print(f"🗑️ Removed file: {file}")
                    except Exception as e:
                        print(f"❌ Error removing file {file}: {e}")
                
                # Remove all directories (from bottom up)
                for dir in dirs:
                    dir_path = os.path.join(root, dir)
                    try:
                        if os.path.exists(dir_path) and not os.listdir(dir_path):  # Only remove if empty
                            os.rmdir(dir_path)
                            dirs_removed += 1
                            print(f"🗂️ Removed empty directory: {dir}")
                    except Exception as e:
                        print(f"❌ Error removing directory {dir}: {e}")
            
            # Finally, try to remove the user's main download directory if it's empty
            try:
                if os.path.exists(user_download_dir) and not os.listdir(user_download_dir):
                    os.rmdir(user_download_dir)
                    dirs_removed += 1
                    print(f"🗂️ Removed empty user download directory: {os.path.basename(user_download_dir)}")
            except Exception as e:
                print(f"❌ Error removing user directory: {e}")
            
            return jsonify({
                'status': 'success',
                'message': f'All downloads cleared successfully! Removed {files_removed} files and {dirs_removed} directories.',
                'files_removed': files_removed,
                'dirs_removed': dirs_removed
            })
        else:
            return jsonify({
                'status': 'success',
                'message': 'No downloads to clear'
            })
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Clear error: {str(e)}'}), 500

# Vercel entry point
if __name__ == '__main__':
    print("=" * 60)
    print("UNIVERSAL SOCIAL MEDIA DOWNLOADER")
    print("=" * 60)
    print("Starting server...")
    print("Supported platforms: YouTube, Instagram, TikTok, Twitter/X, Facebook, Reddit, and more!")
    print("Features: Stories, Reels, Posts, Videos, Bulk downloads")
    print("Multi-user support with isolated download folders")
    print("Server running on: http://localhost:5000")
    print("=" * 60)
    
    # Ensure downloads directory exists
    if not os.path.exists(BASE_DOWNLOAD_DIR):
        os.makedirs(BASE_DOWNLOAD_DIR)
        print(f"✅ Created downloads directory: {BASE_DOWNLOAD_DIR}")
    
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