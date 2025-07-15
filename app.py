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
import io
import base64
from urllib.parse import urlparse

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this'

# Use temporary directory for Vercel compatibility
TEMP_DIR = tempfile.gettempdir()
DOWNLOAD_DIR = os.path.join(TEMP_DIR, 'downloads')

# In-memory storage for download tracking
download_cache = {}

class VercelCompatibleDownloader:
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
    
    def create_temp_dir(self):
        """Create a temporary directory for downloads"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_path = os.path.join(TEMP_DIR, f'dl_{timestamp}')
        os.makedirs(temp_path, exist_ok=True)
        return temp_path
    
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
    
    def download_youtube_content(self, url, path, audio_only=False):
        """Download YouTube content with Vercel optimization"""
        try:
            if audio_only:
                # Simplified audio options for Vercel
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'writesubtitles': False,
                    'ignoreerrors': True,
                    'no_warnings': True,
                    'extractaudio': True,
                    'audioformat': 'mp3' if self.check_ffmpeg_availability() else 'best',
                    'audioquality': '192',
                    'socket_timeout': 30,
                    'retries': 3,
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'best[height<=720]/best',  # Limit quality for Vercel
                    'writesubtitles': False,
                    'ignoreerrors': True,
                    'no_warnings': True,
                    'socket_timeout': 30,
                    'retries': 3,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # First, try to extract info without downloading
                try:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        return {'status': 'error', 'message': 'Could not extract video information'}
                    
                    # Check if info has the required fields
                    if not isinstance(info, dict):
                        return {'status': 'error', 'message': 'Invalid video information received'}
                    
                    # Now download with the validated info
                    info = ydl.extract_info(url, download=True)
                    
                except Exception as extract_error:
                    return {'status': 'error', 'message': f'Failed to extract video info: {str(extract_error)}'}
                
                # Validate the downloaded info
                if not info:
                    return {'status': 'error', 'message': 'No video information available'}
                
                # Cache the download info
                download_id = f"yt_{datetime.now().timestamp()}"
                download_cache[download_id] = {
                    'path': path,
                    'info': info,
                    'type': 'audio' if audio_only else 'video'
                }
                
                content_type = 'audio' if audio_only else 'video'
                
                # Handle playlist vs single video
                if info.get('entries') is not None:  # Playlist
                    entries = info.get('entries', [])
                    if not entries:
                        return {'status': 'error', 'message': 'Playlist is empty or unavailable'}
                    
                    titles = []
                    for entry in entries:
                        if entry and isinstance(entry, dict):
                            title = entry.get('title', 'Unknown')
                            titles.append(title)
                    
                    return {
                        'status': 'success',
                        'message': f'Downloaded {len(titles)} {content_type}s from playlist',
                        'titles': titles[:5],
                        'type': f'playlist_{content_type}',
                        'download_id': download_id
                    }
                else:
                    # Single video
                    title = info.get('title', 'Unknown')
                    uploader = info.get('uploader', 'Unknown')
                    
                    return {
                        'status': 'success',
                        'message': f'YouTube {content_type} downloaded successfully!',
                        'title': title,
                        'uploader': uploader,
                        'type': content_type,
                        'download_id': download_id
                    }
                    
        except Exception as e:
            error_msg = str(e)
            if "argument of type 'NoneType' is not iterable" in error_msg:
                return {'status': 'error', 'message': 'Video not available or private. Please check the URL.'}
            elif "Video unavailable" in error_msg:
                return {'status': 'error', 'message': 'Video is unavailable or has been removed.'}
            elif "Private video" in error_msg:
                return {'status': 'error', 'message': 'Cannot download private videos.'}
            else:
                return {'status': 'error', 'message': f'YouTube error: {error_msg}'}
    
    def download_instagram_content(self, url, path):
        """Download Instagram content with Vercel optimization"""
        try:
            # Simplified Instagram downloader for Vercel
            loader = instaloader.Instaloader(
                dirname_pattern=path,
                filename_pattern='{mediaid}',
                download_videos=True,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                max_connection_attempts=1
            )
            
            if '/p/' in url or '/reel/' in url or '/tv/' in url:
                shortcode = self.extract_instagram_shortcode(url)
                if shortcode:
                    post = instaloader.Post.from_shortcode(loader.context, shortcode)
                    loader.download_post(post, target='')
                    
                    download_id = f"ig_{datetime.now().timestamp()}"
                    download_cache[download_id] = {
                        'path': path,
                        'username': post.owner_username,
                        'type': 'instagram_post'
                    }
                    
                    return {
                        'status': 'success',
                        'message': 'Instagram content downloaded successfully!',
                        'username': post.owner_username,
                        'type': 'instagram_post',
                        'download_id': download_id
                    }
            
            return {'status': 'error', 'message': 'Invalid Instagram URL format'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Instagram error: {str(e)}'}
    
    def download_generic_content(self, url, path, audio_only=False):
        """Download from supported platforms with Vercel optimization"""
        try:
            if audio_only:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3' if self.check_ffmpeg_availability() else 'best',
                    'no_warnings': True,
                    'socket_timeout': 30,
                    'retries': 3,
                    'ignoreerrors': True,
                }
            else:
                ydl_opts = {
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'best[height<=720]/best',
                    'no_warnings': True,
                    'socket_timeout': 30,
                    'retries': 3,
                    'ignoreerrors': True,
                }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first to validate
                try:
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        return {'status': 'error', 'message': 'Could not extract media information'}
                    
                    # Download with validated info
                    info = ydl.extract_info(url, download=True)
                    
                except Exception as extract_error:
                    return {'status': 'error', 'message': f'Failed to extract media info: {str(extract_error)}'}
                
                if not info:
                    return {'status': 'error', 'message': 'No media information available'}
                
                download_id = f"gen_{datetime.now().timestamp()}"
                download_cache[download_id] = {
                    'path': path,
                    'info': info,
                    'type': 'audio' if audio_only else 'video'
                }
                
                content_type = 'audio' if audio_only else 'media'
                title = info.get('title', 'Unknown') if info else 'Unknown'
                extractor = info.get('extractor', 'Unknown') if info else 'Unknown'
                
                return {
                    'status': 'success',
                    'message': f'{content_type.title()} downloaded successfully!',
                    'title': title,
                    'extractor': extractor,
                    'type': content_type,
                    'download_id': download_id
                }
                
        except Exception as e:
            error_msg = str(e)
            if "argument of type 'NoneType' is not iterable" in error_msg:
                return {'status': 'error', 'message': 'Media not available or private. Please check the URL.'}
            else:
                return {'status': 'error', 'message': f'Download error: {error_msg}'}
    
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
    
    def download_content(self, url, audio_only=False):
        """Main download function optimized for Vercel"""
        platform = self.detect_platform(url)
        path = self.create_temp_dir()
        
        try:
            if platform == 'youtube':
                return self.download_youtube_content(url, path, audio_only)
            elif platform == 'instagram':
                if audio_only:
                    return {'status': 'error', 'message': 'Audio-only download not supported for Instagram'}
                return self.download_instagram_content(url, path)
            elif platform in ['tiktok', 'twitter', 'facebook', 'reddit']:
                return self.download_generic_content(url, path, audio_only)
            else:
                return self.download_generic_content(url, path, audio_only)
                
        except Exception as e:
            return {'status': 'error', 'message': f'Unexpected error: {str(e)}'}

# Initialize downloader
downloader = VercelCompatibleDownloader()

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

@app.route('/downloads')
def list_downloads():
    """List downloaded files from cache"""
    try:
        items = []
        
        for download_id, cache_info in download_cache.items():
            path = cache_info.get('path', '')
            if os.path.exists(path):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if not file.startswith('.'):
                            file_path = os.path.join(root, file)
                            try:
                                file_size = os.path.getsize(file_path)
                                items.append({
                                    'name': file,
                                    'size': file_size,
                                    'folder': cache_info.get('type', 'unknown'),
                                    'download_id': download_id
                                })
                            except:
                                continue
        
        return jsonify({'items': items})
        
    except Exception as e:
        return jsonify({'error': f'Error listing downloads: {str(e)}'})

@app.route('/download-file/<path:filename>')
def download_file(filename):
    """Download a specific file"""
    try:
        # Search in cache for the file
        for download_id, cache_info in download_cache.items():
            path = cache_info.get('path', '')
            if os.path.exists(path):
                for root, dirs, files in os.walk(path):
                    for file in files:
                        if file == filename or filename in file:
                            file_path = os.path.join(root, file)
                            if os.path.exists(file_path):
                                return send_file(
                                    file_path,
                                    as_attachment=True,
                                    download_name=file,
                                    mimetype='application/octet-stream'
                                )
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/clear-downloads', methods=['POST'])
def clear_downloads():
    """Clear all downloads"""
    try:
        global download_cache
        
        # Clean up temp directories
        for download_id, cache_info in download_cache.items():
            path = cache_info.get('path', '')
            if os.path.exists(path):
                try:
                    shutil.rmtree(path)
                except:
                    pass
        
        download_cache.clear()
        
        return jsonify({'status': 'success', 'message': 'All downloads cleared'})
        
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Clear error: {str(e)}'})

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Vercel deployment running',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/check-ffmpeg')
def check_ffmpeg():
    """Check FFmpeg availability"""
    try:
        available = downloader.check_ffmpeg_availability()
        return jsonify({
            'available': available,
            'message': 'FFmpeg is available' if available else 'FFmpeg not available - audio will be in original format'
        })
    except Exception as e:
        return jsonify({'available': False, 'error': str(e)})

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Endpoint not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    return jsonify({'error': f'Server error: {str(e)}'}), 500

# Vercel entry point
if __name__ == '__main__':
    app.run(debug=False)