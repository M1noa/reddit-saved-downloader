#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time
import asyncio
import aiohttp
import aiofiles
import logging
import yt_dlp
import cloudscraper
import random
import signal
try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from rich.logging import RichHandler
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

console = Console()

class RedditMediaDownloader:
    def __init__(self, output_dir: str, max_concurrent: int = 5, filename_style: str = 'basic', log_file: str = None, debug: bool = False):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)  # Create output directory if it doesn't exist
        self.max_concurrent = max_concurrent
        self.filename_style = filename_style
        self.session = None
        self.processed_urls = set()  # Track processed URLs
        self.processed_posts = set()  # Track processed post IDs to prevent duplicates
        self.download_semaphore = None  # Control concurrent downloads
        self.max_retries = 3  # Maximum retry attempts for failed downloads
        self.base_delay = 1  # Base delay for exponential backoff
        
        # Create log file directory if specified
        if log_file:
            log_dir = os.path.dirname(os.path.abspath(log_file))
            os.makedirs(log_dir, exist_ok=True)
            
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[dim cyan]{task.description}"),
            BarColumn(complete_style="cyan", finished_style="bright_cyan"),
            TaskProgressColumn(),
            console=console,
            refresh_per_second=2  # Reduce update frequency
        )
        
        # Setup logging with simplified format
        log_format = "%(levelname)s - %(message)s"
        log_level = logging.DEBUG if debug else logging.INFO
        if log_file:
            logging.basicConfig(
                level=log_level,
                format=log_format,
                handlers=[
                    RichHandler(console=console, rich_tracebacks=True, show_path=False),
                    logging.FileHandler(log_file)
                ]
            )
        else:
            logging.basicConfig(
                level=log_level,
                format=log_format,
                handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)]
            )

    def _get_media_urls(self, post: Dict[str, Any]) -> List[str]:
        urls = []
        
        # Check for RedGifs URLs
        if post.get('domain') == 'redgifs.com' and 'url_overridden_by_dest' in post:
            logging.info(f"🔄 Processing RedGifs URL: {post.get('title', 'Untitled')}")
            urls.append(post['url_overridden_by_dest'])
        
        # Check for Reddit media URLs
        if post.get('is_video', False):
            video_data = post.get('media', {}).get('reddit_video', {})
            if video_data:
                if video_data.get('fallback_url'):
                    logging.info(f"🎥 Processing Reddit Video: {post.get('title', 'Untitled')}")
                    urls.append(video_data['fallback_url'])
                # Add HLS URL as fallback
                elif video_data.get('hls_url'):
                    urls.append(video_data['hls_url'])
        
        # Check for preview videos
        preview = post.get('preview', {}).get('reddit_video_preview', {})
        if preview and preview.get('fallback_url') and not urls:
            urls.append(preview['fallback_url'])
        
        # Check for Reddit video URLs (v.redd.it)
        if 'url_overridden_by_dest' in post:
            url = post['url_overridden_by_dest']
            if 'v.redd.it' in url:
                logging.info(f"🎥 Processing Reddit Video (v.redd.it): {post.get('title', 'Untitled')}")
                urls.append(url)
            else:
                # Check for direct image/gif URLs
                ext = os.path.splitext(url)[1].lower()
                if ext in ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.gifv']:
                    logging.info(f"📸 Processing Direct Media: {post.get('title', 'Untitled')}")
                    urls.append(url)
                elif ext and ext not in ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.gifv']:
                    logging.warning(f"⚠️  Unsupported file type '{ext}' for: {post.get('title', 'Untitled')} - {url}")
                elif not ext and not any(domain in url for domain in ['redgifs.com', 'reddit.com', 'v.redd.it']):
                    logging.warning(f"⚠️  Unknown URL format: {post.get('title', 'Untitled')} - {url}")
        
        # Log if no media URLs were found
        if not urls and post.get('url_overridden_by_dest'):
            domain = post.get('domain', 'unknown')
            if domain not in ['self.', 'reddit.com'] and not domain.endswith('.reddit.com'):
                logging.info(f"ℹ️  No downloadable media found for: {post.get('title', 'Untitled')} (domain: {domain})")
        
        return urls

    async def init_session(self):
        self.session = aiohttp.ClientSession()
        self.download_semaphore = asyncio.Semaphore(self.max_concurrent)  # Initialize semaphore

    async def close_session(self):
        if self.session:
            await self.session.close()
    
    def _parse_cookies(self, cookie_string: str) -> dict:
        """Parse cookie string into a dictionary"""
        cookies = {}
        for cookie in cookie_string.split(';'):
            if '=' in cookie:
                key, value = cookie.strip().split('=', 1)
                cookies[key] = value
        return cookies
    
    async def fetch_saved_posts_from_reddit(self, cookies: str) -> dict:
        """Fetch saved posts from Reddit API with pagination using cloudscraper to bypass Cloudflare"""
        parsed_cookies = self._parse_cookies(cookies)
        
        # Extract username from cookies (from reddit_session token)
        username = None
        if 'reddit_session' in parsed_cookies:
            try:
                import base64
                # Decode JWT token to get username (simplified)
                token_parts = parsed_cookies['reddit_session'].split('.')
                if len(token_parts) >= 2:
                    # Add padding if needed
                    payload = token_parts[1]
                    payload += '=' * (4 - len(payload) % 4)
                    decoded = base64.b64decode(payload)
                    token_data = json.loads(decoded)
                    if 'sub' in token_data and token_data['sub'].startswith('t2_'):
                        # For now, we'll use a placeholder username
                        username = "me"  # Reddit API allows 'me' for current user
            except Exception:
                username = "me"  # Fallback to 'me'
        
        if not username:
            console.print("[red]❌ Could not extract username from cookies[/red]")
            return None
        
        all_posts = []
        seen_post_ids = set()
        after = None
        consecutive_duplicates = 0
        max_consecutive_duplicates = 3
        
        # Try undetected-chromedriver first, fallback to cloudscraper
        driver = None
        scraper = None
        
        if SELENIUM_AVAILABLE:
            try:
                console.print("[blue]🔐 Initializing undetected Chrome browser...[/blue]")
                options = uc.ChromeOptions()
                # Remove headless mode to better mimic real user
                # options.add_argument('--headless')
                options.add_argument('--no-sandbox')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--disable-gpu')
                options.add_argument('--window-size=1920,1080')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_experimental_option("excludeSwitches", ["enable-automation"])
                options.add_experimental_option('useAutomationExtension', False)
                options.add_argument('--disable-extensions')
                options.add_argument('--profile-directory=Default')
                options.add_argument('--user-data-dir=/tmp/chrome_dev_test')
                options.add_argument('--disable-plugins-discovery')
                options.add_argument('--start-maximized')
                
                driver = uc.Chrome(options=options, version_main=None)
                
                # Execute stealth scripts to hide automation
                driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
                driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
                driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']})")
                
                # Set cookies in the browser
                driver.get('https://www.reddit.com')
                for name, value in parsed_cookies.items():
                    driver.add_cookie({'name': name, 'value': value, 'domain': '.reddit.com'})
                
                console.print("[green]✓ Undetected Chrome browser initialized successfully[/green]")
                time.sleep(3)  # Longer delay to appear more human
                
            except Exception as e:
                console.print(f"[yellow]⚠️ Undetected Chrome failed, falling back to cloudscraper: {e}[/yellow]")
                if driver:
                    driver.quit()
                driver = None
        
        if not driver:
            # Fallback to cloudscraper
            console.print("[blue]🔐 Using cloudscraper as fallback...[/blue]")
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            
            # Set enhanced headers to mimic real browser
            scraper.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'none',
                'Sec-Fetch-User': '?1',
                'Cache-Control': 'max-age=0',
                'Referer': 'https://www.reddit.com/'
            })
            
            # Set cookies on the scraper session
            for name, value in parsed_cookies.items():
                scraper.cookies.set(name, value)
            
            # Make an initial request to establish session
            try:
                initial_response = scraper.get('https://www.reddit.com/')
                if initial_response.status_code == 200:
                    console.print("[green]✓ Cloudscraper session established[/green]")
                else:
                    console.print(f"[yellow]⚠️ Initial request returned {initial_response.status_code}[/yellow]")
            except Exception as e:
                console.print(f"[yellow]⚠️ Initial session setup failed: {e}[/yellow]")
            
            time.sleep(2)
        
        while True:
            # Construct URL
            url = f"https://www.reddit.com/user/{username}/saved.json?count=25"
            if after:
                url += f"&after={after}"
            
            console.print(f"[dim]Fetching: {url}[/dim]")
            
            # Make request using either selenium or cloudscraper
            try:
                if driver:
                    # Use selenium undetected chromedriver
                    # First navigate to the regular saved posts page to establish session
                    saved_page_url = f"https://www.reddit.com/user/{username}/saved"
                    if after:
                        saved_page_url += f"?after={after}"
                    
                    driver.get(saved_page_url)
                    time.sleep(3)  # Wait for page to load
                    
                    # Check if we're blocked
                    page_source = driver.page_source
                    if "403" in page_source or "blocked" in page_source.lower() or "cloudflare" in page_source.lower():
                        console.print(f"[red]❌ Blocked by Cloudflare (Selenium)[/red]")
                        break
                    
                    # Now try to get the JSON endpoint
                    driver.get(url)
                    time.sleep(2)  # Wait for JSON to load
                    
                    # Get page source and parse JSON
                    page_source = driver.page_source
                    if "403" in page_source or "blocked" in page_source.lower():
                        console.print(f"[red]❌ JSON endpoint blocked by Cloudflare[/red]")
                        break
                    
                    # Extract JSON from page source
                    try:
                        # Find JSON data in page source
                        json_start = page_source.find('{')
                        json_end = page_source.rfind('}') + 1
                        if json_start != -1 and json_end > json_start:
                            json_str = page_source[json_start:json_end]
                            data = json.loads(json_str)
                        else:
                            console.print(f"[red]❌ Could not extract JSON from page[/red]")
                            break
                    except json.JSONDecodeError as e:
                        console.print(f"[red]❌ JSON decode error: {e}[/red]")
                        break
                else:
                    # Use cloudscraper
                    response = scraper.get(url)
                    
                    if response.status_code != 200:
                        console.print(f"[red]❌ HTTP {response.status_code}: {response.text[:200]}[/red]")
                        break
                    
                    data = response.json()
                
                if not data or 'data' not in data or 'children' not in data['data']:
                    console.print("[yellow]⚠️ No more posts found[/yellow]")
                    break
                
                posts = data['data']['children']
                
                if not posts:
                    console.print("[yellow]⚠️ No posts in response[/yellow]")
                    break
                
                # Check for duplicates
                new_posts = []
                duplicate_count = 0
                
                for post in posts:
                    post_id = post['data']['id']
                    if post_id in seen_post_ids:
                        duplicate_count += 1
                    else:
                        seen_post_ids.add(post_id)
                        new_posts.append(post)
                
                if duplicate_count == len(posts):
                    consecutive_duplicates += 1
                    console.print(f"[yellow]⚠️ All {len(posts)} posts are duplicates (consecutive: {consecutive_duplicates})[/yellow]")
                    if consecutive_duplicates >= max_consecutive_duplicates:
                        console.print("[yellow]⚠️ Too many consecutive duplicate batches, stopping[/yellow]")
                        break
                else:
                    consecutive_duplicates = 0
                    all_posts.extend(new_posts)
                    console.print(f"[green]✓ Added {len(new_posts)} new posts (total: {len(all_posts)})[/green]")
                
                # Get next page token
                after = data['data'].get('after')
                if not after:
                    console.print("[green]✓ Reached end of saved posts[/green]")
                    break
                    
                # Small delay to be respectful
                time.sleep(1)
                        
            except Exception as e:
                console.print(f"[red]❌ Error fetching posts: {str(e)}[/red]")
                break
        
        # Clean up driver if used
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
        
        if all_posts:
            # Save to saved.json file
            result = {
                "kind": "Listing",
                "data": {
                    "children": all_posts,
                    "after": None,
                    "before": None
                }
            }
            
            # Save to file
            saved_file_path = os.path.join(os.getcwd(), 'saved.json')
            try:
                with open(saved_file_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2, ensure_ascii=False)
                console.print(f"[green]✓ Saved {len(all_posts)} posts to {saved_file_path}[/green]")
            except Exception as e:
                console.print(f"[yellow]⚠️ Could not save to file: {str(e)}[/yellow]")
            
            return result
        else:
            console.print("[red]❌ No posts fetched[/red]")
            return None

    def _generate_filename(self, post_data: Dict[str, Any], url: str) -> str:
        parsed_url = urlparse(url)
        original_filename = os.path.basename(parsed_url.path)
        file_ext = os.path.splitext(original_filename)[1].lower()
        
        # Ensure file has a valid extension
        if not file_ext:
            if 'redgifs.com' in url:
                file_ext = '.mp4'
            elif post_data.get('is_video', False):
                file_ext = '.mp4'
            else:
                # Skip files without extensions
                return ''

        post_title = post_data.get('title', '').strip()
        post_id = post_data.get('id', '')

        clean_title = ''.join(c if c.isalnum() or c in '-_' else '_' for c in post_title)
        clean_title = clean_title[:50]

        if self.filename_style == 'basic':
            filename = f"{clean_title} --- {post_id}{file_ext}"
        elif self.filename_style == 'pretty':
            filename = f"{clean_title}{file_ext}"
        elif self.filename_style == 'advanced':
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            filename = f"{clean_title}-{post_id}-{url_hash}{file_ext}"
        else:
            filename = original_filename

        return os.path.join(self.output_dir, filename) if file_ext else ''

    def _file_exists_and_valid(self, filepath):
        """Check if file exists and has valid size (not empty or corrupted)"""
        if not os.path.exists(filepath):
            return False
        
        # Check if file size is reasonable (> 1KB for most media files)
        try:
            file_size = os.path.getsize(filepath)
            if file_size < 1024:  # Less than 1KB might be corrupted
                logging.debug(f"File {filepath} exists but is too small ({file_size} bytes), will re-download")
                return False
            return True
        except OSError:
            return False

    async def _download_file_with_retry(self, url: str, filename: str, task_id, retry_count: int = 0) -> bool:
        """Download file with retry logic and exponential backoff"""
        if url in self.processed_urls:
            logging.info(f"⏩ Already processed: {os.path.basename(filename)}")
            self.progress.update(task_id, advance=1)
            return True

        if self._file_exists_and_valid(filename):
            self.processed_urls.add(url)
            logging.info(f"⏩ Skipped: {os.path.basename(filename)}")
            self.progress.update(task_id, advance=1)
            return True

        async with self.download_semaphore:  # Control concurrent downloads
            temp_filename = f"{filename}.tmp"
            try:
                async with self.session.get(url) as response:
                    if response.status == 200:
                        async with aiofiles.open(temp_filename, 'wb') as f:
                            await f.write(await response.read())
                        os.rename(temp_filename, filename)
                        self.processed_urls.add(url)
                        logging.info(f"✓ Downloaded: {os.path.basename(filename)}")
                        self.progress.update(task_id, advance=1)
                        return True
                    elif response.status == 429:  # Rate limited
                        if retry_count < self.max_retries:
                            delay = self.base_delay * (2 ** retry_count) + random.uniform(0, 1)
                            logging.warning(f"⏳ Rate limited, retrying in {delay:.1f}s: {os.path.basename(filename)} (attempt {retry_count + 1}/{self.max_retries})")
                            await asyncio.sleep(delay)
                            return await self._download_file_with_retry(url, filename, task_id, retry_count + 1)
                        else:
                            logging.error(f"✗ Failed after {self.max_retries} retries: {os.path.basename(filename)} (Status 429)")
                            self.progress.update(task_id, advance=1)
                            return False
                    else:
                        logging.error(f"✗ Failed: {os.path.basename(filename)} (Status {response.status})")
                        self.progress.update(task_id, advance=1)
                        return False
            except Exception as e:
                if retry_count < self.max_retries:
                    delay = self.base_delay * (2 ** retry_count) + random.uniform(0, 1)
                    logging.warning(f"⏳ Error, retrying in {delay:.1f}s: {os.path.basename(filename)} - {str(e)} (attempt {retry_count + 1}/{self.max_retries})")
                    await asyncio.sleep(delay)
                    return await self._download_file_with_retry(url, filename, task_id, retry_count + 1)
                else:
                    logging.error(f"✗ Error after {self.max_retries} retries: {os.path.basename(filename)} ({str(e)})")
                    self.progress.update(task_id, advance=1)
                    return False

    async def _download_file(self, url: str, filename: str, task_id) -> bool:
        """Wrapper for download with retry logic"""
        return await self._download_file_with_retry(url, filename, task_id)

    def _cleanup_incomplete_downloads(self):
        for filename in os.listdir(self.output_dir):
            filepath = os.path.join(self.output_dir, filename)
            if os.path.isfile(filepath) and os.path.getsize(filepath) == 0:
                try:
                    os.remove(filepath)
                    logging.info(f"🧹 Cleaned up incomplete download: {filename}")
                except Exception as e:
                    logging.error(f"Failed to clean up {filename}: {str(e)}")

    def _load_processed_posts(self) -> set:
        """Load previously processed post IDs from file"""
        processed_file = os.path.join(self.output_dir, '.processed_posts.json')
        if os.path.exists(processed_file):
            try:
                with open(processed_file, 'r') as f:
                    return set(json.load(f))
            except Exception as e:
                logging.warning(f"Could not load processed posts file: {e}")
        return set()
    
    def _save_processed_posts(self):
        """Save processed post IDs to file"""
        processed_file = os.path.join(self.output_dir, '.processed_posts.json')
        try:
            with open(processed_file, 'w') as f:
                json.dump(list(self.processed_posts), f)
        except Exception as e:
            logging.warning(f"Could not save processed posts file: {e}")
    
    async def process_posts(self, saved_data):
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Load previously processed posts
        self.processed_posts = self._load_processed_posts()
        
        tasks = []
        total_urls = 0
        new_posts_count = 0
        skipped_posts_count = 0
        
        # Handle both list and dict formats for saved_data
        if isinstance(saved_data, list):
            posts = saved_data
        elif isinstance(saved_data, dict):
            posts = saved_data.get('data', {}).get('children', [])
        else:
            logging.error("Invalid saved_data format. Expected list or dict.")
            return
        
        # Get posts in reverse order (newest first)
        posts.reverse()
        
        # Filter out already processed posts and count URLs
        filtered_posts = []
        for post in posts:
            if 'data' in post:
                post_data = post['data']
                post_id = post_data.get('id')
                
                if post_id in self.processed_posts:
                    skipped_posts_count += 1
                    continue
                
                urls = self._get_media_urls(post_data)
                if urls:  # Only process posts with media
                    filtered_posts.append(post)
                    total_urls += len(urls)
                    new_posts_count += 1
                    self.processed_posts.add(post_id)  # Mark as processed
        
        if skipped_posts_count > 0:
            logging.info(f"⏩ Skipped {skipped_posts_count} already processed posts")
        
        if new_posts_count == 0:
            logging.info("ℹ️ No new posts with media to download")
            return
        
        logging.info(f"📥 Processing {new_posts_count} new posts with {total_urls} media files")
        
        with self.progress:
            task_id = self.progress.add_task("[dim cyan]⬇️  Downloading media", total=total_urls)
            
            for post in filtered_posts:
                if 'data' in post:
                    post_data = post['data']
                    urls = self._get_media_urls(post_data)
                    
                    for idx, url in enumerate(urls):
                        if url not in self.processed_urls:  # Skip already processed URLs
                            base_filename = self._generate_filename(post_data, url)
                            name, ext = os.path.splitext(base_filename)
                            
                            if len(urls) > 1:
                                filename = f"{name}_{idx + 1}{ext}"
                            else:
                                filename = base_filename
                            
                            if 'redgifs.com' in url:
                                tasks.append(self._download_redgifs_video(url, filename, task_id))
                            elif 'v.redd.it' in url:
                                tasks.append(self._download_reddit_video(url, filename, task_id))
                            else:
                                tasks.append(self._download_file(url, filename, task_id))
            
            # Process all downloads concurrently with semaphore control
            await asyncio.gather(*tasks)
            
            # Save processed posts to file
            self._save_processed_posts()

    async def _get_redgifs_token(self) -> str:
        async with self.session.get('https://api.redgifs.com/v2/auth/temporary') as response:
            if response.status == 200:
                data = await response.json()
                return data.get('token')
            raise Exception(f"Failed to get RedGifs token: Status {response.status}")

    async def _get_redgifs_video_url(self, gif_id: str, token: str) -> str:
        headers = {'Authorization': f'Bearer {token}'}
        async with self.session.get(f'https://api.redgifs.com/v2/gifs/{gif_id}', headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                urls = data.get('gif', {}).get('urls', {})
                # Try all available quality options
                for quality in ['hd', 'gif', 'sd', 'thumbnail']:
                    if url := urls.get(quality):
                        return url
            raise Exception(f"Failed to get RedGifs video URL: Status {response.status}")

    def _extract_redgifs_id(self, url: str) -> str:
        # Handle various RedGifs URL formats
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')
        
        # Handle watch URLs: /watch/gifname
        if '/watch/' in path:
            gif_id = path.split('/watch/')[-1].split('/')[0]
        # Handle direct URLs: /gifname or /ifr/gifname
        elif '/ifr/' in path:
            gif_id = path.split('/ifr/')[-1].split('/')[0]
        else:
            # Extract last path component
            gif_id = path.split('/')[-1]
        
        # Remove any file extensions or query parameters
        gif_id = gif_id.split('.')[0].split('?')[0]
        
        if not gif_id:
            raise ValueError(f"Could not extract RedGifs ID from URL: {url}")
        
        return gif_id

    async def _download_redgifs_video(self, url: str, filename: str, task_id) -> bool:
        try:
            gif_id = self._extract_redgifs_id(url)
            token = await self._get_redgifs_token()
            video_url = await self._get_redgifs_video_url(gif_id, token)
            if video_url:
                return await self._download_file(video_url, filename, task_id)
            return False
        except Exception as e:
            logging.error(f"✗ RedGifs Error: {os.path.basename(filename)} ({str(e)})")
            self.progress.update(task_id, advance=1)
            return False

    async def _download_reddit_video_with_retry(self, url: str, filename: str, task_id, retry_count: int = 0) -> bool:
        """Download Reddit video using yt-dlp with format fallback and retry logic"""
        filepath = os.path.join(self.output_dir, filename)
        
        # Check if already exists
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            logging.info(f"⏩ Skipped: {os.path.basename(filename)}")
            self.progress.update(task_id, advance=1)
            return True
        
        # Define format options in order of preference
        format_options = [
            'best[height<=720]/best',  # Prefer 720p or lower
            'best[height<=480]/best',  # Fallback to 480p
            'worst/best',              # Fallback to worst quality
            'best',                    # Final fallback
        ]
        
        for format_idx, format_selector in enumerate(format_options):
            try:
                # Configure yt-dlp options
                # Configure yt-dlp options with debug info
                ydl_opts = {
                    'outtmpl': filepath,
                    'quiet': not logging.getLogger().isEnabledFor(logging.DEBUG),
                    'no_warnings': not logging.getLogger().isEnabledFor(logging.DEBUG),
                    'verbose': logging.getLogger().isEnabledFor(logging.DEBUG),
                    'format': format_selector,
                    'ignoreerrors': False,
                    'extractaudio': False,
                    'retries': 2,
                    'fragment_retries': 2,
                    'logger': logging.getLogger('yt-dlp'),
                    'listformats': logging.getLogger().isEnabledFor(logging.DEBUG),  # List available formats in debug mode
                }
                
                logging.debug(f"yt-dlp attempting download with format: {format_selector}")
                logging.debug(f"yt-dlp options: {ydl_opts}")
                
                # Use yt-dlp to download the video
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    await asyncio.get_event_loop().run_in_executor(
                        None, ydl.download, [url]
                    )
                
                # Check if file was downloaded successfully
                if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                    logging.info(f"✓ Downloaded: {os.path.basename(filename)} (format: {format_selector})")
                    self.progress.update(task_id, advance=1)
                    return True
                    
            except yt_dlp.DownloadError as e:
                error_msg = str(e).lower()
                if 'requested format is not available' in error_msg or 'no video formats found' in error_msg:
                    if format_idx < len(format_options) - 1:
                        logging.warning(f"⚠️ Format '{format_selector}' not available for {os.path.basename(filename)}, trying next format...")
                        continue
                    else:
                        logging.error(f"✗ No available formats for: {os.path.basename(filename)}")
                        self.progress.update(task_id, advance=1)
                        return False
                elif '429' in error_msg or 'rate limit' in error_msg:
                    if retry_count < self.max_retries:
                        delay = self.base_delay * (2 ** retry_count) + random.uniform(0, 1)
                        logging.warning(f"⏳ Rate limited, retrying in {delay:.1f}s: {os.path.basename(filename)} (attempt {retry_count + 1}/{self.max_retries})")
                        await asyncio.sleep(delay)
                        return await self._download_reddit_video_with_retry(url, filename, task_id, retry_count + 1)
                    else:
                        logging.error(f"✗ Rate limited after {self.max_retries} retries: {os.path.basename(filename)}")
                        self.progress.update(task_id, advance=1)
                        return False
                else:
                    logging.error(f"✗ yt-dlp error: {os.path.basename(filename)} - {str(e)}")
                    if format_idx < len(format_options) - 1:
                        continue
                    else:
                        self.progress.update(task_id, advance=1)
                        return False
                        
            except Exception as e:
                if retry_count < self.max_retries:
                    delay = self.base_delay * (2 ** retry_count) + random.uniform(0, 1)
                    logging.warning(f"⏳ Error, retrying in {delay:.1f}s: {os.path.basename(filename)} - {str(e)} (attempt {retry_count + 1}/{self.max_retries})")
                    await asyncio.sleep(delay)
                    return await self._download_reddit_video_with_retry(url, filename, task_id, retry_count + 1)
                else:
                    logging.error(f"✗ Reddit Video Error after {self.max_retries} retries: {os.path.basename(filename)} ({str(e)})")
                    self.progress.update(task_id, advance=1)
                    return False
        
        # If we get here, all formats failed
        logging.error(f"✗ All format options failed for: {os.path.basename(filename)}")
        self.progress.update(task_id, advance=1)
        return False

    async def _download_reddit_video(self, url: str, filename: str, task_id) -> bool:
        """Wrapper for Reddit video download with retry logic"""
        return await self._download_reddit_video_with_retry(url, filename, task_id)

def show_help():
    console.print("\n[bold cyan]Reddit Saved Downloader[/bold cyan] 🎥")
    console.print("\n[yellow]Usage:[/yellow]")
    console.print("# Using local file:")
    console.print("python reddit_saved_downloader.py -i saved.json -o ./downloads")
    console.print("\n# Using Reddit cookies:")
    console.print("python reddit_saved_downloader.py -r YOUR_REDDIT_SESSION -o ./downloads")
    console.print("\n[yellow]Available options:[/yellow]")
    console.print("  -i, --input           [green]Path to your saved.json file[/green]")
    console.print("  -r, --reddit-session  [green]Reddit session cookie (reddit_session value)[/green]")
    console.print("  -t, --token-v2        [green]Reddit token_v2 cookie (optional)[/green]")
    console.print("  -o, --output          [green]Output directory for downloads (default: ./downloads)[/green]")
    console.print("  --concurrent          [green]Maximum number of concurrent downloads (default: 5)[/green]")
    console.print("  -s, --style           [green]Filename style: basic, pretty, or advanced (default: basic)[/green]")
    console.print("  -l, --log             [green]Path to log file (optional)[/green]")
    console.print("\n[yellow]Examples:[/yellow]")
    console.print("python reddit_saved_downloader.py -i saved.json -o ./downloads --concurrent 10 -s advanced")
    console.print("python reddit_saved_downloader.py -r eyJhbGc6... -t eyJhbGc6... -o ./downloads\n")

# Global variable to track if shutdown is in progress
shutdown_in_progress = False

def signal_handler(sig, frame):
    global shutdown_in_progress
    if shutdown_in_progress:
        console.print("\n[red]Force quit! Exiting immediately...[/red]")
        os._exit(1)
    
    shutdown_in_progress = True
    console.print("\n[yellow]Received interrupt signal (Ctrl+C). Gracefully shutting down...[/yellow]")
    console.print("[dim]Press Ctrl+C again to force quit[/dim]")
    
    # Set a timer for force quit if graceful shutdown takes too long
    import threading
    def force_quit():
        import time
        time.sleep(5)  # Wait 5 seconds for graceful shutdown
        if shutdown_in_progress:
            console.print("\n[red]Graceful shutdown timed out. Force quitting...[/red]")
            os._exit(1)
    
    threading.Thread(target=force_quit, daemon=True).start()
    sys.exit(0)

def main():
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, signal_handler)
    
    if len(sys.argv) == 1:
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(description='Download media from Reddit saved posts')
    
    # Create mutually exclusive group for input methods
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--input', '-i',
                      help='Path to the saved.json file')
    
    # Reddit authentication options
    reddit_group = input_group.add_argument_group('reddit_auth')
    input_group.add_argument('--reddit-session', '-r',
                      help='Reddit session cookie (reddit_session value)')
    
    parser.add_argument('--token-v2', '-t',
                      help='Reddit token_v2 cookie (optional, improves reliability)')
    
    parser.add_argument('--output', '-o', default='./downloads',
                      help='Output directory for downloaded files')
    parser.add_argument('--concurrent', '--max-concurrent', type=int, default=5,
                      help='Maximum number of concurrent downloads')
    parser.add_argument('--style', '-s', choices=['basic', 'pretty', 'advanced'],
                      default='basic', help='Filename style (basic: title-id, pretty: title, advanced: title-id-hash)')
    parser.add_argument('--log', '-l', help='Path to log file')
    parser.add_argument('--debug', '-d', action='store_true', help='Enable debug logging for troubleshooting')

    args = parser.parse_args()

    saved_data = None
    
    if args.input:
        # Load from local file
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                saved_data = json.load(f)
        except FileNotFoundError:
            console.print(f"[red]❌ File not found: {args.input}[/red]")
            sys.exit(1)
        except json.JSONDecodeError as e:
            console.print(f"[red]❌ Invalid JSON format in {args.input}: {str(e)}[/red]")
            sys.exit(1)
        except PermissionError:
            console.print(f"[red]❌ Permission denied accessing {args.input}[/red]")
            sys.exit(1)
        except Exception as e:
            console.print(f"[red]❌ Error reading {args.input}: {str(e)}[/red]")
            sys.exit(1)
            
        # Validate saved_data content
        if not saved_data:
            console.print(f"[red]❌ Empty file: {args.input}[/red]")
            sys.exit(1)
        
        if isinstance(saved_data, list) and len(saved_data) == 0:
            console.print(f"[red]❌ No posts found in {args.input}[/red]")
            sys.exit(1)
        
        if isinstance(saved_data, dict) and not saved_data.get('data', {}).get('children'):
            console.print(f"[red]❌ No posts found in {args.input}[/red]")
            sys.exit(1)
    
    elif args.reddit_session:
        # Fetch from Reddit API using session cookie
        console.print("[bold blue]🌐 Fetching saved posts from Reddit...[/bold blue]")
        
        # Construct cookie string from individual values
        cookie_parts = [f"reddit_session={args.reddit_session}"]
        if args.token_v2:
            cookie_parts.append(f"token_v2={args.token_v2}")
        
        cookies_string = "; ".join(cookie_parts)
        
    downloader = RedditMediaDownloader(args.output, args.concurrent, args.style, args.log, args.debug)
    
    async def run():
        await downloader.init_session()
        try:
            if args.reddit_session:
                saved_data = await downloader.fetch_saved_posts_from_reddit(cookies_string)
                if not saved_data:
                    console.print("[red]❌ No saved posts found or failed to fetch from Reddit[/red]")
                    return
            
            console.print("[bold green]🚀 Starting download process...[/bold green]")
            await downloader.process_posts(saved_data)
            console.print("[bold green]✨ Download process completed![/bold green]")
        finally:
            await downloader.close_session()

    asyncio.run(run())

if __name__ == '__main__':
    main()