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
import random
import time

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
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
    def get_bypass_options(self, url):
        """Get bypass options for different scenarios"""
        base_options = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_insecure': True,
            # Bypass geo-restrictions
            'geo_bypass': True,
            'geo_bypass_country': ['US', 'UK', 'CA', 'AU', 'DE', 'FR', 'JP'],
            # User agent rotation
            'http_headers': {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Cache-Control': 'max-age=0'
            }
        }
        
        # YouTube specific bypasses
        if 'youtube.com' in url or 'youtu.be' in url:
            base_options.update({
                # Try to bypass age restrictions
                'age_limit': 99,
                'mark_watched': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                'allsubtitles': False,
                'listsubtitles': False,
                # Use alternative extractors
                'youtube_include_dash_manifest': False,
                'youtube_include_hls_manifest': False,
                # Cookie support for login bypass
                'cookiefile': None,
                'cookiesfrombrowser': None,
                # Additional bypass techniques
                'extractor_args': {
                    'youtube': {
                        'skip': ['dash', 'hls'],
                        'player_skip': ['js', 'configs'],
                        'player_client': ['android', 'web'],
                        'comment_sort': ['top'],
                        'max_comments': ['0']
                    }
                }
            })
        
        return base_options
    
    def try_alternative_extractors(self, url):
        """Try alternative extraction methods"""
        alternatives = [
            # Try with different client configurations
            {'extractor_args': {'youtube': {'player_client': ['android']}}},
            {'extractor_args': {'youtube': {'player_client': ['web']}}},
            {'extractor_args': {'youtube': {'player_client': ['ios']}}},
            {'extractor_args': {'youtube': {'player_client': ['mweb']}}},
            # Try with different bypass methods
            {'geo_bypass_country': 'US'},
            {'geo_bypass_country': 'UK'},
            {'geo_bypass_country': 'CA'},
            # Try with age bypass
            {'age_limit': 999},
        ]
        
        # Add user agent variations
        for ua in self.user_agents[:3]:
            alternatives.append({'http_headers': {'User-Agent': ua}})
        
        for alt_config in alternatives:
            try:
                print(f"Trying alternative config: {alt_config}")
                yield alt_config
            except Exception as e:
                print(f"Alternative config failed: {e}")
                continue
    
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
        """Download YouTube content with advanced bypass techniques"""
        try:
            # Base configuration with bypass options
            base_opts = self.get_bypass_options(url)
            
            if audio_only:
                base_opts.update({
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3' if self.check_ffmpeg_availability() else 'best',
                    'audioquality': '192',
                })
            else:
                base_opts.update({
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'best[height<=720]/best',
                })
            
            # Try multiple extraction attempts with different configurations
            last_error = None
            
            for attempt, alt_config in enumerate(self.try_alternative_extractors(url)):
                try:
                    print(f"Attempt {attempt + 1}: Trying with config {alt_config}")
                    
                    # Merge base options with alternative config
                    ydl_opts = {**base_opts, **alt_config}
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        # First try to extract info
                        info = ydl.extract_info(url, download=False)
                        
                        if info is None:
                            print(f"Info extraction failed for attempt {attempt + 1}")
                            continue
                        
                        # Validate extracted info
                        if not self.validate_extracted_info(info):
                            print(f"Info validation failed for attempt {attempt + 1}")
                            continue
                        
                        # If we get here, extraction worked, now download
                        print(f"Info extraction successful, proceeding with download")
                        info = ydl.extract_info(url, download=True)
                        
                        if info is None:
                            print(f"Download failed for attempt {attempt + 1}")
                            continue
                        
                        # Success! Process the result
                        return self.process_download_result(info, path, audio_only)
                        
                except yt_dlp.utils.DownloadError as e:
                    error_msg = str(e).lower()
                    print(f"Download error in attempt {attempt + 1}: {error_msg}")
                    last_error = e
                    
                    # Don't retry for certain errors
                    if any(fatal in error_msg for fatal in ['copyright', 'terminated', 'suspended']):
                        break
                    
                    # Add delay between attempts
                    if attempt < 4:  # Not the last attempt
                        time.sleep(2)
                    continue
                    
                except Exception as e:
                    print(f"General error in attempt {attempt + 1}: {str(e)}")
                    last_error = e
                    continue
            
            # If all attempts failed, return appropriate error
            if last_error:
                return self.handle_download_error(last_error)
            else:
                return {'status': 'error', 'message': 'All extraction attempts failed. Video may be permanently unavailable.'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Unexpected error during download: {str(e)}'}
    
    def validate_extracted_info(self, info):
        """Validate extracted info structure"""
        if not isinstance(info, dict):
            return False
        
        # Check for playlist
        if 'entries' in info:
            entries = info.get('entries')
            if entries is None:
                return False
            
            # Filter valid entries
            valid_entries = []
            for entry in entries:
                if entry is not None and isinstance(entry, dict):
                    if entry.get('title') is not None or entry.get('id') is not None:
                        valid_entries.append(entry)
            
            if not valid_entries:
                return False
            
            # Update with valid entries
            info['entries'] = valid_entries
            return True
        else:
            # Single video validation
            return (info.get('title') is not None or info.get('id') is not None)
    
    def process_download_result(self, info, path, audio_only):
        """Process successful download result"""
        download_id = f"yt_{datetime.now().timestamp()}"
        download_cache[download_id] = {
            'path': path,
            'info': info,
            'type': 'audio' if audio_only else 'video'
        }
        
        content_type = 'audio' if audio_only else 'video'
        
        # Handle playlist vs single video
        if 'entries' in info and info.get('entries') is not None:
            entries = info.get('entries', [])
            
            # Filter valid entries
            valid_entries = []
            for entry in entries:
                if entry is not None and isinstance(entry, dict):
                    title = entry.get('title')
                    if title is not None and str(title).strip():
                        valid_entries.append(entry)
            
            if not valid_entries:
                return {'status': 'error', 'message': 'Playlist processed but no valid videos found'}
            
            titles = [entry.get('title', 'Unknown Title') for entry in valid_entries]
            
            return {
                'status': 'success',
                'message': f'Successfully downloaded {len(titles)} {content_type}s from playlist!',
                'titles': titles[:5],
                'type': f'playlist_{content_type}',
                'download_id': download_id
            }
        else:
            # Single video
            title = info.get('title')
            uploader = info.get('uploader')
            
            if title is None or not str(title).strip():
                title = f"Video_{info.get('id', 'Unknown')}"
            
            if uploader is None or not str(uploader).strip():
                uploader = 'Unknown Channel'
            
            return {
                'status': 'success',
                'message': f'Successfully downloaded {content_type} with bypass techniques!',
                'title': str(title),
                'uploader': str(uploader),
                'type': content_type,
                'download_id': download_id
            }
    
    def handle_download_error(self, error):
        """Handle download errors with specific messages"""
        error_msg = str(error).lower()
        
        if any(phrase in error_msg for phrase in ["video unavailable", "this video is unavailable"]):
            return {'status': 'error', 'message': 'Video unavailable even with bypass attempts. May be permanently deleted.'}
        elif any(phrase in error_msg for phrase in ["private video", "video is private"]):
            return {'status': 'error', 'message': 'Private video - cannot bypass privacy restrictions.'}
        elif "sign in to confirm your age" in error_msg:
            return {'status': 'error', 'message': 'Age-restricted content - tried bypass but failed.'}
        elif any(phrase in error_msg for phrase in ["403", "forbidden"]):
            return {'status': 'error', 'message': 'Access forbidden - tried geo-bypass but failed.'}
        elif "404" in error_msg:
            return {'status': 'error', 'message': 'Video not found - may be deleted or URL is incorrect.'}
        elif any(phrase in error_msg for phrase in ["copyright", "terminated", "suspended"]):
            return {'status': 'error', 'message': 'Video removed due to copyright/terms violation.'}
        elif "region" in error_msg or "country" in error_msg:
            return {'status': 'error', 'message': 'Region-blocked content - geo-bypass failed.'}
        else:
            return {'status': 'error', 'message': f'Download failed after multiple bypass attempts: {str(error)}'}
    
    def download_generic_content(self, url, path, audio_only=False):
        """Download from other platforms with bypass techniques"""
        try:
            base_opts = self.get_bypass_options(url)
            
            if audio_only:
                base_opts.update({
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'bestaudio/best',
                    'extractaudio': True,
                    'audioformat': 'mp3' if self.check_ffmpeg_availability() else 'best',
                })
            else:
                base_opts.update({
                    'outtmpl': os.path.join(path, '%(title)s.%(ext)s'),
                    'format': 'best[height<=720]/best',
                })
            
            # Try multiple configurations
            for attempt, alt_config in enumerate(self.try_alternative_extractors(url)):
                try:
                    ydl_opts = {**base_opts, **alt_config}
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=False)
                        
                        if info is None:
                            continue
                        
                        info = ydl.extract_info(url, download=True)
                        
                        if not info:
                            continue
                        
                        # Success
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
                            'message': f'{content_type.title()} downloaded successfully with bypass!',
                            'title': title,
                            'extractor': extractor,
                            'type': content_type,
                            'download_id': download_id
                        }
                        
                except Exception as e:
                    if attempt < 4:
                        time.sleep(1)
                    continue
            
            return {'status': 'error', 'message': 'All bypass attempts failed for this platform'}
                
        except Exception as e:
            return {'status': 'error', 'message': f'Platform download error: {str(e)}'}
    
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