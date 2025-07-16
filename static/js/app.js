// Universal Media Downloader JavaScript
class MediaDownloader {
    constructor() {
        this.downloadTimers = {};
        this.refreshInterval = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.setupAnimations();
        this.refreshDownloads();
        console.log('🚀 Universal Media Downloader initialized');
    }

    setupEventListeners() {
        // Tab navigation
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchTab(e.target.dataset.tab));
        });

        // Download buttons
        document.getElementById('single-download-btn').addEventListener('click', () => this.downloadSingle());
        document.getElementById('bulk-download-btn').addEventListener('click', () => this.downloadBulk());

        // Action buttons
        document.querySelector('.refresh-btn').addEventListener('click', () => this.refreshDownloads());
        document.querySelector('.download-all-btn').addEventListener('click', () => this.downloadAllFiles());
        document.querySelector('.delete-btn').addEventListener('click', () => this.clearAllDownloads());

        // Input handlers
        document.getElementById('single-url').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.downloadSingle();
        });

        document.getElementById('single-url').addEventListener('input', (e) => {
            this.handleUrlInput(e.target.value, 'single-status');
        });

        // Radio button changes
        document.querySelectorAll('input[type="radio"]').forEach(radio => {
            radio.addEventListener('change', () => this.updateButtonText());
        });

        // Platform card animations
        document.querySelectorAll('.platform-card').forEach((card, index) => {
            card.style.setProperty('--index', index);
            card.addEventListener('mouseenter', () => this.animatePlatformCard(card));
        });
    }

    setupAnimations() {
        // Stagger feature card animations
        document.querySelectorAll('.feature-card').forEach((card, index) => {
            card.style.setProperty('--index', index);
            card.style.animationDelay = `${index * 0.1}s`;
        });

        // Add scroll animations
        this.setupScrollAnimations();
    }

    setupScrollAnimations() {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.style.animationPlayState = 'running';
                }
            });
        });

        document.querySelectorAll('.feature-card, .download-item').forEach(el => {
            observer.observe(el);
        });
    }

    switchTab(tabName) {
        // Remove active class from all tabs and content
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));

        // Add active class to selected tab and content
        document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
        document.getElementById(`${tabName}-tab`).classList.add('active');

        // Clear status messages
        document.getElementById(`${tabName}-status`).innerHTML = '';
    }

    async makeRequest(url, options = {}) {
        try {
            console.log('🌐 Making request to:', url);
            const response = await fetch(url, options);
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }
            
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                const text = await response.text();
                throw new Error(`Expected JSON but got: ${text.substring(0, 100)}...`);
            }
            
            return await response.json();
        } catch (error) {
            console.error('❌ Request failed:', error);
            throw error;
        }
    }

    async downloadSingle() {
        const url = document.getElementById('single-url').value.trim();
        const statusDiv = document.getElementById('single-status');
        const button = document.getElementById('single-download-btn');
        const spinner = button.querySelector('.btn-spinner');
        const buttonText = button.querySelector('.btn-text');
        const audioOnly = document.querySelector('input[name="single-type"]:checked').value === 'audio';
        
        if (!url) {
            this.showStatus(statusDiv, 'Please enter a valid URL', 'error');
            return;
        }
        
        if (audioOnly && url.toLowerCase().includes('instagram.com')) {
            this.showStatus(statusDiv, '⚠️ Audio extraction not supported for Instagram', 'error');
            return;
        }
        
        this.setButtonLoading(button, true);
        buttonText.textContent = audioOnly ? 'Extracting Audio...' : 'Downloading...';
        
        try {
            // Add longer timeout for cloud deployment
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 120000); // 2 minutes timeout
            
            const result = await this.makeRequest('/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, audio_only: audioOnly }),
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            if (result.status === 'success') {
                let message = `✅ ${result.message}`;
                if (result.title) message += `\n📝 ${result.title}`;
                if (result.platform) message += `\n🌐 ${result.platform}`;
                if (audioOnly) message += `\n🎵 Audio extracted as MP3`;
                
                this.showStatus(statusDiv, message, 'success');
                document.getElementById('single-url').value = '';
                
                this.startDownloadCountdown();
                setTimeout(() => this.refreshDownloads(), 1000);
            } else {
                // Enhanced error messages with better YouTube handling
                let errorMessage = result.message;
                
                if (errorMessage.includes('not available') || errorMessage.includes('unavailable')) {
                    errorMessage = `❌ ${errorMessage}\n\n💡 Common causes:\n• Video was removed or made private\n• Content is geo-restricted\n• Age-restricted content\n• Live stream not yet ended`;
                } else if (errorMessage.includes('geo-blocked') || errorMessage.includes('region')) {
                    errorMessage = `🌍 ${errorMessage}\n\n💡 Try: Different content or wait for server region changes`;
                } else if (errorMessage.includes('timeout') || errorMessage.includes('connection')) {
                    errorMessage = `⏱️ ${errorMessage}\n\n💡 Try: Refresh page and try again`;
                } else if (errorMessage.includes('private') || errorMessage.includes('restricted')) {
                    errorMessage = `🔒 ${errorMessage}\n\n💡 Try: Public content only`;
                } else if (errorMessage.includes('age-restricted')) {
                    errorMessage = `🔞 ${errorMessage}\n\n💡 Age-restricted content requires authentication`;
                } else if (errorMessage.includes('copyright') || errorMessage.includes('removed')) {
                    errorMessage = `📋 ${errorMessage}\n\n💡 Content was removed due to policy violations`;
                } else if (errorMessage.includes('live') && errorMessage.includes('stream')) {
                    errorMessage = `🔴 ${errorMessage}\n\n💡 Wait for live stream to end before downloading`;
                }
                
                this.showStatus(statusDiv, errorMessage, 'error');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                this.showStatus(statusDiv, '⏱️ Download timed out. Please try again with a shorter video or check your connection.', 'error');
            } else {
                this.showStatus(statusDiv, `❌ ${error.message}`, 'error');
            }
        } finally {
            this.setButtonLoading(button, false);
            buttonText.textContent = audioOnly ? 'Extract Audio' : 'Download Now';
        }
    }

    async downloadBulk() {
        const urlsText = document.getElementById('bulk-urls').value.trim();
        const statusDiv = document.getElementById('bulk-status');
        const button = document.getElementById('bulk-download-btn');
        const spinner = button.querySelector('.btn-spinner');
        const buttonText = button.querySelector('.btn-text');
        const audioOnly = document.querySelector('input[name="bulk-type"]:checked').value === 'audio';
        
        if (!urlsText) {
            this.showStatus(statusDiv, 'Please enter at least one URL', 'error');
            return;
        }
        
        const urls = urlsText.split('\n').filter(url => url.trim());
        
        if (urls.length === 0) {
            this.showStatus(statusDiv, 'Please enter valid URLs', 'error');
            return;
        }
        
        if (audioOnly) {
            const instagramUrls = urls.filter(url => url.toLowerCase().includes('instagram.com'));
            if (instagramUrls.length > 0) {
                this.showStatus(statusDiv, '⚠️ Audio extraction not supported for Instagram URLs', 'error');
                return;
            }
        }
        
        this.setButtonLoading(button, true);
        buttonText.textContent = audioOnly ? `Extracting Audio (${urls.length})...` : `Processing ${urls.length} URLs...`;
        
        try {
            const result = await this.makeRequest('/bulk-download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ urls, audio_only: audioOnly })
            });
            
            if (result.status === 'success') {
                let message = `✅ ${result.message}`;
                if (audioOnly) message += ` (Audio extracted as MP3)`;
                message += `\n\n📊 Results:\n`;
                
                result.results.forEach((res, index) => {
                    const icon = res.status === 'success' ? '✅' : '❌';
                    message += `${icon} URL ${index + 1}: ${res.message}\n`;
                });
                
                this.showStatus(statusDiv, message, 'success');
                document.getElementById('bulk-urls').value = '';
                
                this.startDownloadCountdown();
                setTimeout(() => this.refreshDownloads(), 1000);
            } else {
                this.showStatus(statusDiv, `❌ ${result.message}`, 'error');
            }
        } catch (error) {
            this.showStatus(statusDiv, `❌ ${error.message}`, 'error');
        } finally {
            this.setButtonLoading(button, false);
            buttonText.textContent = 'Download All';
        }
    }

    async refreshDownloads() {
        const downloadsDiv = document.getElementById('downloads-list');
        
        try {
            const result = await this.makeRequest('/downloads');
            
            if (result.error) {
                downloadsDiv.innerHTML = `<div class="status-message status-error">Error: ${result.error}</div>`;
                return;
            }
            
            if (result.items && result.items.length > 0) {
                let html = '<div class="downloads-grid">';
                
                result.items.forEach((item, index) => {
                    const icon = this.getFileIcon(item.name);
                    const size = this.formatFileSize(item.size);
                    const folderInfo = item.folder !== 'root' ? `📁 ${item.folder}` : '';
                    
                    const deletionInfo = result.deletion_info ? 
                        result.deletion_info.find(d => d.file === item.name) : null;
                    
                    let timerHtml = '';
                    if (deletionInfo && deletionInfo.remaining_seconds > 0) {
                        const minutes = Math.floor(deletionInfo.remaining_seconds / 60);
                        const seconds = deletionInfo.remaining_seconds % 60;
                        const timeStr = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                        
                        const timerClass = deletionInfo.remaining_seconds <= 10 ? 'warning' : '';
                        timerHtml = `
                            <div class="download-timer ${timerClass}">
                                ⏰ Auto-delete in: <span class="countdown-display">${timeStr}</span>
                            </div>
                        `;
                    }
                    
                    html += `
                        <div class="download-item" data-filename="${item.name}">
                            <h3 class="download-title">${icon} ${item.name}</h3>
                            <p class="download-meta">${size} ${folderInfo}</p>
                            ${timerHtml}
                            <div class="download-actions">
                                <button class="action-btn" onclick="downloader.downloadFile('${item.name}')">
                                    <span class="btn-icon">⬇️</span>
                                    Download
                                </button>
                            </div>
                        </div>
                    `;
                });
                
                html += '</div>';
                downloadsDiv.innerHTML = html;
            } else {
                downloadsDiv.innerHTML = `
                    <div class="empty-state">
                        <div style="font-size: 4rem; margin-bottom: 1rem; opacity: 0.3;">📁</div>
                        <p style="color: var(--text-secondary); text-align: center;">No downloads yet. Start downloading some content!</p>
                    </div>
                `;
            }
        } catch (error) {
            downloadsDiv.innerHTML = `<div class="status-message status-error">Network error: ${error.message}</div>`;
        }
    }

    async downloadAllFiles() {
        const downloadItems = document.querySelectorAll('.download-item');
        
        if (downloadItems.length === 0) {
            this.showToast('❌ No files to download', 'error');
            return;
        }
        
        const button = document.querySelector('.download-all-btn');
        const originalText = button.innerHTML;
        
        button.innerHTML = '<span class="btn-icon">⏳</span> Downloading...';
        button.disabled = true;
        
        let successCount = 0;
        const totalFiles = downloadItems.length;
        
        try {
            // Download all files with a small delay between each
            for (let i = 0; i < downloadItems.length; i++) {
                const item = downloadItems[i];
                const filename = item.getAttribute('data-filename');
                
                try {
                    await this.downloadFileAsync(filename);
                    successCount++;
                    
                    // Update button text with progress
                    button.innerHTML = `<span class="btn-icon">📥</span> ${successCount}/${totalFiles}`;
                    
                    // Small delay to prevent overwhelming the server
                    await new Promise(resolve => setTimeout(resolve, 500));
                } catch (error) {
                    console.error(`Failed to download ${filename}:`, error);
                }
            }
            
            if (successCount === totalFiles) {
                this.showToast(`✅ All ${totalFiles} files downloaded successfully!`, 'success');
            } else {
                this.showToast(`⚠️ Downloaded ${successCount}/${totalFiles} files`, 'warning');
            }
            
        } catch (error) {
            this.showToast(`❌ Error during bulk download: ${error.message}`, 'error');
        } finally {
            button.innerHTML = originalText;
            button.disabled = false;
            
            // Refresh downloads after a short delay
            setTimeout(() => this.refreshDownloads(), 2000);
        }
    }

    async downloadFileAsync(filename) {
        return new Promise((resolve, reject) => {
            try {
                console.log('📥 Starting download for:', filename);
                
                const downloadUrl = `/download-file/${encodeURIComponent(filename)}`;
                const link = document.createElement('a');
                link.href = downloadUrl;
                link.download = filename;
                link.style.display = 'none';
                
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                
                resolve();
            } catch (error) {
                reject(error);
            }
        });
    }

    startDownloadCountdown() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        this.refreshInterval = setInterval(() => {
            this.refreshDownloads();
        }, 2000); // Increased interval to reduce blinking
        
        setTimeout(() => {
            if (this.refreshInterval) {
                clearInterval(this.refreshInterval);
                this.refreshInterval = null;
            }
        }, 35000);
    }

    handleUrlInput(url, statusId) {
        const statusDiv = document.getElementById(statusId);
        
        if (!url.trim()) {
            statusDiv.innerHTML = '';
            return;
        }
        
        if (url.includes('youtube.com') || url.includes('youtu.be')) {
            // Check for common YouTube issues
            if (url.includes('/shorts/')) {
                this.showStatus(statusDiv, '🎬 Detected: YouTube Shorts', 'loading');
            } else if (url.includes('playlist')) {
                this.showStatus(statusDiv, '📁 Detected: YouTube Playlist', 'loading');
            } else if (url.includes('/live/')) {
                this.showStatus(statusDiv, '🔴 Detected: YouTube Live Stream (may not be downloadable)', 'loading');
            } else {
                this.showStatus(statusDiv, '🎬 Detected: YouTube Video', 'loading');
            }
        } else if (url.includes('instagram.com')) {
            this.showStatus(statusDiv, '⚠️ Note: Audio extraction not supported for Instagram', 'loading');
        } else {
            const platforms = {
                'tiktok.com': 'TikTok', 'twitter.com': 'Twitter', 'x.com': 'Twitter',
                'facebook.com': 'Facebook', 'reddit.com': 'Reddit'
            };
            
            const platform = Object.keys(platforms).find(key => url.includes(key));
            
            if (platform) {
                this.showStatus(statusDiv, `🌐 Detected: ${platforms[platform]}`, 'loading');
            } else {
                this.showStatus(statusDiv, '🔍 Analyzing URL...', 'loading');
            }
        }
    }

    updateButtonText() {
        const singleAudio = document.querySelector('input[name="single-type"]:checked').value === 'audio';
        const bulkAudio = document.querySelector('input[name="bulk-type"]:checked').value === 'audio';
        
        document.querySelector('#single-download-btn .btn-text').textContent = 
            singleAudio ? 'Extract Audio' : 'Download Now';
        document.querySelector('#bulk-download-btn .btn-text').textContent = 
            bulkAudio ? 'Extract All Audio' : 'Download All';
    }

    setButtonLoading(button, loading) {
        const spinner = button.querySelector('.btn-spinner');
        const icon = button.querySelector('.btn-icon');
        
        if (loading) {
            spinner.style.display = 'block';
            icon.style.display = 'none';
            button.disabled = true;
        } else {
            spinner.style.display = 'none';
            icon.style.display = 'block';
            button.disabled = false;
        }
    }

    showStatus(container, message, type) {
        const statusHtml = `<div class="status-message status-${type}">${message.replace(/\n/g, '<br>')}</div>`;
        container.innerHTML = statusHtml;
        
        // Add animation
        const statusElement = container.querySelector('.status-message');
        statusElement.style.animation = 'slideInUp 0.3s ease-out';
    }

    showToast(message, type) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 1rem 1.5rem;
            border-radius: 0.5rem;
            color: white;
            font-weight: 600;
            z-index: 1000;
            animation: slideInRight 0.3s ease-out;
            background: ${type === 'success' ? 'var(--success)' : 'var(--error)'};
        `;
        
        document.body.appendChild(toast);
        
        setTimeout(() => {
            toast.style.animation = 'slideOutRight 0.3s ease-out';
            setTimeout(() => document.body.removeChild(toast), 300);
        }, 3000);
    }

    animatePlatformCard(card) {
        card.style.transform = 'translateY(-5px) scale(1.05) rotateY(5deg)';
        setTimeout(() => {
            card.style.transform = '';
        }, 300);
    }

    getFileIcon(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        const icons = {
            'mp4': '🎬', 'avi': '🎬', 'mkv': '🎬', 'mov': '🎬', 'webm': '🎬',
            'mp3': '🎵', 'wav': '🎵', 'flac': '🎵', 'm4a': '🎵', 'aac': '🎵',
            'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️', 'webp': '🖼️',
            'pdf': '📄', 'txt': '📄', 'doc': '📄', 'docx': '📄',
            'zip': '📦', 'rar': '📦', '7z': '📦'
        };
        return icons[ext] || '📄';
    }

    formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    async clearAllDownloads() {
        if (!confirm('Are you sure you want to clear all downloads? This will delete all downloaded files.')) {
            return;
        }
        
        const button = document.querySelector('.delete-btn');
        const originalText = button.innerHTML;
        
        button.innerHTML = '<span class="btn-icon">⏳</span> Clearing...';
        button.disabled = true;
        
        try {
            const result = await this.makeRequest('/clear-downloads', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (result.status === 'success') {
                this.showToast(`✅ ${result.message}`, 'success');
                // Refresh the downloads list
                setTimeout(() => this.refreshDownloads(), 1000);
            } else {
                this.showToast(`❌ ${result.message}`, 'error');
            }
        } catch (error) {
            this.showToast(`❌ Error clearing downloads: ${error.message}`, 'error');
        } finally {
            button.innerHTML = originalText;
            button.disabled = false;
        }
    }
}

// Initialize the downloader when DOM is loaded
let downloader;
document.addEventListener('DOMContentLoaded', () => {
    downloader = new MediaDownloader();
});

// Add CSS for toast animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOutRight {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);
