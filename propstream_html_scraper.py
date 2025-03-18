import os
import time
import base64
import json
import csv
import logging
import re
import requests
from bs4 import BeautifulSoup
from tkinter import Tk, filedialog, messagebox
from urllib.parse import urljoin, urlparse, parse_qs
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("propstream_scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PropStreamHTMLScraper:
    def __init__(self):
        self.username = "mikerossgrandrapidsrealty@gmail.com"
        # Get password from environment variable instead of hardcoding
        self.password = os.environ.get("PROPSTREAM_PASSWORD")
        self.base_url = "https://app.propstream.com"
        self.login_url = "https://login.propstream.com/"
        self.session = requests.Session()
        self.scraped_data = []
        self.setup_session()
        
    def setup_session(self):
        """Set up the requests session with common headers"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.base_url,
            'Referer': self.base_url,
        })
        logger.info("Session initialized with headers")
    
    def login(self):
        """Login to PropStream"""
        try:
            logger.info("Logging in to PropStream...")
            
            # First, get the login page to capture any necessary cookies and CSRF tokens
            login_response = self.session.get(self.login_url)
            
            if login_response.status_code != 200:
                logger.error(f"Failed to get login page: {login_response.status_code}")
                return False
                
            # Save the login page HTML for debugging
            with open("login_page.html", "w", encoding="utf-8") as f:
                f.write(login_response.text)
            logger.info("Saved login page HTML for debugging")
                
            # Parse the login page to extract any required tokens
            login_soup = BeautifulSoup(login_response.text, 'html.parser')
            
            # Prepare login data - the form shows that passwords are base64 encoded
            # as seen in the JavaScript: f.password.value = btoa(f.password.value);
            login_data = {
                'username': self.username,
                'password': base64.b64encode(self.password.encode('utf-8')).decode('utf-8')
            }
            
            # The form doesn't have an action, so it posts to the current URL
            login_post_url = self.login_url
            
            # Submit the login form
            logger.info(f"Submitting login form to: {login_post_url}")
            login_response = self.session.post(
                login_post_url,
                data=login_data,
                allow_redirects=True
            )
            
            # Save the login response for debugging
            with open("login_response.html", "w", encoding="utf-8") as f:
                f.write(login_response.text)
            logger.info("Saved login response to login_response.html for debugging")
            
            # Check for successful login
            if login_response.url and self.base_url in login_response.url:
                logger.info("Login successful based on redirect URL")
                return True
                
            # The response might redirect to app.propstream.com with the token in the URL
            if "app.propstream.com" in login_response.url:
                parsed_url = urlparse(login_response.url)
                query_params = parse_qs(parsed_url.query)
                
                if 'token' in query_params:
                    token = query_params['token'][0]
                    self.session.headers.update({
                        'Authorization': f'Bearer {token}'
                    })
                    logger.info("Extracted token from redirect URL")
                    return True
            
            # If we didn't redirect to app.propstream.com, look for a token in the response
            if login_response.status_code == 200 and "token" in login_response.text:
                logger.info("Found token in login response, extracting...")
                token_match = re.search(r'"token":"([^"]+)"', login_response.text)
                
                if token_match:
                    token = token_match.group(1)
                    self.session.headers.update({
                        'Authorization': f'Bearer {token}'
                    })
                    logger.info("Added token to session headers")
                    return True
            
            # Try to access the dashboard to verify login
            # Different apps might have different dashboard URLs
            dashboard_urls = [
                f"{self.base_url}/dashboard",
                f"{self.base_url}/home",
                f"{self.base_url}/app"
            ]
            
            for dashboard_url in dashboard_urls:
                logger.info(f"Trying dashboard URL: {dashboard_url}")
                dash_response = self.session.get(dashboard_url)
                
                if dash_response.status_code == 200 and ("logout" in dash_response.text.lower() or "account" in dash_response.text.lower()):
                    logger.info(f"Login confirmed via dashboard access: {dashboard_url}")
                    return True
                    
                # Save this dashboard response for debugging
                with open(f"dashboard_response_{dashboard_url.split('/')[-1]}.html", "w", encoding="utf-8") as f:
                    f.write(dash_response.text)
                    
            # Try direct API access to verify login
            user_info_url = f"{self.base_url}/api/account/user-info"
            try:
                user_info_response = self.session.get(user_info_url)
                if user_info_response.status_code == 200:
                    logger.info("Login verified through API access")
                    return True
            except Exception as e:
                logger.warning(f"Failed to verify login through API: {str(e)}")
                
            logger.error("Login failed. Could not access dashboard or API.")
            return False
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def select_file_to_upload(self):
        """Open file dialog to select a file"""
        try:
            logger.info("Opening file dialog...")
            
            # Create a hidden Tkinter root window
            root = Tk()
            root.withdraw()
            
            # Ask user to select file
            file_path = filedialog.askopenfilename(
                title="Select File to Upload",
                filetypes=[("CSV files", "*.csv"), ("Excel files", "*.xls;*.xlsx")]
            )
            
            if not file_path:
                logger.warning("No file selected. Aborting operation.")
                return None
                
            logger.info(f"Selected file: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error selecting file: {str(e)}")
            return None
    
    def upload_file_and_create_group(self, file_path):
        """Upload file and create a new group"""
        try:
            logger.info("Accessing import list page...")
            
            # Navigate to import list page
            import_url = f"{self.base_url}/contacts"
            import_response = self.session.get(import_url)
            
            if import_response.status_code != 200:
                logger.error(f"Failed to access import page: {import_response.status_code}")
                return None
            
            # Save the import page for debugging
            with open("import_page.html", "w", encoding="utf-8") as f:
                f.write(import_response.text)
            logger.info("Saved import page to import_page.html for debugging")
            
            # Parse page to look for upload form or endpoint
            import_soup = BeautifulSoup(import_response.text, 'html.parser')
            
            # Try to find the form or API endpoint for uploads
            upload_url = None
            csrf_token = None
            
            # 1. Look for form with file input
            upload_form = import_soup.find('form', {'enctype': 'multipart/form-data'})
            if upload_form:
                form_action = upload_form.get('action')
                if form_action:
                    upload_url = urljoin(self.base_url, form_action)
                    logger.info(f"Found upload form with action: {upload_url}")
                
                # Look for CSRF token
                csrf_input = upload_form.find('input', {'name': '_csrf'}) or upload_form.find('input', {'name': 'csrf'})
                if csrf_input:
                    csrf_token = csrf_input.get('value')
            
            # 2. If no form found, look for JavaScript with upload URL
            if not upload_url:
                script_tags = import_soup.find_all('script')
                for script in script_tags:
                    if script.string and ('upload' in script.string or 'import' in script.string):
                        url_match = re.search(r'["\']((?:/api)?/(?:contacts/)?(?:upload|import))["\'"]', script.string)
                        if url_match:
                            upload_url = urljoin(self.base_url, url_match.group(1))
                            logger.info(f"Found upload URL in script: {upload_url}")
                            break
            
            # 3. If still not found, use default API endpoints
            if not upload_url:
                # Try common endpoints
                upload_url = f"{self.base_url}/api/contacts/upload"
                logger.info(f"Using default upload URL: {upload_url}")
            
            # Prepare the file for upload
            file_name = os.path.basename(file_path)
            content_type = 'text/csv' if file_path.endswith('.csv') else 'application/vnd.ms-excel'
            
            with open(file_path, 'rb') as file:
                file_content = file.read()
            
            # Create multipart form data for the file upload
            try:
                from requests_toolbelt.multipart.encoder import MultipartEncoder
                
                multipart_data = MultipartEncoder(
                    fields={
                        'file': (file_name, file_content, content_type),
                        'fileName': file_name,
                        'contentType': content_type
                    }
                )
                
                headers = {
                    'Content-Type': multipart_data.content_type
                }
                
                if csrf_token:
                    headers['X-CSRF-TOKEN'] = csrf_token
                
                # Upload the file
                logger.info(f"Uploading file to {upload_url}...")
                upload_response = self.session.post(
                    upload_url,
                    data=multipart_data,
                    headers=headers
                )
                
            except ImportError:
                # Fallback if requests_toolbelt is not available
                logger.warning("requests_toolbelt not available, using basic multipart upload")
                
                files = {
                    'file': (file_name, file_content, content_type)
                }
                
                data = {
                    'fileName': file_name,
                    'contentType': content_type
                }
                
                if csrf_token:
                    data['_csrf'] = csrf_token
                
                # Upload the file
                logger.info(f"Uploading file to {upload_url}...")
                upload_response = self.session.post(
                    upload_url,
                    files=files,
                    data=data
                )
            
            # Save the upload response for debugging
            with open("upload_response.html", "w", encoding="utf-8") as f:
                f.write(upload_response.text)
            logger.info("Saved upload response to upload_response.html for debugging")
            
            # Extract the file ID from the response
            file_id = None
            
            try:
                content_type = upload_response.headers.get('Content-Type', '')
                if content_type and 'application/json' in content_type:
                    upload_data = upload_response.json()
                    file_id = upload_data.get('id') or upload_data.get('fileId')
                
                if not file_id and upload_response.status_code in [200, 201, 202]:
                    # Try to extract from response URL or text
                    if 'Location' in upload_response.headers:
                        location = upload_response.headers['Location']
                        file_id = location.split('/')[-1]
                    else:
                        # Search for ID in response text
                        id_match = re.search(r'"id"[:\s]+"([^"]+)"', upload_response.text)
                        if id_match:
                            file_id = id_match.group(1)
                        else:
                            # Generate a timestamp as fallback ID
                            file_id = str(int(time.time()))
                            logger.warning(f"Using timestamp as file ID: {file_id}")
            except Exception as e:
                logger.error(f"Error parsing upload response: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                file_id = str(int(time.time()))
                logger.warning(f"Using timestamp as fallback file ID: {file_id}")
            
            # Now create a group for the uploaded contacts
            group_name = f"Foreclosures_scraping_{time.strftime('%Y%m%d_%H%M%S')}"
            logger.info(f"Creating group: {group_name}")
            
            # Find group creation endpoint
            group_url = f"{self.base_url}/api/contact-groups"
            
            # Prepare group creation data
            group_data = {
                "name": group_name,
                "fileId": file_id,
                "type": "new"
            }
            
            # Create the group
            group_response = self.session.post(
                group_url,
                json=group_data
            )
            
            # Save the group creation response for debugging
            with open("group_response.html", "w", encoding="utf-8") as f:
                f.write(group_response.text)
            logger.info("Saved group creation response to group_response.html for debugging")
            
            # Extract group ID
            group_id = None
            try:
                content_type = group_response.headers.get('Content-Type', '')
                if content_type and 'application/json' in content_type:
                    group_data = group_response.json()
                    group_id = group_data.get('id') or group_data.get('groupId')
                
                if not group_id and group_response.status_code in [200, 201, 202]:
                    # Try to extract from response text
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', group_response.text)
                    if id_match:
                        group_id = id_match.group(1)
                    else:
                        # Use file ID as fallback
                        group_id = file_id
                        logger.warning(f"Using file ID as group ID: {group_id}")
            except Exception as e:
                logger.error(f"Error parsing group creation response: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                group_id = file_id
                logger.warning(f"Using file ID as fallback group ID: {group_id}")
            
            logger.info(f"Group '{group_name}' created with ID: {group_id}")
            return group_id
        except Exception as e:
            logger.error(f"Failed to upload file and create group: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
    
    def navigate_to_skip_tracing(self):
        """Get the skip tracing page and extract necessary information"""
        try:
            logger.info("Navigating to Skip Tracing...")
            
            # Access skip tracing page
            skip_trace_url = f"{self.base_url}/skip-tracing"
            skip_response = self.session.get(skip_trace_url)
            
            if skip_response.status_code != 200:
                logger.error(f"Failed to access skip tracing page: {skip_response.status_code}")
                return False
                
            # Save the response for debugging
            with open("skip_tracing_page.html", "w", encoding="utf-8") as f:
                f.write(skip_response.text)
                
            logger.info("Skip tracing page accessed and saved to skip_tracing_page.html")
            return True
        except Exception as e:
            logger.error(f"Failed to navigate to skip tracing: {str(e)}")
            return False
    
    def select_contacts(self, group_id):
        """Select contacts from the specified group"""
        try:
            logger.info(f"Selecting contacts from group {group_id}...")
            
            # Get available contacts
            contacts_url = f"{self.base_url}/api/contact-groups/{group_id}/contacts"
            contacts_response = self.session.get(contacts_url)
            
            if contacts_response.status_code != 200:
                logger.warning(f"Failed to get contacts directly. Status: {contacts_response.status_code}")
                # Try alternative method
                contacts_url = f"{self.base_url}/api/contacts?groupId={group_id}"
                contacts_response = self.session.get(contacts_url)
                
                if contacts_response.status_code != 200:
                    logger.error(f"Failed to get contacts with alternative method: {contacts_response.status_code}")
                    return False
            
            # Extract contact IDs
            contact_ids = []
            try:
                if contacts_response.headers.get('Content-Type', '').startswith('application/json'):
                    contacts_data = contacts_response.json()
                    
                    # Handle different response formats
                    if 'items' in contacts_data:
                        contacts = contacts_data['items']
                    elif 'contacts' in contacts_data:
                        contacts = contacts_data['contacts']
                    elif isinstance(contacts_data, list):
                        contacts = contacts_data
                    else:
                        contacts = []
                    
                    # Extract IDs
                    for contact in contacts:
                        contact_id = contact.get('id')
                        if contact_id:
                            contact_ids.append(contact_id)
                else:
                    # Try to find contact IDs in HTML response
                    contacts_soup = BeautifulSoup(contacts_response.text, 'html.parser')
                    
                    # Look for elements with data-id attributes
                    elements_with_id = contacts_soup.select('[data-id]')
                    for element in elements_with_id:
                        contact_id = element.get('data-id')
                        if contact_id:
                            contact_ids.append(contact_id)
            except Exception as e:
                logger.error(f"Error extracting contact IDs: {str(e)}")
                # If we can't get specific contact IDs, we'll try to use the group as a whole
                
            logger.info(f"Found {len(contact_ids)} contact IDs")
            
            # If no contact IDs found but we have a group ID, we'll use the group
            if not contact_ids:
                logger.warning("No contact IDs found, will use group ID for skip tracing")
            
            return group_id, contact_ids
        except Exception as e:
            logger.error(f"Failed to select contacts: {str(e)}")
            return None, []
    
    def place_skip_tracing_order(self, group_id, contact_ids=None):
        """Place skip tracing order for the selected contacts"""
        try:
            logger.info("Placing skip tracing order...")
            
            # Prepare the order data
            order_data = {
                "groupId": group_id,
                "type": "skiptracing"
            }
            
            # Add contact IDs if we have them
            if contact_ids:
                order_data["contactIds"] = contact_ids
            
            # Place the order
            order_url = f"{self.base_url}/api/skip-tracing/orders"
            order_response = self.session.post(
                order_url,
                json=order_data
            )
            
            if order_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to place order with primary URL: {order_response.status_code}")
                
                # Try alternative endpoint
                alt_order_url = f"{self.base_url}/api/orders/skiptracing"
                order_response = self.session.post(
                    alt_order_url,
                    json=order_data
                )
                
                if order_response.status_code not in [200, 201, 202]:
                    logger.error(f"Failed to place order with alternative URL: {order_response.status_code}")
                    return None
            
            # Extract order ID
            order_id = None
            try:
                if order_response.headers.get('Content-Type', '').startswith('application/json'):
                    order_data = order_response.json()
                    order_id = order_data.get('id') or order_data.get('orderId')
                
                if not order_id and order_response.status_code in [200, 201, 202]:
                    # Try to extract from response text
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', order_response.text)
                    if id_match:
                        order_id = id_match.group(1)
                    else:
                        # Use group ID + timestamp as fallback
                        order_id = f"{group_id}_{int(time.time())}"
                        logger.warning(f"Using fallback order ID: {order_id}")
            except Exception as e:
                logger.error(f"Error parsing order response: {str(e)}")
                order_id = f"{group_id}_{int(time.time())}"
                logger.warning(f"Using fallback order ID: {order_id}")
            
            logger.info(f"Order placed with ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"Failed to place skip tracing order: {str(e)}")
            return None
    
    def wait_for_order_completion(self, order_id, max_retries=20, wait_interval=10):
        """Wait for skip tracing order to complete"""
        try:
            logger.info("Waiting for order to complete...")
            
            # Define status URL
            status_url = f"{self.base_url}/api/skip-tracing/orders/{order_id}"
            
            for attempt in range(max_retries):
                logger.info(f"Checking order status (attempt {attempt + 1}/{max_retries})...")
                
                # Get order status
                status_response = self.session.get(status_url)
                
                if status_response.status_code != 200:
                    logger.warning(f"Failed to get order status: {status_response.status_code}")
                    
                    # Try alternative URL
                    alt_status_url = f"{self.base_url}/api/orders/{order_id}"
                    status_response = self.session.get(alt_status_url)
                    
                    if status_response.status_code != 200:
                        logger.warning(f"Failed to get order status with alternative URL: {status_response.status_code}")
                        time.sleep(wait_interval)
                        continue
                
                # Check for order status
                try:
                    if status_response.headers.get('Content-Type', '').startswith('application/json'):
                        status_data = status_response.json()
                        order_status = status_data.get('status')
                        
                        if order_status in ["completed", "done", "finished", "success"]:
                            logger.info(f"Order completed with status: {order_status}")
                            return True
                        elif order_status in ["failed", "cancelled", "error", "timeout"]:
                            logger.error(f"Order failed with status: {order_status}")
                            return False
                            
                        logger.info(f"Order status: {order_status}, waiting {wait_interval} seconds...")
                    else:
                        # Look for status indicators in HTML
                        status_soup = BeautifulSoup(status_response.text, 'html.parser')
                        status_element = status_soup.find(string=re.compile(r'completed|done|finished|success|failed|cancelled|error|processing'))
                        
                        if status_element:
                            status_text = status_element.strip().lower()
                            if any(s in status_text for s in ["completed", "done", "finished", "success"]):
                                logger.info(f"Order completed with status indicator: {status_text}")
                                return True
                            elif any(s in status_text for s in ["failed", "cancelled", "error", "timeout"]):
                                logger.error(f"Order failed with status indicator: {status_text}")
                                return False
                                
                            logger.info(f"Order status indicator: {status_text}, waiting {wait_interval} seconds...")
                except Exception as e:
                    logger.warning(f"Error parsing status response: {str(e)}")
                
                time.sleep(wait_interval)
            
            logger.warning(f"Max retries ({max_retries}) reached, assuming order is complete")
            return True
        except Exception as e:
            logger.error(f"Error while waiting for order completion: {str(e)}")
            return False
    
    def get_contact_data(self, group_id):
        """Get contact data from the completed order"""
        try:
            logger.info("Fetching contact data...")
            
            # Try several potential endpoints for contact data
            endpoints = [
                f"{self.base_url}/api/contacts?groupId={group_id}",
                f"{self.base_url}/api/contact-groups/{group_id}/contacts",
                f"{self.base_url}/api/skip-tracing/results?groupId={group_id}"
            ]
            
            for endpoint in endpoints:
                logger.info(f"Trying endpoint: {endpoint}")
                response = self.session.get(endpoint)
                
                if response.status_code != 200:
                    logger.warning(f"Failed to get contacts from {endpoint}: {response.status_code}")
                    continue
                
                try:
                    content_type = response.headers.get('Content-Type', '')
                    if content_type and 'application/json' in content_type:
                        # Parse JSON response
                        data = response.json()
                        
                        # Try different JSON structures
                        contacts = None
                        if "items" in data:
                            contacts = data.get("items", [])
                        elif "contacts" in data:
                            contacts = data.get("contacts", [])
                        elif "results" in data:
                            contacts = data.get("results", [])
                        elif isinstance(data, list):
                            contacts = data
                        
                        if contacts:
                            logger.info(f"Found {len(contacts)} contacts")
                            
                            # Extract contact information
                            for contact in contacts:
                                # Try different field naming patterns
                                name = (
                                    contact.get('fullName') or 
                                    contact.get('name') or 
                                    contact.get('contactName') or
                                    contact.get('customerName') or
                                    ""
                                )
                                
                                phone = (
                                    contact.get('phoneNumber') or 
                                    contact.get('phone') or 
                                    contact.get('primaryPhone') or
                                    contact.get('contactPhone') or
                                    contact.get('customerPhone') or
                                    ""
                                )
                                
                                email = (
                                    contact.get('email') or 
                                    contact.get('emailAddress') or
                                    contact.get('contactEmail') or
                                    contact.get('customerEmail') or
                                    ""
                                )
                                
                                if name or phone or email:
                                    self.scraped_data.append({
                                        "name": name,
                                        "phone": phone,
                                        "email": email
                                    })
                            
                            if self.scraped_data:
                                logger.info(f"Successfully extracted {len(self.scraped_data)} contacts")
                                return True
                    else:
                        # If response is HTML, parse it for contacts
                        soup = BeautifulSoup(response.text, 'html.parser')
                        
                        # Look for tables
                        tables = soup.find_all('table')
                        if tables:
                            for table in tables:
                                rows = table.find_all('tr')
                                
                                # Skip header row
                                for row in rows[1:]:
                                    cells = row.find_all('td')
                                    if len(cells) >= 3:
                                        name = cells[0].text.strip()
                                        phone = cells[1].text.strip()
                                        email = cells[2].text.strip()
                                        
                                        if name or phone or email:
                                            self.scraped_data.append({
                                                "name": name,
                                                "phone": phone,
                                                "email": email
                                            })
                            
                            if self.scraped_data:
                                logger.info(f"Successfully extracted {len(self.scraped_data)} contacts from HTML table")
                                return True
                        
                        # No tables found, look for structured data
                        else:
                            # Look for email addresses and phone numbers in the page
                            email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
                            phone_pattern = re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
                            
                            # Find all emails
                            emails = []
                            for email_match in email_pattern.finditer(response.text):
                                emails.append(email_match.group(0))
                            
                            # Find all phones
                            phones = []
                            for phone_match in phone_pattern.finditer(response.text):
                                phones.append(phone_match.group(0))
                            
                            # If we have roughly the same number of emails and phones, pair them
                            if emails and phones and abs(len(emails) - len(phones)) <= min(len(emails), len(phones)) // 2:
                                for i in range(min(len(emails), len(phones))):
                                    self.scraped_data.append({
                                        "name": "",  # Can't reliably match names
                                        "phone": phones[i],
                                        "email": emails[i]
                                    })
                                
                                if self.scraped_data:
                                    logger.info(f"Successfully paired {len(self.scraped_data)} emails and phones")
                                    return True
                            
                            # Otherwise, just log what we found
                            else:
                                logger.info(f"Found {len(emails)} emails and {len(phones)} phones, but couldn't reliably pair them")
                                for email in emails:
                                    self.scraped_data.append({
                                        "name": "",
                                        "phone": "",
                                        "email": email
                                    })
                                
                                for phone in phones:
                                    self.scraped_data.append({
                                        "name": "",
                                        "phone": phone,
                                        "email": ""
                                    })
                                
                                if self.scraped_data:
                                    logger.info(f"Added {len(self.scraped_data)} unpaired contacts")
                                    return True
                except Exception as e:
                    logger.error(f"Error processing response from {endpoint}: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
            
            # If we've tried all endpoints and still have no data, try the main contacts page
            try:
                contacts_page_url = f"{self.base_url}/contacts"
                contacts_page = self.session.get(contacts_page_url)
                
                if contacts_page.status_code == 200:
                    # Save the page for debugging
                    with open("contacts_page.html", "w", encoding="utf-8") as f:
                        f.write(contacts_page.text)
                    
                    logger.info("Saved contacts page to contacts_page.html")
                    
                    # Parse for contact data
                    soup = BeautifulSoup(contacts_page.text, 'html.parser')
                    
                    # Look for email addresses and phone numbers in the page
                    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
                    phone_pattern = re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
                    
                    # Find all text nodes
                    text_elements = soup.find_all(string=True)
                    
                    for element in text_elements:
                        text = element.strip()
                        if not text:
                            continue
                        
                        email_match = email_pattern.search(text)
                        phone_match = phone_pattern.search(text)
                        
                        if email_match or phone_match:
                            email = email_match.group(0) if email_match else ""
                            phone = phone_match.group(0) if phone_match else ""
                            
                            # Extract name by removing email and phone
                            name = text
                            if email:
                                name = name.replace(email, "")
                            if phone:
                                name = name.replace(phone, "")
                            name = re.sub(r'\s+', ' ', name).strip()
                            
                            if email or phone:
                                self.scraped_data.append({
                                    "name": name,
                                    "phone": phone,
                                    "email": email
                                })
                    
                    if self.scraped_data:
                        logger.info(f"Extracted {len(self.scraped_data)} contacts from contacts page")
                        return True
            except Exception as e:
                logger.error(f"Error processing contacts page: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
            
            # If we still have no data, report failure
            if not self.scraped_data:
                logger.error("Failed to extract any contact data from all sources")
                return False
                
            return True
        except Exception as e:
            logger.error(f"Failed to get contact data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def save_data_to_csv(self, output_file="propstream_contacts.csv"):
        """Save the scraped data to a CSV file"""
        if not self.scraped_data:
            logger.warning("No data to save!")
            return False
            
        try:
            # Deduplicate data based on email (most unique identifier)
            unique_emails = set()
            deduplicated_data = []
            
            for entry in self.scraped_data:
                email = entry.get("email", "")
                if email and email in unique_emails:
                    continue
                if email:
                    unique_emails.add(email)
                deduplicated_data.append(entry)
            
            # Save to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=["name", "phone", "email"])
                writer.writeheader()
                writer.writerows(deduplicated_data)
                
            logger.info(f"Data saved to {output_file} successfully! ({len(deduplicated_data)} contacts)")
            return True
        except Exception as e:
            logger.error(f"Failed to save data: {str(e)}")
            return False
    
    def run(self):
        """Execute the complete scraping process"""
        try:
            # Step 1: Login
            if not self.login():
                logger.error("Login failed, aborting")
                return False
                
            # Step 2: Select file to upload
            file_path = self.select_file_to_upload()
            if not file_path:
                logger.error("No file selected, aborting")
                return False
            
            # Step 3: Upload file and create group
            group_id = self.upload_file_and_create_group(file_path)
            if not group_id:
                logger.error("Failed to upload file and create group, aborting")
                return False
            
            # Step 4: Navigate to Skip Tracing
            if not self.navigate_to_skip_tracing():
                logger.warning("Failed to navigate to Skip Tracing, but continuing anyway")
            
            # Step 5: Select contacts
            group_id, contact_ids = self.select_contacts(group_id)
            if not group_id:
                logger.error("Failed to select contacts, aborting")
                return False
            
            # Step 6: Place skip tracing order
            order_id = self.place_skip_tracing_order(group_id, contact_ids)
            if not order_id:
                logger.error("Failed to place skip tracing order, aborting")
                return False
            
            # Step 7: Wait for order to complete
            if not self.wait_for_order_completion(order_id):
                logger.warning("Order may not have completed successfully, but continuing anyway")
            
            # Step 8: Get contact data
            if not self.get_contact_data(group_id):
                logger.error("Failed to get contact data, aborting")
                return False
            
            # Step 9: Save data to CSV
            if not self.save_data_to_csv():
                logger.error("Failed to save data to CSV")
                return False
            
            logger.info("Scraping process completed successfully!")
            return True
        except Exception as e:
            logger.critical(f"An error occurred during the scraping process: {str(e)}")
            import traceback
            logger.critical(traceback.format_exc())
            return False

if __name__ == "__main__":
    try:
        logger.info("Starting PropStream HTML Scraper")
        scraper = PropStreamHTMLScraper()
        scraper.run()
    except Exception as e:
        logger.critical(f"Critical error: {str(e)}")
        import traceback
        logger.critical(traceback.format_exc()) 