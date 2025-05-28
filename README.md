# !! THIS ISNT FINISHED.. DO NOT USE IT !!

# Reddit Saved Downloader

[![GitHub](https://img.shields.io/github/license/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader)
[![GitHub stars](https://img.shields.io/github/stars/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader/stargazers)
[![GitHub issues](https://img.shields.io/github/issues/M1noa/reddit-saved-downloader)](https://github.com/M1noa/reddit-saved-downloader/issues)

A Python-based CLI tool to download media from your Reddit saved posts!

## Features

- 📥 Download media from your Reddit saved posts
- 🖼️ Supports multiple media types (images, GIFs, videos)
- 🎥 Handles Reddit-hosted videos and RedGifs
- 🚀 Concurrent downloads for better performance
- 📁 Customizable filename formats
- 💾 Organized local storage of your saved media

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

## Usage

Run the downloader with basic settings:
```bash
python reddit_saved_downloader.py -i saved.json -o ./downloads
```

Available options:
```bash
-i, --input      Path to your saved.json file (required)
-o, --output     Output directory for downloads (default: ./downloads)
-c, --concurrent Maximum number of concurrent downloads (default: 5)
-s, --style      Filename style: basic, pretty, or advanced (default: basic)
-l, --log        Path to log file (optional)
```

### Example
```bash
python reddit_saved_downloader.py -i saved.json -o ./downloads -c 10 -s advanced -l download.log
```

### Features
- 🚀 Asynchronous downloads for better performance
- 📊 Progress bar with real-time status
- 🎨 Colored output for better visibility
- 📝 Optional logging to file
- 🔄 Concurrent downloads with customizable limit
- 🏷️ Multiple filename styles
```

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
