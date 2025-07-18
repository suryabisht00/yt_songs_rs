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
        
        # Add Render-specific configuration
        self.is_render = os.getenv('RENDER_EXTERNAL_HOSTNAME') is not None
        if self.is_render:
            self.setup_render_environment()
    
    def setup_render_environment(self):
        """Setup environment for Render deployment"""
        # Set up Chrome/Chromium for Render
        os.environ['CHROME_BIN'] = '/usr/bin/chromium-browser'
        os.environ['DISPLAY'] = ':0'
        
        # Update user agents for better compatibility
        self.user_agents = [
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0',
            'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/121.0'
        ]
        
        # Configure session for Render
        self.session.headers.update({
            'User-Agent': self.user_agents[0],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        print("🚀 Render environment configured")

    def check_ffmpeg_availability(self):
        """Check if FFmpeg is available for audio conversion"""
        try:
            import subprocess
            result = subprocess.run(['ffmpeg', '-version'], 
                                  capture_output=True, 
                                  text=True, 
                                  timeout=5)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            return False
        except Exception as e:
            print(f"⚠️ FFmpeg check error: {e}")
            return False

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
        """Download YouTube videos, shorts, playlists with enhanced error handling"""
        try:
            # Enhanced options for Render environment
            base_opts = {
                'outtmpl': os.path.join(path, '%(uploader)s - %(title)s.%(ext)s'),
                'writesubtitles': False,
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 30,
                'retries': 3,
                'fragment_retries': 3,
                'extractor_retries': 3,
                'http_chunk_size': 10485760,
            }
            
            # Add Render-specific options
            if self.is_render:
                base_opts.update({
                    'socket_timeout': 60,
                    'retries': 5,
                    'geo_bypass': True,
                    'geo_bypass_country': 'US',
                    'http_headers': {
                        'User-Agent': self.user_agents[0],
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Connection': 'keep-alive'
                    }
                })
            
            if audio_only:
                ffmpeg_available = self.check_ffmpeg_availability()
                
                if ffmpeg_available:
                    ydl_opts = {**base_opts, 'format': 'bestaudio/best'}
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {**base_opts, 'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best'}
                    conversion_msg = "in original format"
            else:
                ydl_opts = {**base_opts, 'format': 'best[height<=1080]/best'}
                ydl_opts['writesubtitles'] = True
                ydl_opts['writeautomaticsub'] = True
                ydl_opts['subtitleslangs'] = ['en']
            
            print(f"🎵 Audio extraction settings: FFmpeg available = {ffmpeg_available if audio_only else 'N/A'}")
            
            # Enhanced error handling for YouTube
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    # First, try to extract info without downloading to check availability
                    try:
                        info = ydl.extract_info(url, download=False)
                        if not info:
                            return {'status': 'error', 'message': 'Failed to extract video information. The video may be unavailable, private, or deleted.'}
                    except Exception as info_error:
                        error_msg = str(info_error).lower()
                        print(f"❌ YouTube info extraction error: {info_error}")
                        
                        # Enhanced error detection
                        if any(keyword in error_msg for keyword in ['unavailable', "isn't available", 'not available']):
                            return {'status': 'error', 'message': 'This YouTube video is not available. It may have been removed, made private, or is restricted in your region.'}
                        elif any(keyword in error_msg for keyword in ['private', 'requires sign', 'sign in']):
                            return {'status': 'error', 'message': 'This YouTube video is private or requires sign-in to access.'}
                        elif any(keyword in error_msg for keyword in ['age-restricted', 'age restricted', 'confirm your age']):
                            return {'status': 'error', 'message': 'This YouTube video is age-restricted and cannot be downloaded without authentication.'}
                        elif any(keyword in error_msg for keyword in ['geo', 'country', 'region', 'blocked']):
                            return {'status': 'error', 'message': 'This YouTube video is geo-blocked and not available in the server region.'}
                        elif any(keyword in error_msg for keyword in ['copyright', 'removed', 'violated']):
                            return {'status': 'error', 'message': 'This YouTube video has been removed due to copyright or policy violations.'}
                        elif 'live' in error_msg and 'stream' in error_msg:
                            return {'status': 'error', 'message': 'Live streams cannot be downloaded. Please wait until the stream ends.'}
                        elif any(keyword in error_msg for keyword in ['format', 'no suitable']):
                            return {'status': 'error', 'message': 'No suitable video format found for download.'}
                        elif any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
                            return {'status': 'error', 'message': 'Network timeout or connection error. Please try again later.'}
                        else:
                            return {'status': 'error', 'message': f'YouTube video unavailable: {str(info_error)}'}
                    
                    # Now proceed with download
                    info = ydl.extract_info(url, download=True)
                    
                    if not info:
                        return {'status': 'error', 'message': 'Download failed. The video may have become unavailable during download.'}
                    
                    content_type = 'audio' if audio_only else 'video'
                    
                    if 'entries' in info and isinstance(info['entries'], list) and info['entries']:
                        # Filter out None entries
                        valid_entries = [entry for entry in info['entries'] if entry is not None]
                        if not valid_entries:
                            return {'status': 'error', 'message': 'No valid videos found in the playlist'}
                        titles = [entry.get('title', 'Unknown') for entry in valid_entries]
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
                error_msg = str(e).lower()
                print(f"❌ YouTube download error: {e}")
                
                # Enhanced error messages
                if any(keyword in error_msg for keyword in ['unavailable', "isn't available", 'not available']):
                    return {'status': 'error', 'message': 'This YouTube video is not available. It may have been removed, made private, or is restricted in your region.'}
                elif any(keyword in error_msg for keyword in ['private', 'requires sign', 'sign in']):
                    return {'status': 'error', 'message': 'This YouTube video is private or requires sign-in to access.'}
                elif any(keyword in error_msg for keyword in ['age-restricted', 'age restricted', 'confirm your age']):
                    return {'status': 'error', 'message': 'This YouTube video is age-restricted and cannot be downloaded without authentication.'}
                elif any(keyword in error_msg for keyword in ['geo', 'country', 'region', 'blocked']):
                    return {'status': 'error', 'message': 'This YouTube video is geo-blocked and not available in the server region.'}
                elif any(keyword in error_msg for keyword in ['copyright', 'removed', 'violated']):
                    return {'status': 'error', 'message': 'This YouTube video has been removed due to copyright or policy violations.'}
                elif 'live' in error_msg and 'stream' in error_msg:
                    return {'status': 'error', 'message': 'Live streams cannot be downloaded. Please wait until the stream ends.'}
                elif any(keyword in error_msg for keyword in ['format', 'no suitable']):
                    return {'status': 'error', 'message': 'No suitable video format found for download.'}
                elif any(keyword in error_msg for keyword in ['timeout', 'connection', 'network']):
                    return {'status': 'error', 'message': 'Network timeout or connection error. Please try again later.'}
                else:
                    return {'status': 'error', 'message': f'YouTube download failed: {str(e)}'}
                    
        except Exception as e:
            return {'status': 'error', 'message': f'YouTube download failed: {str(e)}'}

    def download_instagram_content(self, url, path, audio_only=False):
        """Download Instagram posts with enhanced Render compatibility"""
        print(f"🔄 Starting Instagram download for: {url}")
        
        if audio_only:
            return {'status': 'error', 'message': 'Audio extraction not supported for Instagram. Instagram content is primarily visual.'}
        
        # Enhanced methods for Render
        methods = [
            ("ytdlp_enhanced", self._instagram_ytdlp_enhanced),
            ("instaloader_render", self._try_instaloader_render),
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
    
    def _instagram_ytdlp_enhanced(self, url, path):
        """Enhanced yt-dlp for Instagram with better Render compatibility"""
        try:
            print("🔄 Trying enhanced yt-dlp for Instagram on Render...")
            
            # Render-optimized configuration
            ydl_opts = {
                'outtmpl': os.path.join(path, 'Instagram_%(id)s.%(ext)s'),
                'format': 'best',
                'ignoreerrors': True,
                'no_warnings': True,
                'socket_timeout': 60,
                'retries': 5,
                'fragment_retries': 5,
                'extractor_retries': 5,
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if info:
                    return {
                        'status': 'success',
                        'message': 'Instagram content downloaded successfully with enhanced method!',
                        'title': info.get('title', 'Instagram Content'),
                        'uploader': info.get('uploader', 'Unknown'),
                        'type': 'enhanced'
                    }
                else:
                    return {'status': 'error', 'message': 'Failed to extract Instagram content with enhanced method'}
                    
        except Exception as e:
            return {'status': 'error', 'message': f'Enhanced Instagram download failed: {str(e)}'}
    
    def _try_instaloader_render(self, url, path):
        """Render-optimized instaloader method"""
        try:
            print("🔄 Trying Render-optimized instaloader...")
            
            # Render-specific configuration
            loader = instaloader.Instaloader(
                dirname_pattern=path,
                filename_pattern='{mediaid}',
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                max_connection_attempts=3,
                request_timeout=30.0,
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            # Disable verbose logging
            loader.context.log = lambda *args, **kwargs: None
            
            # Add longer delay for Render
            import time
            time.sleep(2)
            
            shortcode = self.extract_instagram_shortcode(url)
            if not shortcode:
                return {'status': 'error', 'message': 'Could not extract post ID from URL'}
            
            # Use timeout for Render
            import threading
            result = {'post': None, 'error': None}
            
            def fetch_post():
                try:
                    result['post'] = instaloader.Post.from_shortcode(loader.context, shortcode)
                except Exception as e:
                    result['error'] = e
            
            thread = threading.Thread(target=fetch_post)
            thread.daemon = True
            thread.start()
            thread.join(timeout=45)  # Longer timeout for Render
            
            if thread.is_alive():
                return {'status': 'error', 'message': 'Post fetching timed out on Render - content may be private or unavailable'}
            
            if result['error']:
                raise result['error']
            
            if not result['post']:
                return {'status': 'error', 'message': 'Failed to fetch post data on Render'}
            
            post = result['post']
            loader.download_post(post, target=post.owner_username)
            
            return {
                'status': 'success',
                'message': 'Instagram content downloaded successfully with Render-optimized method!',
                'username': post.owner_username,
                'type': 'render_optimized'
            }
            
        except Exception as e:
            return {'status': 'error', 'message': f'Render-optimized instaloader failed: {str(e)}'}

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
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'TikTok_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'TikTok_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if info is None
                if not info:
                    return {'status': 'error', 'message': 'Failed to extract TikTok video information. The video may be private, deleted, or unavailable.'}
                
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
            error_msg = str(e)
            if 'private' in error_msg.lower():
                return {'status': 'error', 'message': 'This TikTok video is private and cannot be downloaded.'}
            elif 'unavailable' in error_msg.lower():
                return {'status': 'error', 'message': 'This TikTok video is unavailable or has been deleted.'}
            else:
                return {'status': 'error', 'message': f'TikTok download failed: {error_msg}'}
    
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
                        'no_warnings': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Twitter audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Twitter_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'writesubtitles': True,
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if info is None
                if not info:
                    return {'status': 'error', 'message': 'Failed to extract Twitter content. The tweet may be private, deleted, or contain no media.'}
                
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
            error_msg = str(e)
            if 'private' in error_msg.lower():
                return {'status': 'error', 'message': 'This Twitter content is private and cannot be downloaded.'}
            elif 'unavailable' in error_msg.lower():
                return {'status': 'error', 'message': 'This Twitter content is unavailable or has been deleted.'}
            else:
                return {'status': 'error', 'message': f'Twitter download failed: {error_msg}'}
    
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
                        'no_warnings': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Facebook_%(uploader)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Facebook audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Facebook_%(uploader)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if info is None
                if not info:
                    return {'status': 'error', 'message': 'Failed to extract Facebook content. The post may be private, deleted, or unavailable.'}
                
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
            error_msg = str(e)
            if 'private' in error_msg.lower():
                return {'status': 'error', 'message': 'This Facebook content is private and cannot be downloaded.'}
            elif 'unavailable' in error_msg.lower():
                return {'status': 'error', 'message': 'This Facebook content is unavailable or has been deleted.'}
            else:
                return {'status': 'error', 'message': f'Facebook download failed: {error_msg}'}
    
    def download_generic_content(self, url, path, audio_only=False):
        """Download from other platforms with bypass techniques"""
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
                        'no_warnings': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
                
                print(f"🎵 Generic audio extraction settings: FFmpeg available = {ffmpeg_available}")
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(extractor)s_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if info is None
                if not info:
                    return {'status': 'error', 'message': 'Failed to extract content from this platform. The content may be private, deleted, or not supported.'}
                
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
            error_msg = str(e)
            if 'private' in error_msg.lower():
                return {'status': 'error', 'message': 'This content is private and cannot be downloaded.'}
            elif 'unavailable' in error_msg.lower():
                return {'status': 'error', 'message': 'This content is unavailable or has been deleted.'}
            else:
                return {'status': 'error', 'message': f'Platform download failed: {error_msg}'}
    
    # Add missing method for Reddit content
    def download_reddit_content(self, url, path, audio_only=False):
        """Download Reddit videos and images"""
        try:
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
                        'no_warnings': True,
                    }
                    conversion_msg = "converted to MP3"
                else:
                    ydl_opts = {
                        'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                        'format': 'bestaudio/best',
                        'ignoreerrors': True,
                        'no_warnings': True,
                    }
                    conversion_msg = "in original format (install FFmpeg for MP3 conversion)"
            
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, 'Reddit_%(title)s.%(ext)s'),
                    'format': 'best',
                    'ignoreerrors': True,
                    'no_warnings': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                # Check if info is None
                if not info:
                    return {'status': 'error', 'message': 'Failed to extract Reddit content. The post may be deleted, private, or contain no media.'}
                
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
            error_msg = str(e)
            if 'private' in error_msg.lower():
                return {'status': 'error', 'message': 'This Reddit post is private and cannot be downloaded.'}
            elif 'unavailable' in error_msg.lower():
                return {'status': 'error', 'message': 'This Reddit post is unavailable or has been deleted.'}
            else:
                return {'status': 'error', 'message': f'Reddit download failed: {error_msg}'}

    def download_content(self, url, audio_only=False):
        """Main download method that routes to appropriate platform handler"""
        try:
            # Get user-specific download directory
            user_download_dir = get_user_download_dir()
            
            # Create a subdirectory for this download
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            download_path = os.path.join(user_download_dir, f"download_{timestamp}")
            os.makedirs(download_path, exist_ok=True)
            
            platform = self.detect_platform(url)
            print(f"🔍 Detected platform: {platform} for URL: {url}")
            
            # Route to appropriate downloader
            if platform == 'youtube':
                result = self.download_youtube_content(url, download_path, audio_only)
            elif platform == 'instagram':
                result = self.download_instagram_content(url, download_path, audio_only)
            elif platform == 'tiktok':
                result = self.download_tiktok_content(url, download_path, audio_only)
            elif platform == 'twitter':
                result = self.download_twitter_content(url, download_path, audio_only)
            elif platform == 'facebook':
                result = self.download_facebook_content(url, download_path, audio_only)
            elif platform == 'reddit':
                result = self.download_reddit_content(url, download_path, audio_only)
            else:
                # Try generic downloader for unknown platforms
                result = self.download_generic_content(url, download_path, audio_only)
            
            # If download was successful, schedule file deletion
            if result.get('status') == 'success':
                self.schedule_downloaded_files_deletion(download_path)
                print(f"✅ Download completed successfully for {platform}")
            else:
                # Clean up empty directory if download failed
                try:
                    if os.path.exists(download_path) and not os.listdir(download_path):
                        os.rmdir(download_path)
                        print(f"🧹 Cleaned up empty directory after failed download")
                except Exception as e:
                    print(f"⚠️ Error cleaning up directory: {e}")
            
            return result
            
        except Exception as e:
            error_msg = f'Download error: {str(e)}'
            print(f"❌ {error_msg}")
            return {'status': 'error', 'message': error_msg}
    
    def extract_instagram_shortcode(self, url):
        """Extract Instagram post shortcode from URL"""
        try:
            # Handle different Instagram URL formats
            patterns = [
                r'instagram\.com/p/([^/?]+)',
                r'instagram\.com/reel/([^/?]+)',
                r'instagram\.com/tv/([^/?]+)',
                r'instagram\.com/stories/[^/]+/([^/?]+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)
            
            print(f"⚠️ Could not extract shortcode from URL: {url}")
            return None
            
        except Exception as e:
            print(f"❌ Error extracting Instagram shortcode: {e}")
            return None
    
    def extract_instagram_username(self, url):
        """Extract Instagram username from URL"""
        try:
            # Handle different Instagram URL formats
            patterns = [
                r'instagram\.com/([^/?]+)',
                r'instagram\.com/stories/([^/?]+)',
            ]
            
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    username = match.group(1)
                    # Filter out common non-username paths
                    if username not in ['p', 'reel', 'tv', 'stories', 'explore', 'accounts']:
                        return username
            
            print(f"⚠️ Could not extract username from URL: {url}")
            return None
            
        except Exception as e:
            print(f"❌ Error extracting Instagram username: {e}")
            return None
    
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

# For Render: Use Gunicorn or similar WSGI server in production.
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)