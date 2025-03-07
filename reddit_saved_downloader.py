#!/usr/bin/env python3

import argparse
import json
import os
import sys
import asyncio
import aiohttp
import aiofiles
import logging
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.console import Console
from rich.logging import RichHandler
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any

console = Console()

class RedditMediaDownloader:
    def __init__(self, output_dir: str, max_concurrent: int = 5, filename_style: str = 'basic', log_file: str = None):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)  # Create output directory if it doesn't exist
        self.max_concurrent = max_concurrent
        self.filename_style = filename_style
        self.session = None
        self.processed_urls = set()  # Track processed URLs
        self.download_semaphore = None  # Control concurrent downloads
        
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
        if log_file:
            logging.basicConfig(
                level=logging.INFO,
                format=log_format,
                handlers=[
                    RichHandler(console=console, rich_tracebacks=True, show_path=False),
                    logging.FileHandler(log_file)
                ]
            )
        else:
            logging.basicConfig(
                level=logging.INFO,
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
        
        # Check for direct image/gif URLs
        if 'url_overridden_by_dest' in post:
            url = post['url_overridden_by_dest']
            ext = os.path.splitext(url)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.mp4', '.webm', '.gifv']:
                logging.info(f"📸 Processing Direct Media: {post.get('title', 'Untitled')}")
                urls.append(url)
        
        return urls

    async def init_session(self):
        self.session = aiohttp.ClientSession()
        self.download_semaphore = asyncio.Semaphore(self.max_concurrent)  # Initialize semaphore

    async def close_session(self):
        if self.session:
            await self.session.close()

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

    async def _download_file(self, url: str, filename: str, task_id) -> bool:
        if url in self.processed_urls:
            logging.info(f"⏩ Already processed: {os.path.basename(filename)}")
            self.progress.update(task_id, advance=1)
            return True

        if os.path.exists(filename):
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
                    else:
                        logging.error(f"✗ Failed: {os.path.basename(filename)} (Status {response.status})")
                        self.progress.update(task_id, advance=1)
                        return False
            except Exception as e:
                logging.error(f"✗ Error: {os.path.basename(filename)} ({str(e)})")
                self.progress.update(task_id, advance=1)
                return False

    def _cleanup_incomplete_downloads(self):
        for filename in os.listdir(self.output_dir):
            filepath = os.path.join(self.output_dir, filename)
            if os.path.isfile(filepath) and os.path.getsize(filepath) == 0:
                try:
                    os.remove(filepath)
                    logging.info(f"🧹 Cleaned up incomplete download: {filename}")
                except Exception as e:
                    logging.error(f"Failed to clean up {filename}: {str(e)}")

    async def process_posts(self, saved_data: Dict[str, Any]):
        os.makedirs(self.output_dir, exist_ok=True)
        tasks = []
        total_urls = 0
        
        # Get posts in reverse order (newest first)
        posts = saved_data.get('data', {}).get('children', [])
        posts.reverse()
        
        # Count total URLs first
        for post in posts:
            if 'data' in post:
                urls = self._get_media_urls(post['data'])
                total_urls += len(urls)
        
        with self.progress:
            task_id = self.progress.add_task("[dim cyan]⬇️  Downloading media", total=total_urls)
            
            for post in posts:
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
                            else:
                                tasks.append(self._download_file(url, filename, task_id))
            
            # Process all downloads concurrently with semaphore control
            await asyncio.gather(*tasks)

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
        # Handle both watch URLs and direct URLs
        path = urlparse(url).path.rstrip('/')
        if '/watch/' in path:
            return path.split('/')[-1]
        return path.split('/')[-1]

    def _extract_redgifs_id(self, url: str) -> str:
        path = urlparse(url).path
        return path.split('/')[-1]

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

def show_help():
    console.print("\n[bold cyan]Reddit Saved Downloader[/bold cyan] 🎥")
    console.print("\n[yellow]Usage:[/yellow]")
    console.print("python reddit_saved_downloader.py -i saved.json -o ./downloads")
    console.print("\n[yellow]Available options:[/yellow]")
    console.print("  -i, --input      [green]Path to your saved.json file (required)[/green]")
    console.print("  -o, --output     [green]Output directory for downloads (default: ./downloads)[/green]")
    console.print("  -c, --concurrent [green]Maximum number of concurrent downloads (default: 5)[/green]")
    console.print("  -s, --style      [green]Filename style: basic, pretty, or advanced (default: basic)[/green]")
    console.print("  -l, --log        [green]Path to log file (optional)[/green]")
    console.print("\n[yellow]Example:[/yellow]")
    console.print("python reddit_saved_downloader.py -i saved.json -o ./downloads -c 10 -s advanced -l download.log\n")

def signal_handler(sig, frame):
    console.print("\n[yellow]Received interrupt signal. Cleaning up...[/yellow]")
    sys.exit(0)

def main():
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    
    if len(sys.argv) == 1:
        show_help()
        sys.exit(0)

    parser = argparse.ArgumentParser(description='Download media from Reddit saved posts')
    parser.add_argument('--input', '-i', required=True,
                      help='Path to the saved.json file')
    parser.add_argument('--output', '-o', default='./downloads',
                      help='Output directory for downloaded files')
    parser.add_argument('--concurrent', '-c', type=int, default=5,
                      help='Maximum number of concurrent downloads')
    parser.add_argument('--style', '-s', choices=['basic', 'pretty', 'advanced'],
                      default='basic', help='Filename style (basic: title-id, pretty: title, advanced: title-id-hash)')
    parser.add_argument('--log', '-l', help='Path to log file')

    args = parser.parse_args()

    try:
        with open(args.input, 'r') as f:
            saved_data = json.load(f)
    except Exception as e:
        console.print(f"[red]❌ Error reading saved.json: {str(e)}[/red]")
        sys.exit(1)

    downloader = RedditMediaDownloader(args.output, args.concurrent, args.style, args.log)
    
    async def run():
        await downloader.init_session()
        try:
            console.print("[bold green]🚀 Starting download process...[/bold green]")
            await downloader.process_posts(saved_data)
            console.print("[bold green]✨ Download process completed![/bold green]")
        finally:
            await downloader.close_session()

    asyncio.run(run())

if __name__ == '__main__':
    main()