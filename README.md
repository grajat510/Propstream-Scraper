# PropStream Scraping Tools

This repository contains tools to automate the process of working with PropStream.com, including uploading property lists, creating contact groups, and scraping contact information.

## Available Tools

### 1. Direct HTTP Scraper (`propstream_html_scraper.py`)

This script uses direct HTTP requests to interact with PropStream's web interface.

**Features:**
- Automatically logs into PropStream with provided credentials
- Prompts user to select a CSV or Excel file to import
- Creates a new contact group with timestamp for uniqueness
- Interacts with PropStream's web interface via direct HTTP requests
- Places skip tracing orders through the API interface
- Scrapes contact information (name, phone, email)
- Saves results to a CSV file

### 2. Playwright Browser Automation (`propstream_playwright_scraper.py`)

This script uses Playwright to automate a real browser for a more robust solution, particularly useful for complex UI interactions.

**Features:**
- Full browser automation with Playwright
- Handles JavaScript-heavy pages effectively
- Uploads CSV files and creates contact groups
- Places skip tracing orders through the UI
- Waits for order completion and extracts data
- Includes robust error handling and screenshots for debugging
- Supports a mock mode for testing without accessing PropStream

## Requirements

- Python 3.7+
- The dependencies listed in `requirements.txt`
- For Playwright: browser engines installed via `python -m playwright install`

## Installation

1. Clone this repository or download the script files
2. Install the required dependencies:

```bash
pip install -r requirements.txt
python -m playwright install  # Only needed for the Playwright script
```

3. Create a `.env` file in the root directory with your PropStream credentials:

```
PROPSTREAM_USERNAME=your_email@example.com
PROPSTREAM_PASSWORD=your_password_here
```

## Usage

### HTML Scraper

```bash
python propstream_html_scraper.py
```

### Playwright Browser Automation

```bash
# Regular mode with browser visible
python propstream_playwright_scraper.py

# Run in headless mode (browser not visible)
python propstream_playwright_scraper.py --headless

# Use mock mode for testing (doesn't access PropStream)
python propstream_playwright_scraper.py --mock

# Specify a different CSV file to upload
python propstream_playwright_scraper.py --file your_file.csv
```

## How It Works

The HTML scraper:
1. Uses direct HTTP requests to interact with PropStream's web interface
2. Parses HTML responses with BeautifulSoup
3. Simulates normal browser behavior without needing a browser driver

The Playwright scraper:
1. Controls a real browser (Chrome/Chromium by default)
2. Interacts with the UI just like a human would
3. Takes screenshots at key points for debugging
4. Handles JavaScript-rendered content that the HTTP scraper cannot

## Important Notes

- The scripts use your PropStream credentials from the .env file
- You must have a valid PropStream subscription for these scripts to work
- The scripts may need adjustments if PropStream changes their website structure
- Never commit your .env file to git repositories

## Troubleshooting

- If login fails, check your credentials or PropStream's login page structure
- For upload issues, verify your file format is compatible
- If contact data extraction fails, the scripts save HTML responses for debugging
- Check the log file `propstream_scraper.log` for detailed error information
- For the Playwright script, examine the screenshot files (like `login_error.png`, `dashboard.png`, etc.) for visual debugging 