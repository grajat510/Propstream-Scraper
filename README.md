# PropStream Contact Scraper

This Python script automates the process of logging into PropStream.com, uploading a list of properties, creating a contact group, and then scraping contact information (name, phone number, email) from the imported listings using a direct HTTP approach.

## Features

- Automatically logs into PropStream with provided credentials
- Prompts user to select a CSV or Excel file to import
- Creates a new contact group with timestamp for uniqueness
- Interacts with PropStream's web interface via direct HTTP requests
- Places skip tracing orders through the API interface
- Scrapes contact information (name, phone, email)
- Saves results to a CSV file

## Requirements

- Python 3.7+
- The dependencies listed in `requirements.txt`

## Installation

1. Clone this repository or download the script files
2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the root directory with your PropStream credentials:

```
PROPSTREAM_USERNAME=your_email@example.com
PROPSTREAM_PASSWORD=your_password_here
```

## Usage

1. Prepare your property list in CSV or Excel format
2. Ensure your `.env` file is properly configured with your password
3. Run the script:

```bash
python propstream_html_scraper.py
```

4. When prompted, select your property list file
5. The script will automate the entire process and save the results to `propstream_contacts.csv`

## How It Works

Unlike Selenium-based automation, this script:
1. Uses direct HTTP requests to interact with PropStream's web interface
2. Parses HTML responses with BeautifulSoup
3. Simulates normal browser behavior without needing a browser driver
4. Handles file uploads via multipart form data
5. Extracts contact information from both JSON and HTML responses

## Important Notes

- The script uses your PropStream credentials from the .env file
- You must have a valid PropStream subscription for this script to work
- The script may need adjustments if PropStream changes their website structure or API endpoints
- Never commit your .env file to git repositories

## Troubleshooting

- If login fails, check your credentials or PropStream's login page structure
- For upload issues, verify your file format is compatible
- If contact data extraction fails, the script saves HTML responses for debugging
- Check the log file `propstream_scraper.log` for detailed error information 