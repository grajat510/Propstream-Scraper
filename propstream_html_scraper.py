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
        # Get credentials from environment variables
        self.username = os.environ.get("PROPSTREAM_USERNAME")
        self.password = os.environ.get("PROPSTREAM_PASSWORD")
        self.base_url = "https://app.propstream.com"
        self.login_url = "https://login.propstream.com/"
        self.session = requests.Session()
        self.scraped_data = []
        self.uploaded_file_path = None  # Store the path to the uploaded file
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
            
            # Store the file path as an instance variable for later use
            self.uploaded_file_path = file_path
                
            logger.info(f"Selected file: {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error selecting file: {str(e)}")
            return None
    
    def upload_file_and_create_group(self, file_path):
        """Upload file and create a new group"""
        try:
            logger.info("Accessing contacts page...")
            
            # Navigate directly to contacts page
            import_url = f"{self.base_url}/contacts"
            import_response = self.session.get(import_url)
            
            if import_response.status_code != 200:
                logger.error(f"Failed to access contacts page: {import_response.status_code}")
                return None
            
            # Save the import page for debugging
            with open("import_page.html", "w", encoding="utf-8") as f:
                f.write(import_response.text)
            logger.info("Saved import page to import_page.html for debugging")
            
            # Step 1: Upload the file directly (skip the Import List button)
            logger.info(f"Uploading file: {os.path.basename(file_path)}...")
            upload_url = f"{self.base_url}/api/contacts/upload"
            
            # Prepare file for upload
            file_name = os.path.basename(file_path)
            content_type = 'text/csv' if file_path.endswith('.csv') else 'application/vnd.ms-excel'
            
            with open(file_path, 'rb') as file:
                file_content = file.read()
            
            # Upload using MultipartEncoder if available
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
                
                upload_response = self.session.post(
                    upload_url,
                    files=files,
                    data=data
                )
            
            # Save upload response for debugging
            with open("upload_response.html", "w", encoding="utf-8") as f:
                f.write(upload_response.text)
            logger.info("Saved upload response to upload_response.html for debugging")
            
            # Get file ID from the upload response
            file_id = None
            try:
                if 'application/json' in upload_response.headers.get('Content-Type', ''):
                    upload_data = upload_response.json()
                    file_id = upload_data.get('id') or upload_data.get('fileId')
                    logger.info(f"Extracted file ID from JSON response: {file_id}")
            except Exception as e:
                logger.warning(f"Error parsing upload JSON: {str(e)}")
            
            # If still no file ID, try to extract from response text
            if not file_id:
                try:
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', upload_response.text)
                    if id_match:
                        file_id = id_match.group(1)
                        logger.info(f"Extracted file ID from response text: {file_id}")
                    else:
                        # Use timestamp as fallback
                        file_id = str(int(time.time()))
                        logger.warning(f"Using timestamp as file ID: {file_id}")
                except Exception as e:
                    logger.warning(f"Error extracting file ID: {str(e)}")
                    file_id = str(int(time.time()))
            
            # Wait longer after upload to ensure file is processed
            logger.info("Waiting for file processing...")
            time.sleep(10)
            
            # Step 2: Select "Create New" radio button
            logger.info("Selecting 'Create New' option...")
            add_to_group_url = f"{self.base_url}/api/contacts/import/mode"
            add_to_group_data = {"mode": "new"}
            add_response = self.session.post(add_to_group_url, json=add_to_group_data)
            
            if add_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to select 'Create New' option: {add_response.status_code}")
            
            time.sleep(2)
            
            # Step 3: Set group name and click Save button
            group_name = f"Foreclosures_scraping_{time.strftime('%Y%m%d_%H%M%S')}"
            logger.info(f"Creating new group: {group_name}")
            
            # Save to create the group with the imported contacts - use groupName as seen in network tab
            save_url = f"{self.base_url}/api/contacts/import/save"
            save_data = {
                "fileId": file_id,
                "groupName": group_name,
                "mode": "new"
            }
            save_response = self.session.post(save_url, json=save_data)
            
            logger.info(f"Save response status: {save_response.status_code}")
            
            # Extract group ID from response
            group_id = None
            
            # Try to get group ID from Location header
            if 'Location' in save_response.headers:
                location = save_response.headers['Location']
                group_id_match = re.search(r'[\?&]id=([^&]+)', location)
                if group_id_match:
                    group_id = group_id_match.group(1)
                    logger.info(f"Extracted group ID from Location header: {group_id}")
            
            # If no group ID yet, try other methods
            if not group_id:
                # Try to extract from response body if it's JSON
                try:
                    if 'application/json' in save_response.headers.get('Content-Type', ''):
                        save_data = save_response.json()
                        group_id = save_data.get('id') or save_data.get('groupId')
                        if group_id:
                            logger.info(f"Extracted group ID from JSON response: {group_id}")
                except Exception as e:
                    logger.warning(f"Error parsing save response JSON: {str(e)}")
            
            # If still no group ID, try to extract from HTML
            if not group_id:
                try:
                    group_id_match = re.search(r'groupId=([^&"]+)', save_response.text)
                    if group_id_match:
                        group_id = group_id_match.group(1)
                        logger.info(f"Extracted group ID from response HTML: {group_id}")
                    else:
                        # Try looking for the group by name
                        logger.info(f"Looking for group by name: {group_name}")
                        time.sleep(5)  # Wait a bit before checking
                        
                        # Get list of groups
                        groups_url = f"{self.base_url}/api/contact-groups"
                        # Add retry logic for getting groups
                        max_retries = 3
                        retry_delay = 3
                        
                        for retry in range(max_retries):
                            try:
                                # Get the groups list with retry
                                groups_response = self.session.get(groups_url)
                                
                                # Check if the response is JSON
                                if groups_response.status_code == 200 and 'application/json' in groups_response.headers.get('Content-Type', ''):
                                    groups_data = groups_response.json()
                                    for group in groups_data:
                                        if group.get('name') == group_name:
                                            group_id = group.get('id')
                                            logger.info(f"Found group by name with ID: {group_id}")
                                            break
                                    
                                    # If we found the group, break out of retry loop
                                    if group_id:
                                        break
                                else:
                                    # If not JSON, log and try again
                                    logger.warning(f"Groups response not JSON (attempt {retry+1}/{max_retries}): {groups_response.status_code}")
                                    if retry < max_retries - 1:
                                        # Wait longer with each retry
                                        time.sleep(retry_delay * (retry + 1))
                                        continue
                            except Exception as e:
                                logger.warning(f"Error finding group by name (attempt {retry+1}/{max_retries}): {str(e)}")
                                if retry < max_retries - 1:
                                    # Wait longer with each retry
                                    time.sleep(retry_delay * (retry + 1))
                                    continue
                        
                        # If we still can't get the group ID, extract it from the URL
                        if not group_id:
                            # Navigate to contacts page to see if we can find our group
                            try:
                                contacts_url = f"{self.base_url}/contacts"
                                contacts_response = self.session.get(contacts_url)
                                
                                if contacts_response.status_code == 200:
                                    # Look for the group name in the HTML
                                    group_pattern = re.compile(f'{re.escape(group_name)}.*?groupId=([^&"\']+)', re.DOTALL)
                                    group_match = group_pattern.search(contacts_response.text)
                                    
                                    if group_match:
                                        group_id = group_match.group(1)
                                        logger.info(f"Found group ID from contacts page: {group_id}")
                            except Exception as e:
                                logger.warning(f"Error extracting group ID from contacts page: {str(e)}")
                            
                            # If still no ID, just proceed with what we have
                            if not group_id:
                                # Get the ID directly from the save response if possible
                                save_id_match = re.search(r'"id"\s*:\s*"([^"]+)"', save_response.text)
                                if save_id_match:
                                    group_id = save_id_match.group(1)
                                    logger.info(f"Extracted group ID directly from save response: {group_id}")
                except Exception as e:
                    logger.warning(f"Error finding group by name: {str(e)}")
            
            # Use fallback if still no group ID
            if not group_id:
                group_id = f"group_{int(time.time())}"
                logger.info(f"Using fallback group ID: {group_id}")
            
            # Wait for import to complete
            logger.info(f"Waiting for contacts to be imported into group '{group_name}'...")
            time.sleep(30)  # Give PropStream plenty of time to process the file
            
            # Verify contacts were imported
            contacts_url = f"{self.base_url}/api/contact-groups/{group_id}/contacts"
            contacts_response = self.session.get(contacts_url)
            
            contact_count = 0
            try:
                if contacts_response.status_code == 200:
                    # Try to parse the response if it's JSON
                    try:
                        if 'application/json' in contacts_response.headers.get('Content-Type', ''):
                            contacts_data = contacts_response.json()
                            
                            # Log the response structure for debugging
                            with open("contacts_debug.json", "w", encoding="utf-8") as f:
                                f.write(json.dumps(contacts_data, indent=2))
                            
                            # Try different possible response structures
                            if 'items' in contacts_data:
                                contact_count = len(contacts_data['items'])
                            elif 'contacts' in contacts_data:
                                contact_count = len(contacts_data['contacts'])
                            elif isinstance(contacts_data, list):
                                contact_count = len(contacts_data)
                            elif 'count' in contacts_data:
                                contact_count = contacts_data['count']
                            
                            logger.info(f"Found {contact_count} contacts in the group")
                    except Exception as e:
                        logger.warning(f"Error parsing contacts response: {str(e)}")
                        # Save raw response for debugging
                        with open("contacts_response_raw.txt", "w", encoding="utf-8") as f:
                            f.write(contacts_response.text)
                else:
                    logger.warning(f"Failed to verify contacts: {contacts_response.status_code}")
            except Exception as e:
                logger.error(f"Error verifying contacts: {str(e)}")
            
            # Always return the group ID, even if we couldn't verify contacts
            logger.info(f"Group '{group_name}' created with ID: {group_id} containing {contact_count} contacts")
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
            
            # Step 12: Click "Select Contacts" button
            logger.info("Clicking 'Select Contacts' button...")
            select_contacts_url = f"{self.base_url}/api/skip-tracing/select-contacts"
            select_contacts_response = self.session.post(select_contacts_url)
            
            if select_contacts_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click Select Contacts button: {select_contacts_response.status_code}")
            
            time.sleep(2)  # Wait a moment for the page to load
            
            # Step 13: Select the group from dropdown
            logger.info(f"Selecting group: {group_id}")
            # Get available groups first to confirm our group exists
            groups_url = f"{self.base_url}/api/contact-groups"
            groups_response = self.session.get(groups_url)
            
            group_exists = False
            group_name = ""
            if groups_response.status_code == 200:
                try:
                    groups_data = groups_response.json()
                    if isinstance(groups_data, list):
                        for group in groups_data:
                            if str(group.get('id')) == str(group_id):
                                group_exists = True
                                group_name = group.get('name', "")
                                logger.info(f"Found group: {group_name} with ID {group_id}")
                                break
                except Exception as e:
                    logger.warning(f"Error checking groups: {str(e)}")
            
            if not group_exists:
                logger.warning(f"Group ID {group_id} not found in available groups!")
            
            # Select the group
            select_group_url = f"{self.base_url}/api/skip-tracing/select-group"
            select_group_data = {"groupId": group_id}
            select_group_response = self.session.post(select_group_url, json=select_group_data)
            
            if select_group_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to select group: {select_group_response.status_code}")
            
            time.sleep(2)  # Wait a moment for contacts to load
            
            # Get contacts from the selected group
            contacts_url = f"{self.base_url}/api/skip-tracing/contacts?groupId={group_id}"
            contacts_response = self.session.get(contacts_url)
            
            contact_ids = []
            if contacts_response.status_code == 200:
                try:
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
                            
                    logger.info(f"Found {len(contact_ids)} contact IDs from the skip tracing interface")
                except Exception as e:
                    logger.error(f"Error extracting contact IDs: {str(e)}")
            else:
                logger.warning(f"Failed to get contacts: {contacts_response.status_code}")
                
                # Try alternative method
                alt_contacts_url = f"{self.base_url}/api/contact-groups/{group_id}/contacts"
                alt_contacts_response = self.session.get(alt_contacts_url)
                
                if alt_contacts_response.status_code == 200:
                    try:
                        alt_contacts_data = alt_contacts_response.json()
                        
                        # Handle different response formats
                        if 'items' in alt_contacts_data:
                            contacts = alt_contacts_data['items']
                        elif 'contacts' in alt_contacts_data:
                            contacts = alt_contacts_data['contacts']
                        elif isinstance(alt_contacts_data, list):
                            contacts = alt_contacts_data
                        else:
                            contacts = []
                        
                        # Extract IDs
                        for contact in contacts:
                            contact_id = contact.get('id')
                            if contact_id:
                                contact_ids.append(contact_id)
                                
                        logger.info(f"Found {len(contact_ids)} contact IDs using alternative method")
                    except Exception as e:
                        logger.error(f"Error extracting contact IDs with alternative method: {str(e)}")
            
            # If still no contacts found, try to get them from the HTML
            if not contact_ids:
                # Get the skip tracing contact selection page HTML
                skip_page_url = f"{self.base_url}/skip-tracing/select-contacts"
                skip_page_response = self.session.get(skip_page_url)
                
                if skip_page_response.status_code == 200:
                    skip_soup = BeautifulSoup(skip_page_response.text, 'html.parser')
                    
                    # Save the skip tracing contacts page for debugging
                    with open("skip_contacts_page.html", "w", encoding="utf-8") as f:
                        f.write(skip_page_response.text)
                    
                    # Look for elements with data-id attributes or checkboxes
                    checkboxes = skip_soup.select('input[type="checkbox"]')
                    for checkbox in checkboxes:
                        parent = checkbox.find_parent('tr') or checkbox.find_parent('div')
                        if parent:
                            contact_id = parent.get('data-id') or parent.get('id')
                            if contact_id and contact_id not in contact_ids:
                                contact_ids.append(contact_id)
                    
                    if contact_ids:
                        logger.info(f"Found {len(contact_ids)} contact IDs from HTML parsing")
            
            # Step 14: Mark all checkmarks (select all contacts)
            logger.info("Selecting all contacts")
            select_all_url = f"{self.base_url}/api/skip-tracing/select-all"
            select_all_data = {"groupId": group_id}
            select_all_response = self.session.post(select_all_url, json=select_all_data)
            
            if select_all_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to select all contacts: {select_all_response.status_code}")
            
            time.sleep(2)  # Wait a moment for selection to process
            
            # Step 15: Click "Add Selected Contacts"
            logger.info("Clicking 'Add Selected Contacts' button...")
            add_selected_url = f"{self.base_url}/api/skip-tracing/add-selected"
            add_selected_data = {"groupId": group_id}
            if contact_ids:
                add_selected_data["contactIds"] = contact_ids
            add_selected_response = self.session.post(add_selected_url, json=add_selected_data)
            
            if add_selected_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to add selected contacts: {add_selected_response.status_code}")
            
            time.sleep(2)  # Wait a moment for contacts to be added
            
            # Step 16: Click "Done"
            logger.info("Clicking 'Done' button...")
            done_button_url = f"{self.base_url}/api/skip-tracing/done"
            done_button_response = self.session.post(done_button_url)
            
            if done_button_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click Done button: {done_button_response.status_code}")
            
            # Even if we couldn't get specific contact IDs, we'll use the group
            if not contact_ids:
                logger.warning("No specific contact IDs found, will use group ID for skip tracing")
            else:
                logger.info(f"Successfully selected {len(contact_ids)} contacts for skip tracing")
            
            return group_id, contact_ids
        except Exception as e:
            logger.error(f"Failed to select contacts: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return group_id, []
    
    def place_skip_tracing_order(self, group_id, contact_ids=None):
        """Place skip tracing order for the selected contacts"""
        try:
            logger.info("Placing skip tracing order...")
            
            # Step 17: Click the "Next" button
            logger.info("Clicking 'Next' button...")
            next_button_url = f"{self.base_url}/api/skip-tracing/next"
            next_data = {"groupId": group_id}
            if contact_ids:
                next_data["contactIds"] = contact_ids
            next_response = self.session.post(next_button_url, json=next_data)
            
            if next_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click Next button: {next_response.status_code}")
            
            time.sleep(1)  # Wait a moment for the page to load
            
            # Step 18: Click the "Place Order" button
            logger.info("Clicking 'Place Order' button...")
            place_order_url = f"{self.base_url}/api/skip-tracing/place-order"
            place_order_data = {"groupId": group_id}
            if contact_ids:
                place_order_data["contactIds"] = contact_ids
            place_order_response = self.session.post(place_order_url, json=place_order_data)
            
            if place_order_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click Place Order button: {place_order_response.status_code}")
                
                # Try alternative endpoint
                alt_place_order_url = f"{self.base_url}/api/orders/skiptracing"
                place_order_response = self.session.post(alt_place_order_url, json=place_order_data)
                
                if place_order_response.status_code not in [200, 201, 202]:
                    logger.error(f"Failed to place order with alternative URL: {place_order_response.status_code}")
                    return None
            
            time.sleep(1)  # Wait a moment for the page to load
            
            # Step 19: Click the "I Accept" button
            logger.info("Clicking 'I Accept' button...")
            accept_url = f"{self.base_url}/api/skip-tracing/accept"
            accept_data = {"groupId": group_id}
            accept_response = self.session.post(accept_url, json=accept_data)
            
            if accept_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click I Accept button: {accept_response.status_code}")
            
            # Extract order ID from the response
            order_id = None
            try:
                if place_order_response.headers.get('Content-Type', '').startswith('application/json'):
                    order_data = place_order_response.json()
                    order_id = order_data.get('id') or order_data.get('orderId')
                
                if not order_id and place_order_response.status_code in [200, 201, 202]:
                    # Try to extract from response text
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', place_order_response.text)
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
    
    def wait_for_order_completion(self, order_id, max_retries=2, wait_interval=10):
        """Wait for skip tracing order to complete and handle UI interactions"""
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
                            
                            # Handle UI interactions after order completion
                            # 1. Click OK button
                            ok_button_url = f"{self.base_url}/api/contacts/import/complete"
                            ok_response = self.session.post(ok_button_url)
                            if ok_response.status_code != 200:
                                logger.warning("Failed to click OK button")
                            
                            # 2. Set list name
                            list_name = f"{time.strftime('%m/%d/%Y')} - {order_id}"
                            list_name_url = f"{self.base_url}/api/contacts/import/name"
                            list_name_data = {"name": list_name}
                            list_name_response = self.session.post(list_name_url, json=list_name_data)
                            if list_name_response.status_code != 200:
                                logger.warning("Failed to set list name")
                            
                            # 3. Click Done button
                            done_button_url = f"{self.base_url}/api/contacts/import/finish"
                            done_response = self.session.post(done_button_url)
                            if done_response.status_code != 200:
                                logger.warning("Failed to click Done button")
                            
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
                                
                                # Handle UI interactions after order completion
                                # 1. Click OK button
                                ok_button_url = f"{self.base_url}/api/contacts/import/complete"
                                ok_response = self.session.post(ok_button_url)
                                if ok_response.status_code != 200:
                                    logger.warning("Failed to click OK button")
                                
                                # 2. Set list name
                                list_name = f"{time.strftime('%m/%d/%Y')} - {order_id}"
                                list_name_url = f"{self.base_url}/api/contacts/import/name"
                                list_name_data = {"name": list_name}
                                list_name_response = self.session.post(list_name_url, json=list_name_data)
                                if list_name_response.status_code != 200:
                                    logger.warning("Failed to set list name")
                                
                                # 3. Click Done button
                                done_button_url = f"{self.base_url}/api/contacts/import/finish"
                                done_response = self.session.post(done_button_url)
                                if done_response.status_code != 200:
                                    logger.warning("Failed to click Done button")
                                
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
    
    def extract_contact_data_from_html(self, html_content):
        """Extract contact data directly from HTML using CSS selectors"""
        try:
            logger.info("Extracting contact data from HTML...")
            
            soup = BeautifulSoup(html_content, 'html.parser')
            contacts_data = []
            
            # Try to find contact forms in the HTML
            contact_forms = soup.find_all('form') or []
            
            if not contact_forms:
                logger.warning("No contact forms found in HTML")
                
                # Try alternative method - look for specific selectors
                # First Name selector
                first_name_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(1) > div:nth-child(1) > div > div > input[type=text]"
                # Middle Name selector
                middle_name_selector = "input[name='middleName'][type='text']"
                # Last Name selector
                last_name_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(1) > div:nth-child(3) > div > div > input[type=text]"
                # Street Address selector
                street_address_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(3) > div.src-app-Contacts-ContactEditor-style__zrACj__lg > div > div > input[type=text]"
                # City selector
                city_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(3) > div.src-app-Contacts-ContactEditor-style__iY0fh__md > div > div > input[type=text]"
                # State selector
                state_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(4) > div.src-app-Contacts-ContactEditor-style__zrACj__lg > div > div > div > select"
                # Zip selector
                zip_selector = "#root > div > div.src-components-Loader-style__tbIRk__withHoverLoader > div > div > div.src-app-style__x5gBM__wrapper > div:nth-child(3) > div:nth-child(2) > div > div.src-app-Contacts-style__fJY6___rightSide > div > div.src-app-Contacts-ContactEditor-style__MKOqR__body > div > div.src-app-Contacts-ContactEditor-style__K2bsg__fields > div:nth-child(4) > div.src-app-Contacts-ContactEditor-style__iY0fh__md > div > div > input[type=text]"
                
                # Try simpler selectors if complex ones fail
                # First we'll try the complex selectors
                first_name_elements = soup.select(first_name_selector)
                if not first_name_elements:
                    # Fallback to simpler selectors
                    first_name_elements = soup.find_all('input', {'type': 'text', 'placeholder': re.compile(r'First\s*Name', re.I)})
                    if not first_name_elements:
                        first_name_elements = soup.find_all('input', {'name': re.compile(r'first', re.I)})
                
                middle_name_elements = soup.select(middle_name_selector)
                if not middle_name_elements:
                    middle_name_elements = soup.find_all('input', {'name': re.compile(r'middle', re.I)})
                    
                last_name_elements = soup.select(last_name_selector)
                if not last_name_elements:
                    last_name_elements = soup.find_all('input', {'type': 'text', 'placeholder': re.compile(r'Last\s*Name', re.I)})
                    if not last_name_elements:
                        last_name_elements = soup.find_all('input', {'name': re.compile(r'last', re.I)})
                
                # Process all rows of contact data we can find
                # If we found any contact fields, we'll collect the data
                if first_name_elements or last_name_elements:
                    logger.info("Found contact fields, extracting data...")
                    
                    # Extract data from the first contact
                    contact_info = {}
                    
                    # Get first name
                    if first_name_elements:
                        first_name = first_name_elements[0].get('value', '')
                        if first_name:
                            contact_info['first_name'] = first_name
                    
                    # Get middle name
                    if middle_name_elements:
                        middle_name = middle_name_elements[0].get('value', '')
                        if middle_name:
                            contact_info['middle_name'] = middle_name
                    
                    # Get last name
                    if last_name_elements:
                        last_name = last_name_elements[0].get('value', '')
                        if last_name:
                            contact_info['last_name'] = last_name
                    
                    # If we have any contact info, add it to the list
                    if contact_info:
                        contacts_data.append(contact_info)
                
                # Try to find contact data in table format
                # Look for tables that might contain contact data
                tables = soup.find_all('table')
                for table in tables:
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all('td')
                        if len(cells) >= 3:  # At least name, phone, email
                            contact_info = {}
                            
                            # Try to extract name
                            name_cell = cells[0]
                            name_text = name_cell.get_text().strip()
                            name_parts = name_text.split()
                            
                            if len(name_parts) >= 2:
                                contact_info['first_name'] = name_parts[0]
                                contact_info['last_name'] = name_parts[-1]
                                if len(name_parts) > 2:
                                    contact_info['middle_name'] = ' '.join(name_parts[1:-1])
                            
                            # Try to extract phone
                            if len(cells) > 1:
                                phone_cell = cells[1]
                                phone_text = phone_cell.get_text().strip()
                                if re.search(r'\d{3}[-.\s]?\d{3}[-.\s]?\d{4}', phone_text):
                                    contact_info['phones'] = [phone_text]
                            
                            # Try to extract email
                            if len(cells) > 2:
                                email_cell = cells[2]
                                email_text = email_cell.get_text().strip()
                                if '@' in email_text:
                                    contact_info['email'] = email_text
                            
                            # If we have any contact info, add it to the list
                            if contact_info:
                                contacts_data.append(contact_info)
            
            # If we found contact data, return it
            if contacts_data:
                logger.info(f"Successfully extracted {len(contacts_data)} contacts from HTML")
                return contacts_data
            else:
                logger.warning("No contact data found in HTML")
                return []
                
        except Exception as e:
            logger.error(f"Error extracting contact data from HTML: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
            
    def get_contact_data(self, group_id):
        """Get contact data from the completed order"""
        try:
            logger.info("Fetching contact data...")
            
            # Navigate to the contact page
            contact_url = f"{self.base_url}/contacts"
            contact_response = self.session.get(contact_url)
            
            if contact_response.status_code != 200:
                logger.error(f"Failed to access contact page: {contact_response.status_code}")
                return False
            
            # Save the contact page for debugging
            with open("contact_page.html", "w", encoding="utf-8") as f:
                f.write(contact_response.text)
            logger.info("Saved contact page to contact_page.html for debugging")
            
            # First try to extract contacts directly from the HTML
            html_contacts = self.extract_contact_data_from_html(contact_response.text)
            if html_contacts:
                logger.info(f"Found {len(html_contacts)} contacts directly from HTML")
                self.scraped_data = html_contacts
                return True
                
            # If we couldn't extract directly, try the API approach
            lists_url = f"{self.base_url}/api/contacts/lists"
            lists_response = self.session.get(lists_url)
            
            if lists_response.status_code != 200:
                logger.error(f"Failed to get contact lists: {lists_response.status_code}")
                return False
                
            # Find our list - it should be named with the date and order ID
            # Format is typically "MM/DD/YYYY - order_id"
            target_list_id = None
            today_date = time.strftime("%m/%d/%Y")
            
            try:
                lists_data = lists_response.json()
                
                # Look for our list with date pattern
                for list_item in lists_data:
                    list_name = list_item.get('name', '')
                    if (today_date in list_name and str(group_id) in list_name) or "skip" in list_name.lower():
                        target_list_id = list_item.get('id')
                        logger.info(f"Found target list: {list_name} with ID {target_list_id}")
                        break
                        
                # If not found with today's date, look for any skip tracing list
                if not target_list_id:
                    for list_item in lists_data:
                        list_name = list_item.get('name', '')
                        list_type = list_item.get('type', '')
                        if list_type == 'skipTracing' or 'skip' in list_name.lower():
                            target_list_id = list_item.get('id')
                            logger.info(f"Found skip tracing list: {list_name} with ID {target_list_id}")
                            break
            except Exception as e:
                logger.error(f"Error finding target list: {str(e)}")
                
            if not target_list_id:
                logger.error("Could not find the skip tracing results list")
                return False
                
            # Select the list to view its data
            select_list_url = f"{self.base_url}/api/contacts/select-list"
            select_data = {"listId": target_list_id}
            select_response = self.session.post(select_list_url, json=select_data)
            
            if select_response.status_code != 200:
                logger.warning(f"Failed to select list: {select_response.status_code}")
                
            # Wait a moment for the data to load
            time.sleep(3)
            
            # Get the contact data for the selected list
            list_contacts_url = f"{self.base_url}/api/contacts?listId={target_list_id}"
            list_contacts_response = self.session.get(list_contacts_url)
            
            if list_contacts_response.status_code != 200:
                logger.error(f"Failed to get contacts for list: {list_contacts_response.status_code}")
                return False
                
            # Parse the contact data
            try:
                contacts_data = []
                contact_items = []
                
                # Try to get the contact data
                if list_contacts_response.headers.get('Content-Type', '').startswith('application/json'):
                    list_data = list_contacts_response.json()
                    
                    # Handle different response formats
                    if 'items' in list_data:
                        contact_items = list_data['items']
                    elif 'contacts' in list_data:
                        contact_items = list_data['contacts']
                    elif isinstance(list_data, list):
                        contact_items = list_data
                        
                    logger.info(f"Found {len(contact_items)} contacts in the list")
                    
                    # Extract the relevant data from each contact
                    for contact in contact_items:
                        contact_info = {}
                        
                        # Get mobile phone
                        mobile_phone = contact.get('mobilePhone', '')
                        if mobile_phone:
                            contact_info['mobile_phones'] = [mobile_phone]
                        
                        # Get landline
                        landline = contact.get('landlinePhone', '')
                        if landline:
                            contact_info['landlines'] = [landline]
                        
                        # Get phone
                        phone = contact.get('phone', '')
                        if phone:
                            contact_info['phones'] = [phone]
                        
                        # Get email
                        email = contact.get('email', '')
                        if email:
                            contact_info['email'] = email
                            
                        # Get name information
                        contact_info['first_name'] = contact.get('firstName', '')
                        contact_info['middle_name'] = contact.get('middleName', '')
                        contact_info['last_name'] = contact.get('lastName', '')
                        
                        if contact_info:
                            contacts_data.append(contact_info)
                
                if contacts_data:
                    self.scraped_data = contacts_data
                    logger.info(f"Successfully extracted data for {len(contacts_data)} contacts")
                    return True
                else:
                    logger.error("No contact data found in API response")
                    
                    # If API data extraction failed, try HTML extraction as a fallback
                    # Refresh the contact page after selecting the list
                    updated_contact_url = f"{self.base_url}/contacts?listId={target_list_id}"
                    updated_contact_response = self.session.get(updated_contact_url)
                    
                    if updated_contact_response.status_code == 200:
                        updated_contact_soup = BeautifulSoup(updated_contact_response.text, 'html.parser')
                        
                        # Save the updated contact page for debugging
                        with open("updated_contact_page.html", "w", encoding="utf-8") as f:
                            f.write(updated_contact_response.text)
                            
                        # Find all contact rows in the HTML
                        contact_rows = updated_contact_soup.select('div.ag-center-cols-clipper > div > div > div')
                        
                        for row in contact_rows:
                            contact = {}
                            
                            # Extract mobile phone
                            mobile_phone = row.select_one('#cell-mobilePhone-2338')
                            if mobile_phone:
                                contact['mobile_phones'] = [mobile_phone.text.strip()]
                            
                            # Extract landline
                            landline = row.select_one('#cell-landlinePhone-2339')
                            if landline:
                                contact['landlines'] = [landline.text.strip()]
                            
                            # Extract phone (from the 4th column)
                            phone = row.select_one('div:nth-child(4)')
                            if phone:
                                contact['phones'] = [phone.text.strip()]
                            
                            # Extract email (from the 5th column)
                            email = row.select_one('div:nth-child(5)')
                            if email:
                                contact['email'] = email.text.strip()
                            
                            if contact:
                                contacts_data.append(contact)
                        
                        if contacts_data:
                            self.scraped_data = contacts_data
                            logger.info(f"Successfully extracted data for {len(contacts_data)} contacts via HTML parsing")
                            return True
                        else:
                            logger.error("No contact data found in HTML parsing")
                            return False
                    else:
                        logger.error("No contact data found")
                        return False
            except Exception as e:
                logger.error(f"Error extracting contact data: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                return False
        except Exception as e:
            logger.error(f"Failed to get contact data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def save_data_to_csv(self, output_file=None):
        """
        Save the scraped data back to the original CSV file, adding new columns
        for phone, mobile phone, landline, email, and update timestamp
        """
        if not self.scraped_data:
            logger.warning("No data to save!")
            return False
            
        try:
            # If no output file specified, use the uploaded file
            if not output_file and hasattr(self, 'uploaded_file_path'):
                output_file = self.uploaded_file_path
            elif not output_file:
                output_file = "propstream_contacts.csv"
                
            logger.info(f"Preparing to update file: {output_file}")
            
            # Get current timestamp
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            
            # Check if file is CSV
            if output_file.lower().endswith('.csv'):
                # Read the original CSV file
                original_data = []
                fieldnames = []
                
                try:
                    with open(output_file, 'r', newline='', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        fieldnames = reader.fieldnames or []
                        original_data = list(reader)
                        
                    logger.info(f"Read {len(original_data)} rows from original file")
                except Exception as e:
                    logger.error(f"Error reading original CSV: {str(e)}")
                    # If we can't read the file, we'll create a new one
                    original_data = []
                    fieldnames = ['First Name', 'Middle Name', 'Last Name']
                
                # Our new fields we want to add
                new_fields = ['Phone', 'Mobile Phone', 'Landline', 'Email', 'Propstream Updated Date & Time']
                
                # First, check if any of our fields already exist
                existing_fields = [field for field in new_fields if field in fieldnames]
                
                # If none of our fields exist yet, we need to add them in the right position
                if not existing_fields:
                    # Determine where to insert our new fields
                    # Instead of trying to be clever, we'll directly analyze the Excel file structure
                    # from the screenshot
                    
                    # Common last columns before our data should be added
                    last_column_candidates = [
                        'Recorded Date', 'Last Date',
                        'Lender/Mortgage', 'Mortgage',
                        'Date', 'Recorded', 'Last'
                    ]
                    
                    # Find the last column that should appear before our new fields
                    insert_after = None
                    for candidate in last_column_candidates:
                        if candidate in fieldnames:
                            candidate_index = fieldnames.index(candidate)
                            if insert_after is None or candidate_index > insert_after:
                                insert_after = candidate_index
                    
                    # If we couldn't find a good insertion point, just use the last field
                    if insert_after is None:
                        insert_after = len(fieldnames) - 1
                    
                    # Create a new fieldnames list with our fields inserted at the right position
                    new_fieldnames = []
                    for i, field in enumerate(fieldnames):
                        new_fieldnames.append(field)
                        # Insert our new fields right after the chosen column
                        if i == insert_after:
                            new_fieldnames.extend(new_fields)
                    
                    # Use the new fieldnames
                    fieldnames = new_fieldnames
                
                # Try to match scraped data with original data
                # Look for any available property that might help with matching
                # The first approach is to try matching by First Name + Last Name if available
                matched_indices = set()
                
                # First, try to identify unique identifiers in the original data that we can use for matching
                # We'll use Address or Zip or any other available data 
                identifier_columns = [
                    ('First Name', 'Last Name'),  # Try matching by first and last name
                    ('Zip',),  # Try matching by zip alone
                    ('Address',),  # Try matching by address
                    ('Street Address',),  # Alternative name for address
                    ('Property Address',),  # Another alternative
                ]
                
                # For each scraped contact, try to find a match in the original data
                for scraped_index, scraped_contact in enumerate(self.scraped_data):
                    matched = False
                    
                    # Try different identifier combinations
                    for identifier_set in identifier_columns:
                        if matched:
                            break
                            
                        # Check if we have this identifier in the original data
                        if all(id_col in fieldnames for id_col in identifier_set):
                            # If we have first/last name in our scraped data, try to match by that
                            if identifier_set == ('First Name', 'Last Name'):
                                # Only try name matching if we have name data
                                if not scraped_contact.get('first_name', '') and not scraped_contact.get('last_name', ''):
                                    continue
                                    
                                # Try matching by name
                                for i, row in enumerate(original_data):
                                    if i in matched_indices:
                                        continue
                                        
                                    if (scraped_contact.get('first_name', '').strip().lower() == row.get('First Name', '').strip().lower() and 
                                        scraped_contact.get('last_name', '').strip().lower() == row.get('Last Name', '').strip().lower() and
                                        scraped_contact.get('first_name', '') and row.get('First Name', '')):  # Ensure not matching empty names
                                        
                                        # We found a match! Update this row with our data
                                        matched = True
                                        matched_indices.add(i)
                                        
                                        # Combine phone numbers, removing duplicates
                                        all_phones = scraped_contact.get('phones', [])
                                        all_mobile_phones = scraped_contact.get('mobile_phones', [])
                                        all_landlines = scraped_contact.get('landlines', [])
                                        
                                        # Update the original row with our scraped data
                                        original_data[i]['Phone'] = ', '.join(set(all_phones))
                                        original_data[i]['Mobile Phone'] = ', '.join(set(all_mobile_phones))
                                        original_data[i]['Landline'] = ', '.join(set(all_landlines))
                                        original_data[i]['Email'] = scraped_contact.get('email', '')
                                        original_data[i]['Propstream Updated Date & Time'] = timestamp
                                        break
                            # Try matching by other identifiers
                            else:
                                identifier_val = None
                                # For simpler identifiers like Zip or Address
                                if len(identifier_set) == 1:
                                    identifier_col = identifier_set[0]
                                    # Try to find this identifier in the scraped data based on likely field patterns
                                    if identifier_col == 'Zip':
                                        # Extract zip from any address field in scraped data
                                        # This is just a simple heuristic - in reality would need more sophisticated matching
                                        for field in ['address', 'full_address', 'property_address']:
                                            address = scraped_contact.get(field, '')
                                            if address:
                                                zip_match = re.search(r'\b\d{5}(?:-\d{4})?\b', address)
                                                if zip_match:
                                                    identifier_val = zip_match.group(0)
                                                    break
                                    elif identifier_col in ['Address', 'Street Address', 'Property Address']:
                                        # Use any address field in scraped data
                                        for field in ['address', 'full_address', 'property_address']:
                                            identifier_val = scraped_contact.get(field, '')
                                            if identifier_val:
                                                break
                                                
                                    # If we found a value to match on, try matching each row
                                    if identifier_val:
                                        for i, row in enumerate(original_data):
                                            if i in matched_indices:
                                                continue
                                                
                                            row_val = row.get(identifier_col, '')
                                            # For addresses, do a partial match
                                            if identifier_col in ['Address', 'Street Address', 'Property Address']:
                                                if identifier_val.lower() in row_val.lower() or row_val.lower() in identifier_val.lower():
                                                    matched = True
                                                    matched_indices.add(i)
                                                    
                                                    # Update the original row with our scraped data
                                                    all_phones = scraped_contact.get('phones', [])
                                                    all_mobile_phones = scraped_contact.get('mobile_phones', [])
                                                    all_landlines = scraped_contact.get('landlines', [])
                                                    
                                                    original_data[i]['Phone'] = ', '.join(set(all_phones))
                                                    original_data[i]['Mobile Phone'] = ', '.join(set(all_mobile_phones))
                                                    original_data[i]['Landline'] = ', '.join(set(all_landlines))
                                                    original_data[i]['Email'] = scraped_contact.get('email', '')
                                                    original_data[i]['Propstream Updated Date & Time'] = timestamp
                                                    break
                                            # For exact identifiers like zip, do exact match
                                            elif row_val.strip() == identifier_val.strip():
                                                matched = True
                                                matched_indices.add(i)
                                                
                                                # Update the original row with our scraped data
                                                all_phones = scraped_contact.get('phones', [])
                                                all_mobile_phones = scraped_contact.get('mobile_phones', [])
                                                all_landlines = scraped_contact.get('landlines', [])
                                                
                                                original_data[i]['Phone'] = ', '.join(set(all_phones))
                                                original_data[i]['Mobile Phone'] = ', '.join(set(all_mobile_phones))
                                                original_data[i]['Landline'] = ', '.join(set(all_landlines))
                                                original_data[i]['Email'] = scraped_contact.get('email', '')
                                                original_data[i]['Propstream Updated Date & Time'] = timestamp
                                                break
                
                # If we have unmatched scraped data and unmatched original rows,
                # assign the data sequentially based on order
                unmatched_scraped = [sc for i, sc in enumerate(self.scraped_data) if i not in matched_indices]
                unmatched_rows = [i for i in range(len(original_data)) if i not in matched_indices]
                
                # Match by position (this is a fallback if we couldn't match by identifiers)
                for i in range(min(len(unmatched_scraped), len(unmatched_rows))):
                    row_idx = unmatched_rows[i]
                    scraped_contact = unmatched_scraped[i]
                    
                    # Combine phone numbers, removing duplicates
                    all_phones = scraped_contact.get('phones', [])
                    all_mobile_phones = scraped_contact.get('mobile_phones', [])
                    all_landlines = scraped_contact.get('landlines', [])
                    
                    # Update the original row with our scraped data
                    original_data[row_idx]['Phone'] = ', '.join(set(all_phones))
                    original_data[row_idx]['Mobile Phone'] = ', '.join(set(all_mobile_phones))
                    original_data[row_idx]['Landline'] = ', '.join(set(all_landlines))
                    original_data[row_idx]['Email'] = scraped_contact.get('email', '')
                    original_data[row_idx]['Propstream Updated Date & Time'] = timestamp
                
                # If we still have more scraped data than original rows, add new rows
                remaining_scraped = unmatched_scraped[len(unmatched_rows):]
                for scraped_contact in remaining_scraped:
                    new_row = {}
                    for field in fieldnames:
                        new_row[field] = ''
                    
                    # Set name fields
                    new_row['First Name'] = scraped_contact.get('first_name', '')
                    new_row['Middle Name'] = scraped_contact.get('middle_name', '')
                    new_row['Last Name'] = scraped_contact.get('last_name', '')
                    
                    # Set phone fields
                    new_row['Phone'] = ', '.join(set(scraped_contact.get('phones', [])))
                    new_row['Mobile Phone'] = ', '.join(set(scraped_contact.get('mobile_phones', [])))
                    new_row['Landline'] = ', '.join(set(scraped_contact.get('landlines', [])))
                    
                    # Set email and timestamp
                    new_row['Email'] = scraped_contact.get('email', '')
                    new_row['Propstream Updated Date & Time'] = timestamp
                    
                    original_data.append(new_row)
                
                # Ensure all rows have the new fields
                for row in original_data:
                    for field in new_fields:
                        if field not in row:
                            row[field] = ''
                
                # Write the updated data back to the file
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(original_data)
                
                logger.info(f"Data saved to {output_file} successfully! ({len(original_data)} contacts)")
                return True
            else:
                logger.error(f"File {output_file} is not a CSV file. Only CSV files are supported for updates.")
                return False
                
        except Exception as e:
            logger.error(f"Failed to save data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
    
    def prepare_csv_for_upload(self, file_path):
        """Validate and prepare CSV file for upload to PropStream"""
        try:
            logger.info(f"Preparing CSV file for upload: {file_path}")
            
            # PropStream expected field names
            expected_fields = [
                "First Name", "Middle Name", "Last Name", 
                "Street Address", "City", "State", "Zip"
            ]
            
            # Read the original CSV
            original_data = []
            original_fieldnames = []
            
            with open(file_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                original_fieldnames = reader.fieldnames or []
                original_data = list(reader)
            
            if not original_data:
                logger.error("CSV file is empty. PropStream requires at least one contact.")
                return False
                
            logger.info(f"Original CSV has {len(original_data)} rows with headers: {original_fieldnames}")
            
            # Check if fields need mapping
            missing_fields = [field for field in expected_fields if field not in original_fieldnames]
            
            # If any expected fields are missing, we need to map them
            if missing_fields:
                logger.warning(f"Missing required fields in CSV: {missing_fields}")
                
                # Common variations of field names to check
                field_variations = {
                    "First Name": ["firstname", "first", "fname", "given name"],
                    "Middle Name": ["middlename", "middle", "mname"],
                    "Last Name": ["lastname", "last", "lname", "surname", "family name"],
                    "Street Address": ["address", "street", "property address", "property street", "addr"],
                    "City": ["town", "municipality", "property city"],
                    "State": ["province", "region", "property state"],
                    "Zip": ["zipcode", "postal code", "zip code", "postal", "property zip"]
                }
                
                # Create field mapping
                field_mapping = {}
                for expected_field in missing_fields:
                    # Check for variations in case-insensitive way
                    variations = field_variations.get(expected_field, [])
                    mapped = False
                    
                    for field in original_fieldnames:
                        if field.lower() in [v.lower() for v in variations]:
                            field_mapping[field] = expected_field
                            mapped = True
                            break
                    
                    if not mapped:
                        logger.warning(f"Could not map {expected_field} to any field in the CSV")
                
                # If we have mappings, create a new CSV file with correct headers
                if field_mapping:
                    logger.info(f"Mapping fields: {field_mapping}")
                    
                    new_fieldnames = original_fieldnames.copy()
                    # Add any missing fields
                    for expected_field in missing_fields:
                        if expected_field not in new_fieldnames:
                            new_fieldnames.append(expected_field)
                    
                    # Create new data with mapped fields
                    new_data = []
                    for row in original_data:
                        new_row = row.copy()
                        
                        # Apply mappings
                        for original_field, expected_field in field_mapping.items():
                            if original_field in row:
                                new_row[expected_field] = row[original_field]
                        
                        # Ensure all fields exist
                        for field in new_fieldnames:
                            if field not in new_row:
                                new_row[field] = ""
                                
                        new_data.append(new_row)
                    
                    # Save to a new temporary file
                    temp_file_path = file_path + ".formatted.csv"
                    with open(temp_file_path, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=new_fieldnames)
                        writer.writeheader()
                        writer.writerows(new_data)
                    
                    logger.info(f"Created formatted CSV file: {temp_file_path}")
                    return temp_file_path
            
            # If no mapping needed, use original file
            logger.info("CSV file has all required fields, no formatting needed")
            return file_path
            
        except Exception as e:
            logger.error(f"Error preparing CSV file: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return file_path
    
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
            
            # Step 2.5: Prepare CSV file for upload
            prepared_file_path = self.prepare_csv_for_upload(file_path)
            if not prepared_file_path:
                logger.error("Failed to prepare CSV file, continuing with original file")
                prepared_file_path = file_path
            
            # Step 3: Upload file and create group
            group_id = self.upload_file_and_create_group(prepared_file_path)
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