# Reddit Saved Downloader

[![GitHub](https://img.shields.io/github/license/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader)
[![GitHub stars](https://img.shields.io/github/stars/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader/issues)

A Python-based CLI tool to download media from your Reddit saved posts!

## Features

- 📥 Download media from your Reddit saved posts
- 🍪 **NEW**: Direct fetching from Reddit using cookies (no manual export needed!)
- 🛡️ **Enhanced Cloudflare bypass** with multiple methods:
  - Primary: `undetected-chromedriver` with Selenium for maximum stealth
  - Fallback: `cloudscraper` with browser emulation
- 🖼️ Supports multiple media types (images, GIFs, videos)
- 🎥 Handles Reddit-hosted videos (v.redd.it) and RedGifs
- 🚀 Concurrent downloads for better performance
- 📁 Customizable filename formats
- 💾 Organized local storage of your saved media
- 🔄 Automatic pagination and duplicate detection

## Installation

### Prerequisites

- Python 3.7 or higher
- pip (Python package installer)

### Setup

```bash
# Clone the repository
git clone https://github.com/M1noa/reddit-saved-downloader.git
cd reddit-saved-downloader

# Install dependencies
pip install -r requirements.txt
```

### Enhanced Cloudflare Bypass

For maximum effectiveness against Reddit's Cloudflare protection, the tool uses:

- **Primary method**: `undetected-chromedriver` + Selenium (automatically installed)
- **Fallback method**: `cloudscraper` with browser emulation

The tool will automatically attempt the most effective method first and fall back if needed.

## Usage

There are two ways to use this tool:

### Method 1: Using Reddit Cookies (Recommended)

Fetch your saved posts directly from Reddit using your browser cookies:

```bash
python reddit_saved_downloader.py --reddit-session "your_reddit_session_value" -o ./downloads
```

### Method 2: Using Local saved.json File

Use a pre-exported saved.json file:

```bash
python reddit_saved_downloader.py --input saved.json -o ./downloads
```

## Available Options

```bash
# Input methods (choose one):
-i, --input           Path to your saved.json file
-r, --reddit-session  Reddit session cookie (reddit_session value)

# Optional Reddit authentication:
-t, --token-v2        Reddit token_v2 cookie (improves reliability)

# Other options:
-o, --output          Output directory for downloads (default: ./downloads)
--concurrent          Maximum number of concurrent downloads (default: 5)
-s, --style          Filename style: basic, pretty, or advanced (default: basic)
-l, --log            Path to log file (optional)
```

## How to Get Reddit Cookies

### Step 1: Open Reddit in Your Browser
1. Go to [reddit.com](https://reddit.com) and make sure you're logged in
2. Navigate to your saved posts: `https://reddit.com/user/YOUR_USERNAME/saved`

### Step 2: Open Developer Tools
- **Chrome/Edge**: Press `F12` or `Ctrl+Shift+I`
- **Firefox**: Press `F12` or `Ctrl+Shift+I`
- **Safari**: Press `Cmd+Option+I` (enable Developer menu first)

### Step 3: Extract Specific Cookies

#### Method A: Using Network Tab (Recommended)
1. Click on the **Network** tab in Developer Tools
2. Refresh the page (`F5` or `Ctrl+R`)
3. Look for a request to `saved.json` or any Reddit API request
4. Click on the request and find the **Request Headers** section
5. In the `Cookie:` header, find and copy the `reddit_session` value
6. Optionally, also copy the `token_v2` value for better reliability

#### Method B: Using Console
1. Click on the **Console** tab in Developer Tools
2. Type: `document.cookie` and press Enter
3. From the output, find and copy the `reddit_session` value
4. Optionally, also copy the `token_v2` value

### Step 4: Use the Cookies

The `reddit_session` value should look something like this:
```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ...
```

Use it with the tool:
```bash
# Basic usage (reddit_session only)
python reddit_saved_downloader.py --reddit-session "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." -o ./downloads

# With token_v2 for better reliability
python reddit_saved_downloader.py --reddit-session "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." --token-v2 "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..." -o ./downloads
```

**Important Notes:**
- Keep your cookies private and secure
- Cookies expire after some time (usually weeks/months)
- If downloads fail, try getting fresh cookies
- The tool automatically saves fetched posts to `saved.json` for future use

## Examples

### Using Reddit Session (Recommended)
```bash
# Basic usage with reddit session
python reddit_saved_downloader.py --reddit-session "your_reddit_session_here" -o ./downloads

# With token_v2 and custom settings
python reddit_saved_downloader.py --reddit-session "your_reddit_session_here" --token-v2 "your_token_v2_here" -o ./my_media --concurrent 10 -s advanced -l download.log
```

### Using Local File
```bash
# Basic usage with local file
python reddit_saved_downloader.py --input saved.json -o ./downloads

# With custom settings
python reddit_saved_downloader.py --input saved.json -o ./downloads --concurrent 10 -s advanced -l download.log
```

## Features
- 🚀 Asynchronous downloads for better performance
- 📊 Progress bar with real-time status
- 🎨 Colored output for better visibility
- 📝 Optional logging to file
- 🔄 Concurrent downloads with customizable limit
- 🏷️ Multiple filename styles
- 🍪 Direct Reddit API integration with cookie authentication
- 🔄 Automatic pagination through all saved posts
- 🚫 Duplicate detection to avoid re-downloading

## Contributing

Contributions are welcome! Here's how you can contribute:

1. **Fork** the repository on GitHub
2. **Clone** your fork to your local machine
3. **Create a branch** for your feature or bugfix
4. **Commit** your changes
5. **Push** your branch to your fork
6. Submit a **Pull Request** to the main repository

### Guidelines

- Follow Python best practices and PEP 8 style guide
- Add comments for complex logic
- Update documentation for any new features
- Write descriptive commit messages

## License

This project is licensed under the MIT License

---

[```made with <3 by Minoa```](https://github.com/M1noa)
