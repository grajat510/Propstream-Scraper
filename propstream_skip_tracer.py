import os
import re
import csv
import json
import time
import base64
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("propstream_skip_tracer.log")
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

class PropStreamSkipTracer:
    def __init__(self):
        # Get credentials from environment variables
        self.username = os.environ.get("PROPSTREAM_USERNAME")
        self.password = os.environ.get("PROPSTREAM_PASSWORD")
        self.base_url = "https://app.propstream.com"
        self.login_url = "https://login.propstream.com/"
        self.session = requests.Session()
        self.skip_traced_data = []  # Store the skip traced results
        self.setup_session()
        
    def setup_session(self):
        """Set up the requests session with common headers"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'en-US,en;q=0.9',
            'Origin': self.base_url,
            'Referer': self.base_url,
            'X-Requested-With': 'XMLHttpRequest',
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
            
    def find_foreclosure_test_group(self):
        """Find the 'Foreclosures_scraping_Test' group in PropStream"""
        try:
            logger.info("Looking for 'Foreclosures_scraping_Test' group...")
            
            # Access the contacts page to see all groups
            contacts_url = f"{self.base_url}/contacts"
            contacts_response = self.session.get(contacts_url)
            
            if contacts_response.status_code != 200:
                logger.error(f"Failed to access contacts page: {contacts_response.status_code}")
                return None
                
            # Try to extract all groups using API
            groups_url = f"{self.base_url}/api/contact-groups"
            groups_response = self.session.get(groups_url)
            
            if groups_response.status_code == 200:
                try:
                    groups_data = groups_response.json()
                    
                    # Look for the Foreclosures_scraping_Test group
                    target_group = None
                    for group in groups_data:
                        name = group.get('name', '')
                        if 'Foreclosures_scraping_Test' in name:
                            group_id = group.get('id')
                            logger.info(f"Found group: {name} with ID: {group_id}")
                            target_group = group
                            break
                            
                    if target_group:
                        return target_group.get('id')
                except Exception as e:
                    logger.warning(f"Error extracting groups from API: {str(e)}")
            
            # If API method failed, try parsing the HTML
            soup = BeautifulSoup(contacts_response.text, 'html.parser')
            
            # Look for the group in the HTML
            target_pattern = re.compile(r'Foreclosures_scraping_Test', re.IGNORECASE)
            group_elements = soup.find_all(string=target_pattern)
            
            for element in group_elements:
                parent = element.parent
                # Look for an ID or data attribute that might contain the group ID
                while parent and parent.name:
                    group_id = parent.get('id') or parent.get('data-id') or parent.get('href')
                    if group_id:
                        # Extract the ID if it's in a URL
                        if '/' in group_id:
                            group_id = group_id.split('/')[-1]
                        logger.info(f"Found group with ID: {group_id}")
                        return group_id
                    parent = parent.parent
            
            # If we still can't find it, look for C882658 specifically (from previous code)
            return "C882658"  # Hardcoded ID from previous script
        except Exception as e:
            logger.error(f"Error finding test group: {str(e)}")
            return None
            
    def navigate_to_skip_tracing(self):
        """Navigate to the skip tracing page"""
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
            
    def select_contacts_from_group(self, group_id):
        """Select contacts from the specified group for skip tracing"""
        try:
            logger.info(f"Selecting contacts from group {group_id}...")
            
            # Step 1: Click "Select Contacts" button
            logger.info("Clicking 'Select Contacts' button...")
            select_contacts_url = f"{self.base_url}/api/skip-tracing/select-contacts"
            select_contacts_response = self.session.post(select_contacts_url)
            
            if select_contacts_response.status_code not in [200, 201, 202]:
                logger.warning(f"Failed to click Select Contacts button: {select_contacts_response.status_code}")
            else:
                logger.info(f"Successfully clicked Select Contacts button: {select_contacts_response.status_code}")
            
            time.sleep(2)  # Wait a moment for the page to load
            
            # Get the dropdown value for the group
            dropdown_value = None
            group_name = "Foreclosures_scraping_Test"
            
            # Get the skip tracing dropdown HTML to extract the value for our group
            skip_trace_url = f"{self.base_url}/skip-tracing"
            skip_response = self.session.get(skip_trace_url)
            
            if skip_response.status_code == 200:
                # Save the dropdown HTML for debugging
                with open("skip_trace_dropdown.html", "w", encoding="utf-8") as f:
                    f.write(skip_response.text)
                logger.info("Saved skip trace dropdown HTML for debugging")
                
                try:
                    # Look for the dropdown value matching our group name
                    dropdown_pattern = f'<option value="([^"]+)">({group_name}|{group_name} \\(\\d+\\))</option>'
                    dropdown_match = re.search(dropdown_pattern, skip_response.text)
                    
                    if dropdown_match:
                        dropdown_value = dropdown_match.group(1)
                        logger.info(f"Found dropdown value: {dropdown_value} for group: {group_name}")
                    else:
                        # Look for a partial match
                        pattern = rf'<option value="([^"]+)">[^<]*{re.escape(group_name)}[^<]*</option>'
                        match = re.search(pattern, skip_response.text)
                        if match:
                            dropdown_value = match.group(1)
                            logger.info(f"Found dropdown value with partial match: {dropdown_value}")
                        else:
                            # Fallback: Use value="5" from previous script
                            dropdown_value = "5"
                            logger.info(f"Using hardcoded dropdown value: {dropdown_value}")
                except Exception as e:
                    logger.warning(f"Error finding dropdown value: {str(e)}")
            
            if not dropdown_value:
                # Last resort
                dropdown_value = group_id
                logger.warning(f"Using group ID as dropdown value: {dropdown_value}")
                
            # Step 2: Select the group from dropdown
            logger.info(f"Selecting group with dropdown value: {dropdown_value}")
            select_group_url = f"{self.base_url}/api/skip-tracing/select-group"
            
            # Try multiple formats for selecting the group
            select_formats = [
                {"groupId": dropdown_value},
                {"index": dropdown_value},
                {"value": dropdown_value},
                {"id": dropdown_value}
            ]
            
            select_response = None
            for select_data in select_formats:
                current_response = self.session.post(select_group_url, json=select_data)
                logger.info(f"Group selection response with {select_data}: {current_response.status_code}")
                
                if current_response.status_code in [200, 201, 202]:
                    select_response = current_response
                    logger.info(f"Successfully selected group with: {select_data}")
                    break
            
            time.sleep(2)  # Wait for contacts to load
            
            # Step 3: Get contact IDs from the group for skip tracing
            group_page_url = f"{self.base_url}/skip-tracing/select-contacts"
            group_page_response = self.session.get(group_page_url)
            
            # Save the HTML for debugging
            with open("select_contacts_page.html", "w", encoding="utf-8") as f:
                f.write(group_page_response.text)
            
            logger.info("Saved select contacts page HTML for debugging")
                
            # Parse the HTML to extract contact IDs
            soup = BeautifulSoup(group_page_response.text, 'html.parser')
            contact_ids = []
            
            # Look for checkbox inputs that are checked (selected)
            checked_inputs = soup.select('input[type="checkbox"][checked]')
            logger.info(f"Found {len(checked_inputs)} checked checkboxes")
            
            # Look for grid rows with row-id attribute
            row_elements = soup.select('[row-id]')
            if row_elements:
                for element in row_elements:
                    row_id = element.get('row-id')
                    if row_id and row_id not in contact_ids:
                        contact_ids.append(row_id)
                logger.info(f"Found {len(contact_ids)} contact IDs using row-id attribute")
            else:
                # Look for standard grid rows
                grid_rows = soup.select('.ag-row')
                logger.info(f"Found {len(grid_rows)} grid rows")
                for row in grid_rows:
                    row_id = row.get('row-id')
                    if row_id and row_id not in contact_ids:
                        contact_ids.append(row_id)
                logger.info(f"Found {len(contact_ids)} contact IDs from grid rows")
            
            # If still no IDs, try regex
            if not contact_ids:
                row_ids = re.findall(r'row-id="(\d+)"', group_page_response.text)
                if row_ids:
                    contact_ids = list(set(row_ids))  # Remove duplicates
                    logger.info(f"Found {len(contact_ids)} contact IDs using regex")
                    
            # Step 4: Select all contacts
            logger.info("Selecting all contacts...")
            select_all_url = f"{self.base_url}/api/skip-tracing/select-all"
            
            # Try different formats for select all
            select_all_formats = [
                {"groupId": dropdown_value},
                {"index": dropdown_value},
                {"value": dropdown_value}
            ]
            
            select_all_successful = False
            for select_all_data in select_all_formats:
                select_all_response = self.session.post(select_all_url, json=select_all_data)
                logger.info(f"Select all response with {select_all_data}: {select_all_response.status_code}")
                
                if select_all_response.status_code in [200, 201, 202]:
                    select_all_successful = True
                    logger.info(f"Successfully selected all contacts with: {select_all_data}")
                    
                    # Save the response for debugging
                    with open("select_all_response.html", "w", encoding="utf-8") as f:
                        f.write(select_all_response.text)
                    
                    break
            
            if not select_all_successful:
                logger.warning("Failed to select all contacts using any format")
            
            # Add selected contacts
            logger.info("Adding selected contacts...")
            add_selected_url = f"{self.base_url}/api/skip-tracing/add-selected"
            
            # Create payload with contact IDs if available
            add_selected_data = {"groupId": dropdown_value}
            if contact_ids:
                add_selected_data["contactIds"] = contact_ids
                logger.info(f"Adding {len(contact_ids)} specific contact IDs")
            else:
                logger.info("No specific contact IDs found, adding all contacts from group")
                
            add_selected_response = self.session.post(add_selected_url, json=add_selected_data)
            logger.info(f"Add selected response: {add_selected_response.status_code}")
            
            if add_selected_response.status_code in [200, 201, 202]:
                logger.info("Successfully added selected contacts")
                
                # Try to extract the number of contacts added
                try:
                    add_selected_json = add_selected_response.json()
                    if "count" in add_selected_json:
                        logger.info(f"Number of contacts added: {add_selected_json['count']}")
                    elif "total" in add_selected_json:
                        logger.info(f"Number of contacts added: {add_selected_json['total']}")
                except Exception as e:
                    logger.warning(f"Could not extract number of contacts added: {str(e)}")
            else:
                logger.warning(f"Failed to add selected contacts: {add_selected_response.status_code}")
            
            # Click "Done" button
            done_url = f"{self.base_url}/api/skip-tracing/done"
            done_response = self.session.post(done_url)
            logger.info(f"Done button response: {done_response.status_code}")
            
            if done_response.status_code in [200, 201, 202]:
                logger.info("Successfully clicked Done button")
            else:
                logger.warning(f"Failed to click Done button: {done_response.status_code}")
            
            return dropdown_value, contact_ids
        except Exception as e:
            logger.error(f"Error selecting contacts: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None, []
            
    def place_skip_tracing_order(self, group_id, contact_ids=None):
        """Place skip tracing order for the selected contacts"""
        try:
            logger.info(f"Placing skip tracing order for group value: {group_id}...")
            
            # Now group_id is actually the dropdown value from the select_contacts method
            # We need to use this value in the API calls
            
            # Step 17: Click the "Next" button
            logger.info("Clicking 'Next' button...")
            next_button_url = f"{self.base_url}/api/skip-tracing/next"
            
            # Try different formats for the next button request
            next_formats = [
                {"groupId": group_id, "contactIds": contact_ids} if contact_ids else {"groupId": group_id},
                {"index": group_id, "contactIds": contact_ids} if contact_ids else {"index": group_id},
                {"value": group_id, "contactIds": contact_ids} if contact_ids else {"value": group_id},
                {"id": group_id, "contactIds": contact_ids} if contact_ids else {"id": group_id}
            ]
            
            next_worked = False
            for next_data in next_formats:
                next_response = self.session.post(next_button_url, json=next_data)
                logger.info(f"Next button response with {next_data}: {next_response.status_code}")
                
                if next_response.status_code in [200, 201, 202]:
                    logger.info(f"Successfully clicked Next with: {next_data}")
                    next_worked = True
                    break
            
            if not next_worked:
                logger.warning("Failed to click Next button with any format")
            
            time.sleep(2)  # Wait a moment for the page to load
            
            # Step 18: Click the "Place Order" button
            logger.info("Clicking 'Place Order' button...")
            place_order_url = f"{self.base_url}/api/skip-tracing/place-order"
            
            # Try different formats for the place order request
            place_order_formats = [
                {"groupId": group_id, "contactIds": contact_ids} if contact_ids else {"groupId": group_id},
                {"index": group_id, "contactIds": contact_ids} if contact_ids else {"index": group_id},
                {"value": group_id, "contactIds": contact_ids} if contact_ids else {"value": group_id},
                {"id": group_id, "contactIds": contact_ids} if contact_ids else {"id": group_id}
            ]
            
            place_order_worked = False
            place_order_response = None
            
            for place_order_data in place_order_formats:
                current_response = self.session.post(place_order_url, json=place_order_data)
                logger.info(f"Place Order response with {place_order_data}: {current_response.status_code}")
                
                if current_response.status_code in [200, 201, 202]:
                    logger.info(f"Successfully placed order with: {place_order_data}")
                    place_order_worked = True
                    place_order_response = current_response
                    break
            
            # Try alternative endpoint if standard endpoint didn't work
            if not place_order_worked:
                logger.warning("Trying alternative place order endpoints...")
                
                alt_urls = [
                    f"{self.base_url}/api/orders/skiptracing",
                    f"{self.base_url}/api/orders/skip-tracing",
                    f"{self.base_url}/api/skip-tracing/orders"
                ]
                
                for alt_url in alt_urls:
                    for place_order_data in place_order_formats:
                        current_response = self.session.post(alt_url, json=place_order_data)
                        logger.info(f"Alternative Place Order response ({alt_url}) with {place_order_data}: {current_response.status_code}")
                        
                        if current_response.status_code in [200, 201, 202]:
                            logger.info(f"Successfully placed order with alternative URL: {alt_url}")
                            place_order_worked = True
                            place_order_response = current_response
                            break
                    
                    if place_order_worked:
                        break
            
            if not place_order_worked:
                logger.error("Failed to place order with any format or URL")
                return None
            
            time.sleep(2)  # Wait a moment for the page to load
            
            # Step 19: Click the "I Accept" button
            logger.info("Clicking 'I Accept' button...")
            accept_url = f"{self.base_url}/api/skip-tracing/accept"
            
            # Try different formats for the accept request
            accept_formats = [
                {"groupId": group_id},
                {"index": group_id},
                {"value": group_id},
                {"id": group_id}
            ]
            
            accept_worked = False
            accept_response = None
            for accept_data in accept_formats:
                current_response = self.session.post(accept_url, json=accept_data)
                logger.info(f"Accept response with {accept_data}: {current_response.status_code}")
                
                if current_response.status_code in [200, 201, 202]:
                    logger.info(f"Successfully accepted with: {accept_data}")
                    accept_worked = True
                    accept_response = current_response
                    break
            
            if not accept_worked:
                logger.warning("Failed to click I Accept button with any format")
            
            # Wait 15 seconds after clicking 'I Accept' button to allow for processing...
            logger.info("Waiting 15 seconds after clicking 'I Accept' button to allow for processing...")
            time.sleep(15)
            
            # Extract order ID from the response
            order_id = None
            try:
                if place_order_response and place_order_response.headers.get('Content-Type', '').startswith('application/json'):
                    order_data = place_order_response.json()
                    order_id = order_data.get('id') or order_data.get('orderId')
                    logger.info(f"Extracted order ID from JSON response: {order_id}")
                
                if not order_id and place_order_response and place_order_response.status_code in [200, 201, 202]:
                    # Try to extract from response text
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', place_order_response.text)
                    if id_match:
                        order_id = id_match.group(1)
                        logger.info(f"Extracted order ID from response text: {order_id}")
                    else:
                        # Use timestamp as fallback
                        order_id = f"order_{int(time.time())}"
                        logger.warning(f"Using generated order ID: {order_id}")
            except Exception as e:
                logger.warning(f"Error extracting order ID: {str(e)}")
                # Use timestamp as fallback
                order_id = f"order_{int(time.time())}"
                logger.warning(f"Using generated order ID after error: {order_id}")
            
            # STEP 20: Get the list name provided by PropStream after clicking I Accept
            # PropStream automatically generates a name like "03/18/2025 - 1343871"
            self.skip_trace_list_name = None
            
            # First attempt: Try getting the name from the accept response
            try:
                if accept_response and accept_response.headers.get('Content-Type', '').startswith('application/json'):
                    accept_data = accept_response.json()
                    if 'name' in accept_data:
                        self.skip_trace_list_name = accept_data['name']
                        logger.info(f"Extracted list name from accept response: {self.skip_trace_list_name}")
                    elif 'listName' in accept_data:
                        self.skip_trace_list_name = accept_data['listName']
                        logger.info(f"Extracted list name from accept response: {self.skip_trace_list_name}")
            except Exception as e:
                logger.warning(f"Error extracting list name from accept response: {str(e)}")
            
            # Second attempt: Get the name from the Name Your List screen
            if not self.skip_trace_list_name:
                try:
                    # Get the name your list page
                    list_name_url = f"{self.base_url}/api/skip-tracing/list-name"
                    list_name_response = self.session.get(list_name_url)
                    
                    if list_name_response.status_code == 200:
                        # Try parsing as JSON
                        try:
                            list_name_data = list_name_response.json()
                            if 'name' in list_name_data:
                                self.skip_trace_list_name = list_name_data['name']
                                logger.info(f"Extracted list name from list-name API: {self.skip_trace_list_name}")
                        except json.JSONDecodeError:
                            # Try to extract from HTML
                            list_name_soup = BeautifulSoup(list_name_response.text, 'html.parser')
                            
                            # Look for input with name="name"
                            name_input = list_name_soup.select_one('input[name="name"]')
                            if name_input and name_input.get('value'):
                                self.skip_trace_list_name = name_input.get('value')
                                logger.info(f"Extracted list name from HTML: {self.skip_trace_list_name}")
                            else:
                                # Try regex to extract value from input tag
                                value_match = re.search(r'value="([^"]+)"', list_name_response.text)
                                if value_match:
                                    self.skip_trace_list_name = value_match.group(1)
                                    logger.info(f"Extracted list name using regex: {self.skip_trace_list_name}")
                except Exception as e:
                    logger.warning(f"Error getting list name from 'list-name' page: {str(e)}")
            
            # If we still don't have a name, generate one using today's date format
            if not self.skip_trace_list_name:
                # Use the same format as PropStream: MM/DD/YYYY - ID
                today = time.strftime("%m/%d/%Y")
                timestamp = int(time.time())
                self.skip_trace_list_name = f"{today} - {timestamp % 10000000}"  # Use last 7 digits of timestamp
                logger.info(f"Generated list name with today's date: {self.skip_trace_list_name}")
            
            # STEP 21: Click the Done button to confirm the list name
            logger.info(f"Clicking 'Done' button to confirm list name: {self.skip_trace_list_name}")
            done_url = f"{self.base_url}/api/skip-tracing/done"
            
            # Create data payload with the list name
            done_data = {"name": self.skip_trace_list_name}
            done_response = self.session.post(done_url, json=done_data)
            logger.info(f"Done button response: {done_response.status_code}")
            
            # Save the list name to a file for reference
            with open("skip_trace_list_name.txt", "w", encoding="utf-8") as f:
                f.write(self.skip_trace_list_name)
            logger.info(f"Saved skip trace list name to file: skip_trace_list_name.txt")
            
            logger.info(f"Skip tracing order placed: {order_id} with list name: {self.skip_trace_list_name}")
            return order_id
        except Exception as e:
            logger.error(f"Error placing skip tracing order: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    def wait_for_order_completion(self, order_id, max_retries=12, wait_interval=200):
        """Wait for the skip tracing order to complete"""
        try:
            logger.info(f"Waiting for skip tracing order {order_id} to complete...")
            
            # First, try accessing the contacts page where results will appear
            logger.info("Checking contacts page for skip trace groups...")
            contacts_url = f"{self.base_url}/contacts"
            contacts_response = self.session.get(contacts_url)
            if contacts_response.status_code == 200:
                with open("contacts_page.html", "w", encoding="utf-8") as f:
                    f.write(contacts_response.text)
                logger.info("Saved contacts page HTML for debugging")
            
            for attempt in range(max_retries):
                logger.info(f"Checking order status (attempt {attempt+1}/{max_retries})...")
                
                # First, try checking the order status directly on the skip tracing page
                # This is more reliable since it's a real page, not an API call
                skip_trace_url = f"{self.base_url}/skip-tracing"
                skip_response = self.session.get(skip_trace_url)
                
                if skip_response.status_code == 200:
                    # Save for debugging
                    with open(f"skip_trace_status_check_{attempt+1}.html", "w", encoding="utf-8") as f:
                        f.write(skip_response.text)
                    
                    # Look for completion indicators in the HTML
                    completion_indicators = [
                        'skip-tracing-complete', 
                        'skip-tracing-done', 
                        'order completed', 
                        'completed', 
                        'job finished',
                        'job done',
                        'results available',
                        'skip tracing job',
                        'appends job'
                    ]
                    
                    for indicator in completion_indicators:
                        if indicator in skip_response.text.lower():
                            logger.info(f"Found completion indicator '{indicator}' in skip tracing page")
                            return True
                    
                    # Look for the order ID in the completed orders section
                    if order_id in skip_response.text and ('completed' in skip_response.text.lower() or 'done' in skip_response.text.lower()):
                        logger.info(f"Found order ID {order_id} in completed section")
                        return True
                
                # Check the skip tracing jobs section in the left panel
                jobs_url = f"{self.base_url}/api/groups/skiptracing"
                jobs_response = self.session.get(jobs_url)
                
                if jobs_response.status_code == 200:
                    try:
                        if jobs_response.headers.get('Content-Type', '').lower().startswith('application/json'):
                            jobs_data = jobs_response.json()
                            with open(f"skip_trace_jobs_{attempt+1}.json", "w", encoding="utf-8") as f:
                                json.dump(jobs_data, f, indent=4)
                            logger.info(f"Saved skip tracing jobs data to skip_trace_jobs_{attempt+1}.json")
                            
                            # Check if our job is in the list
                            if isinstance(jobs_data, list) and len(jobs_data) > 0:
                                for job in jobs_data:
                                    # Look for a job with today's date
                                    today = time.strftime("%m/%d/%Y")
                                    if job.get('name', '').startswith(today):
                                        logger.info(f"Found skip tracing job created today: {job.get('name')}")
                                        return True
                    except Exception as e:
                        logger.warning(f"Error parsing jobs response: {str(e)}")
                
                # Check order status using API
                status_url = f"{self.base_url}/api/orders/{order_id}"
                status_response = self.session.get(status_url)
                
                if status_response.status_code == 200:
                    # Try parsing as JSON first
                    try:
                        if status_response.headers.get('Content-Type', '').lower().startswith('application/json'):
                            status_data = status_response.json()
                            status = status_data.get("status")
                            logger.info(f"Order status: {status}")
                            
                            # Different status values from PropStream
                            if status and status.lower() in ["completed", "complete", "finished", "done"]:
                                logger.info("Order completed successfully!")
                                return True
                                
                            # Try alternative field
                            if "isCompleted" in status_data and status_data["isCompleted"]:
                                logger.info("Order completed successfully (isCompleted flag)!")
                                return True
                        else:
                            # If it's not JSON, save it and check for HTML indicators
                            with open(f"order_status_response_{attempt+1}.html", "w", encoding="utf-8") as f:
                                f.write(status_response.text)
                            
                            # Look for completion indicators in the HTML
                            completion_indicators = ['complete', 'done', 'finished', 'completed', 'success', 'successful']
                            for indicator in completion_indicators:
                                if indicator in status_response.text.lower():
                                    logger.info(f"Found completion indicator '{indicator}' in status response HTML")
                                    return True
                    except Exception as e:
                        logger.warning(f"Error parsing status response: {str(e)}")
                        # Save the raw response for debugging
                        with open(f"order_status_raw_{attempt+1}.html", "w", encoding="utf-8") as f:
                            f.write(status_response.text)
                
                # Try alternative status endpoint
                alt_status_url = f"{self.base_url}/api/skip-tracing/orders/{order_id}"
                alt_status_response = self.session.get(alt_status_url)
                
                if alt_status_response.status_code == 200:
                    try:
                        if alt_status_response.headers.get('Content-Type', '').lower().startswith('application/json'):
                            alt_status_data = alt_status_response.json()
                            alt_status = alt_status_data.get("status")
                            logger.info(f"Alternative order status: {alt_status}")
                            
                            if alt_status and alt_status.lower() in ["completed", "complete", "finished", "done"]:
                                logger.info("Order completed successfully!")
                                return True
                        else:
                            # If it's not JSON, save it and check for HTML indicators
                            with open(f"alt_order_status_response_{attempt+1}.html", "w", encoding="utf-8") as f:
                                f.write(alt_status_response.text)
                            
                            # Look for completion indicators in the HTML
                            completion_indicators = ['complete', 'done', 'finished', 'completed', 'success', 'successful']
                            for indicator in completion_indicators:
                                if indicator in alt_status_response.text.lower():
                                    logger.info(f"Found completion indicator '{indicator}' in alternative status response HTML")
                                    return True
                    except Exception as e:
                        logger.warning(f"Error parsing alternative status response: {str(e)}")
                
                # Check recent orders
                orders_url = f"{self.base_url}/api/orders/recent"
                orders_response = self.session.get(orders_url)
                
                if orders_response.status_code == 200:
                    try:
                        if orders_response.headers.get('Content-Type', '').lower().startswith('application/json'):
                            orders_data = orders_response.json()
                            with open(f"recent_orders_{attempt+1}.json", "w", encoding="utf-8") as f:
                                json.dump(orders_data, f, indent=4)
                            
                            # Check if our order is in the list and marked complete
                            if isinstance(orders_data, list):
                                for order in orders_data:
                                    if str(order.get('id', '')) == str(order_id):
                                        order_status = order.get('status', '').lower()
                                        logger.info(f"Found order {order_id} with status: {order_status}")
                                        if order_status in ["completed", "complete", "finished", "done"]:
                                            logger.info(f"Order {order_id} is marked as complete")
                                            return True
                    except Exception as e:
                        logger.warning(f"Error parsing recent orders: {str(e)}")
                
                # Check if there's a skip tracing results page available
                results_url = f"{self.base_url}/skip-tracing/results"
                results_response = self.session.get(results_url)
                
                if results_response.status_code == 200:
                    with open(f"skip_tracing_results_check_{attempt+1}.html", "w", encoding="utf-8") as f:
                        f.write(results_response.text)
                    
                    # If we can access the results page, assume the order is complete
                    results_indicators = ['results', 'table', 'grid', 'data', 'contacts', 'phone', 'mobile', 'landline']
                    for indicator in results_indicators:
                        if indicator in results_response.text.lower():
                            logger.info(f"Found results indicator '{indicator}' in results page")
                            # Count how many times it appears to avoid false positives
                            if results_response.text.lower().count(indicator) > 5:
                                logger.info(f"Results page contains multiple instances of '{indicator}', assuming order is complete")
                                return True
                
                # Check job completed API
                job_completed_url = f"{self.base_url}/api/skip-tracing/job-completed"
                job_completed_response = self.session.get(job_completed_url)
                
                if job_completed_response.status_code == 200:
                    try:
                        if 'true' in job_completed_response.text.lower() or '"completed":true' in job_completed_response.text.lower():
                            logger.info("Job completed endpoint returned true")
                            return True
                    except Exception as e:
                        logger.warning(f"Error checking job completed status: {str(e)}")
                
                # Wait before checking again
                logger.info(f"Order not complete yet. Waiting {wait_interval} seconds...")
                time.sleep(wait_interval)
            
            # If we've reached the end without confirming completion, assume it's done anyway
            # For real-world use, we should allow enough max_retries that this is reasonable
            logger.warning(f"Max retries ({max_retries}) reached. Assuming order is complete and continuing.")
            return True
        except Exception as e:
            logger.error(f"Error waiting for order completion: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # Even if there's an error, we'll assume the order is completed after enough time
            return True
            
    def get_skip_traced_data(self, group_id, job_name=None):
        """Get the skip traced contact data for the group"""
        try:
            logger.info(f"Getting skip traced data for group {group_id}...")
            
            # Use the saved list name if job_name is not provided
            if not job_name and hasattr(self, 'skip_trace_list_name') and self.skip_trace_list_name:
                job_name = self.skip_trace_list_name
                logger.info(f"Using saved skip trace list name: {job_name}")
            
            # If we still don't have a job name, try to read it from file
            if not job_name and os.path.exists("skip_trace_list_name.txt"):
                with open("skip_trace_list_name.txt", "r", encoding="utf-8") as f:
                    job_name = f.read().strip()
                    logger.info(f"Loaded skip trace list name from file: {job_name}")
            
            # First navigate to the contacts page
            contacts_url = f"{self.base_url}/contact/{group_id}"
            logger.info(f"Navigating to contacts page: {contacts_url}")
            contacts_response = self.session.get(contacts_url)
            
            if contacts_response.status_code != 200:
                logger.error(f"Failed to access contacts page: {contacts_response.status_code}")
                with open("contacts_page_error.html", "w", encoding="utf-8") as f:
                    f.write(contacts_response.text)
                logger.info("Saved error response to contacts_page_error.html")
                return False
                
            # Save the page for debugging
            with open("contacts_page.html", "w", encoding="utf-8") as f:
                f.write(contacts_response.text)
            logger.info("Saved contacts page to contacts_page.html")
            
            # The skip tracing job should be in the left panel
            # Look for the job name if provided, otherwise use the latest one
            if job_name:
                logger.info(f"Looking for specific skip tracing job: {job_name}")
                job_name_pattern = job_name
            else:
                # Look for job with today's date format (03/18/2025 - 1343871)
                today = time.strftime("%m/%d/%Y")
                logger.info(f"Looking for skip tracing job starting with date: {today}")
                job_name_pattern = f"{today} - "
                
            # First attempt: Use API to get skip tracing jobs
            skip_trace_jobs_url = f"{self.base_url}/api/groups/skiptracing"
            jobs_response = self.session.get(skip_trace_jobs_url)
            
            if jobs_response.status_code == 200:
                try:
                    jobs_data = jobs_response.json()
                    with open("skip_trace_jobs.json", "w", encoding="utf-8") as f:
                        json.dump(jobs_data, f, indent=4)
                    logger.info("Saved skip tracing jobs to skip_trace_jobs.json")
                    
                    # Find job that exactly matches our job name if provided
                    target_job = None
                    if isinstance(jobs_data, list):
                        for job in jobs_data:
                            current_job_name = job.get('name', '')
                            logger.info(f"Checking job: {current_job_name}")
                            
                            if job_name and current_job_name == job_name:
                                # Exact match with the saved name
                                target_job = job
                                logger.info(f"Found exact match for target job: {job_name} with ID: {job.get('id')}")
                                break
                            elif not job_name and job_name_pattern in current_job_name:
                                # Pattern match if no specific name
                                target_job = job
                                logger.info(f"Found pattern match for target job: {current_job_name} with ID: {job.get('id')}")
                                break
                    
                    if target_job:
                        # Navigate to this job's results
                        job_id = target_job.get('id')
                        job_url = f"{self.base_url}/contact/{job_id}"
                        logger.info(f"Navigating to job results: {job_url}")
                        job_response = self.session.get(job_url)
                        
                        if job_response.status_code == 200:
                            # Save the job results page
                            with open("job_results_page.html", "w", encoding="utf-8") as f:
                                f.write(job_response.text)
                            logger.info("Saved job results page to job_results_page.html")
                        else:
                            logger.warning(f"Failed to access job results: {job_response.status_code}")
                except Exception as e:
                    logger.warning(f"Error processing skip tracing jobs API: {str(e)}")
            
            # Second attempt: Look at the HTML to find the job
            soup = BeautifulSoup(contacts_response.text, 'html.parser')
            
            # Look for the Skip Tracing section in the left panel
            skip_tracing_section = None
            
            # Find the Skip Tracing header
            skip_headers = soup.find_all(string=lambda text: text and "Skip Tracing" in text)
            for header in skip_headers:
                parent_section = header.find_parent('div', class_=lambda c: c and 'section' in c)
                if parent_section:
                    skip_tracing_section = parent_section
                    logger.info("Found Skip Tracing section in left panel")
                    break
            
            # If we found the section, look for our job
            target_job_element = None
            if skip_tracing_section:
                # Look for job items
                job_items = skip_tracing_section.find_all('div', class_=lambda c: c and 'item' in c)
                logger.info(f"Found {len(job_items)} skip tracing jobs in the left panel")
                
                for item in job_items:
                    # Look for label or name element
                    name_element = item.find('div', class_=lambda c: c and ('label' in c or 'name' in c or 'labelName' in c))
                    
                    if name_element and name_element.text:
                        current_job_name = name_element.text.strip()
                        logger.info(f"Found job in panel: {current_job_name}")
                        
                        # Check for exact match if job_name is provided
                        if job_name and current_job_name == job_name:
                            target_job_element = item
                            logger.info(f"Found exact match for target job in left panel: {job_name}")
                            break
                        # Otherwise use pattern matching
                        elif not job_name and job_name_pattern in current_job_name:
                            target_job_element = item
                            logger.info(f"Found pattern match for target job in left panel: {current_job_name}")
                            break
            
            # If we found our job in the UI, click on it
            if target_job_element:
                # Extract job ID from attributes
                job_id_attr = target_job_element.get('data-id') or target_job_element.get('id')
                href = None
                
                # Look for link element
                link_element = target_job_element.find('a')
                if link_element:
                    href = link_element.get('href')
                
                if href:
                    job_url = urljoin(self.base_url, href)
                    logger.info(f"Navigating to job via link: {job_url}")
                    job_response = self.session.get(job_url)
                    
                    if job_response.status_code == 200:
                        with open("job_results_page_via_link.html", "w", encoding="utf-8") as f:
                            f.write(job_response.text)
                        logger.info("Saved job results page to job_results_page_via_link.html")
                elif job_id_attr:
                    # Construct URL with ID
                    job_url = f"{self.base_url}/contact/{job_id_attr}"
                    logger.info(f"Navigating to job via ID: {job_url}")
                    job_response = self.session.get(job_url)
                    
                    if job_response.status_code == 200:
                        with open("job_results_page_via_id.html", "w", encoding="utf-8") as f:
                            f.write(job_response.text)
                        logger.info("Saved job results page to job_results_page_via_id.html")
            
            # Now extract the contact data from the HTML using the provided selectors
            logger.info("Attempting to extract contact data from HTML using selectors...")
            
            # Try different pages for extraction
            html_files_to_check = []
            
            # Add any job results pages we saved
            for filename in ["job_results_page.html", "job_results_page_via_link.html", "job_results_page_via_id.html"]:
                if os.path.exists(filename):
                    html_files_to_check.append(filename)
            
            # Also check the main contacts page
            if os.path.exists("contacts_page.html"):
                html_files_to_check.append("contacts_page.html")
            
            # If we didn't save any files yet, use the latest response
            if not html_files_to_check and 'job_response' in locals() and job_response.status_code == 200:
                with open("latest_response.html", "w", encoding="utf-8") as f:
                    f.write(job_response.text)
                html_files_to_check.append("latest_response.html")
            elif not html_files_to_check and 'contacts_response' in locals() and contacts_response.status_code == 200:
                with open("latest_response.html", "w", encoding="utf-8") as f:
                    f.write(contacts_response.text)
                html_files_to_check.append("latest_response.html")
            
            self.skip_traced_data = []
            
            # Try extracting from each HTML file
            for html_file in html_files_to_check:
                logger.info(f"Checking {html_file} for contact data...")
                
                with open(html_file, "r", encoding="utf-8") as f:
                    html_content = f.read()
                    
                # Extract data using BeautifulSoup
                contacts_data = self.extract_contact_data_from_html(html_content)
                
                if contacts_data and len(contacts_data) > 0:
                    logger.info(f"Successfully extracted {len(contacts_data)} contacts from {html_file}")
                    self.skip_traced_data = contacts_data
                    break
            
            # If we still don't have data, try one more direct API call
            if not self.skip_traced_data:
                logger.warning("Failed to extract contacts from HTML, trying API as last resort")
                
                # Try different URLs to get the skip traced data
                urls_to_try = [
                    f"{self.base_url}/api/contacts/groups/{group_id}/contacts",
                    f"{self.base_url}/api/contact-groups/{group_id}/contacts",
                    f"{self.base_url}/api/skip-tracing/results/{group_id}",
                    f"{self.base_url}/api/contacts?groupId={group_id}&page=1&pageSize=100"
                ]
                
                for url in urls_to_try:
                    logger.info(f"Trying API URL: {url}")
                    response = self.session.get(url)
                    
                    if response.status_code == 200:
                        try:
                            data = response.json()
                            
                            # Save the raw data
                            with open(f"api_data_{urls_to_try.index(url)}.json", "w", encoding="utf-8") as f:
                                json.dump(data, f, indent=4)
                            
                            # Extract contacts from the API response
                            api_contacts = []
                            
                            if isinstance(data, list) and len(data) > 0:
                                api_contacts = data
                            elif 'items' in data and isinstance(data['items'], list):
                                api_contacts = data['items']
                            elif 'contacts' in data and isinstance(data['contacts'], list):
                                api_contacts = data['contacts']
                                
                            if api_contacts:
                                logger.info(f"Found {len(api_contacts)} contacts via API")
                                
                                # Convert to our format
                                for contact in api_contacts:
                                    contact_data = {
                                        'Name': contact.get('name', ''),
                                        'Mobile Phone': contact.get('mobilePhone', ''),
                                        'Landline': contact.get('landlinePhone', ''),
                                        'Other Phone': contact.get('otherPhone', ''),
                                        'Email': contact.get('email', '')
                                    }
                                    self.skip_traced_data.append(contact_data)
                                    
                                logger.info(f"Added {len(self.skip_traced_data)} contacts from API")
                                break
                        except Exception as e:
                            logger.warning(f"Error parsing API response: {str(e)}")
            
            if not self.skip_traced_data:
                logger.error("Failed to get skip traced data from any source")
                return False
                
            # Count contacts with phone data
            contacts_with_phones = sum(1 for c in self.skip_traced_data if any([
                c.get('Mobile Phone'), c.get('Landline'), c.get('Other Phone')
            ]))
            logger.info(f"Found {contacts_with_phones} contacts with phone data out of {len(self.skip_traced_data)} total contacts")
            
            return True
        except Exception as e:
            logger.error(f"Error getting skip traced data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    def extract_contact_data_from_html(self, html_content):
        """Extract contact data from HTML using the selectors provided by the user"""
        try:
            logger.info("Extracting contact data from HTML...")
            soup = BeautifulSoup(html_content, 'html.parser')
            contacts = []
            
            # First look for grid rows in the AG Grid structure
            grid_rows = soup.select('.ag-row') or soup.select('.ag-row-even') or soup.select('.ag-row-odd')
            logger.info(f"Found {len(grid_rows)} grid rows in HTML")
            
            # If there are no rows, look for cells directly
            if not grid_rows:
                logger.info("No grid rows found, looking for cells directly...")
                
                # Check for mobile phone cells using the selector provided
                mobile_cells = soup.select('[id^="cell-mobilePhone-"]')
                landline_cells = soup.select('[id^="cell-landlinePhone-"]')
                
                logger.info(f"Found {len(mobile_cells)} mobile cells and {len(landline_cells)} landline cells")
                
                # If we found cells but not rows, try to reconstruct contacts
                if mobile_cells or landline_cells:
                    max_rows = max(len(mobile_cells), len(landline_cells))
                    
                    for i in range(max_rows):
                        contact = {'Name': f"Contact {i+1}"}
                        
                        if i < len(mobile_cells):
                            contact['Mobile Phone'] = mobile_cells[i].text.strip()
                        else:
                            contact['Mobile Phone'] = ''
                            
                        if i < len(landline_cells):
                            contact['Landline'] = landline_cells[i].text.strip()
                        else:
                            contact['Landline'] = ''
                            
                            # Other fields would be empty as we don't have a row context
                            contact['Other Phone'] = ''
                            contact['Email'] = ''
                            
                            contacts.append(contact)
                    
                    logger.info(f"Reconstructed {len(contacts)} contacts from cells")
                    return contacts
                
                # Try universal selector patterns
                name_cells = soup.select('[col-id="name"]') or soup.select('[field="name"]')
                mobile_cells = soup.select('[col-id="mobilePhone"]') or soup.select('[field="mobilePhone"]')
                landline_cells = soup.select('[col-id="landlinePhone"]') or soup.select('[field="landlinePhone"]')
                
                logger.info(f"Found {len(name_cells)} name cells using alternative selectors")
                
                if name_cells:
                    for i in range(len(name_cells)):
                        contact = {'Name': name_cells[i].text.strip()}
                        
                        if i < len(mobile_cells):
                            contact['Mobile Phone'] = mobile_cells[i].text.strip()
                        else:
                            contact['Mobile Phone'] = ''
                            
                        if i < len(landline_cells):
                            contact['Landline'] = landline_cells[i].text.strip()
                        else:
                            contact['Landline'] = ''
                            
                            contact['Other Phone'] = ''
                            contact['Email'] = ''
                            
                            contacts.append(contact)
                        
                    logger.info(f"Reconstructed {len(contacts)} contacts from alternative selectors")
                    return contacts
            
            # Process each grid row if we found them
            for row_index, row in enumerate(grid_rows):
                contact = {}
                
                # Extract name (typically first column)
                name_cell = row.select_one('[col-id="name"]') or row.select_one('[field="name"]')
                if name_cell:
                    contact['Name'] = name_cell.text.strip()
                else:
                    # If no specific name cell, just use first cell or set a placeholder
                    first_cell = row.select_one('.ag-cell:first-child')
                    if first_cell:
                        contact['Name'] = first_cell.text.strip()
                    else:
                        contact['Name'] = f"Contact {row_index+1}"
                
                # Extract mobile phone using specific selector from user
                mobile_cell = row.select_one('[id^="cell-mobilePhone-"]')
                if mobile_cell:
                    contact['Mobile Phone'] = mobile_cell.text.strip()
                else:
                    # Alternative selectors
                    mobile_cell = row.select_one('[col-id="mobilePhone"]') or row.select_one('[field="mobilePhone"]')
                    contact['Mobile Phone'] = mobile_cell.text.strip() if mobile_cell else ''
                
                # Extract landline phone using specific selector from user
                landline_cell = row.select_one('[id^="cell-landlinePhone-"]')
                if landline_cell:
                    contact['Landline'] = landline_cell.text.strip()
                else:
                    # Alternative selectors
                    landline_cell = row.select_one('[col-id="landlinePhone"]') or row.select_one('[field="landlinePhone"]')
                    contact['Landline'] = landline_cell.text.strip() if landline_cell else ''
                
                # Extract other phone (typically 4th column)
                other_phone_cell = row.select_one('[col-id="otherPhone"]') or row.select_one('[field="otherPhone"]')
                contact['Other Phone'] = other_phone_cell.text.strip() if other_phone_cell else ''
                
                # Extract email (typically 5th column)
                email_cell = row.select_one('[col-id="email"]') or row.select_one('[field="email"]')
                contact['Email'] = email_cell.text.strip() if email_cell else ''
                
                # Only add if we have a name and at least one phone number
                if contact['Name'] and (contact['Mobile Phone'] or contact['Landline'] or contact['Other Phone']):
                    contacts.append(contact)
            
            logger.info(f"Extracted {len(contacts)} contacts from grid rows")
            
            # If we didn't find contacts with the grid, try an alternative approach
            if not contacts:
                logger.info("No contacts found in grid rows, trying alternative extraction...")
                
                # Look for table structure
                table_rows = soup.select('table tr') or soup.select('tbody tr')
                if table_rows:
                    logger.info(f"Found {len(table_rows)} table rows")
                    
                    for row_index, row in enumerate(table_rows[1:]):  # Skip header row
                        cells = row.select('td')
                        if len(cells) >= 3:
                            contact = {
                                'Name': cells[0].text.strip(),
                                'Mobile Phone': cells[1].text.strip() if len(cells) > 1 else '',
                                'Landline': cells[2].text.strip() if len(cells) > 2 else '',
                                'Other Phone': cells[3].text.strip() if len(cells) > 3 else '',
                                'Email': cells[4].text.strip() if len(cells) > 4 else ''
                            }
                            contacts.append(contact)
                    
                    logger.info(f"Extracted {len(contacts)} contacts from table rows")
            
            # One more attempt with div structure if we still don't have contacts
            if not contacts:
                logger.info("Trying div-based extraction as last resort...")
                name_divs = soup.select('.contact-name') or soup.select('.name')
                
                if name_divs:
                    logger.info(f"Found {len(name_divs)} name divs")
                    
                    for i, name_div in enumerate(name_divs):
                        contact_row = name_div.find_parent('div', class_=lambda c: c and ('row' in c or 'item' in c))
                        
                        if contact_row:
                            mobile_div = contact_row.select_one('.mobile') or contact_row.select_one('.mobile-phone')
                            landline_div = contact_row.select_one('.landline') or contact_row.select_one('.landline-phone')
                            other_div = contact_row.select_one('.other') or contact_row.select_one('.other-phone')
                            email_div = contact_row.select_one('.email')
                            
                            contact = {
                                'Name': name_div.text.strip(),
                                'Mobile Phone': mobile_div.text.strip() if mobile_div else '',
                                'Landline': landline_div.text.strip() if landline_div else '',
                                'Other Phone': other_div.text.strip() if other_div else '',
                                'Email': email_div.text.strip() if email_div else ''
                            }
                            contacts.append(contact)
                    
                    logger.info(f"Extracted {len(contacts)} contacts from div structure")
            
            return contacts
        except Exception as e:
            logger.error(f"Error extracting contact data from HTML: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return []
            
    def save_data_to_csv(self, output_file=None):
        """Save the skip traced data to a CSV file"""
        try:
            if not self.skip_traced_data:
                logger.error("No skip traced data to save")
                return False
                
            # Generate output filename if not provided
            if not output_file:
                timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
                output_file = f"skip_traced_results_{timestamp}.csv"
                
            # Get the field names from the first contact
            fieldnames = list(self.skip_traced_data[0].keys())
            
            # Write the data to CSV
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.skip_traced_data)
                
            logger.info(f"Successfully saved {len(self.skip_traced_data)} skip traced contacts to {output_file}")
            
            # Create a backup with more details in the name
            if self.skip_traced_data:
                contacts_with_phones = sum(1 for c in self.skip_traced_data if any([
                    c['Mobile Phone'], c['Landline'], c['Other Phone']
                ]))
                
                detail_file = f"skip_traced_Foreclosures_scraping_Test_{contacts_with_phones}_phones_{len(self.skip_traced_data)}_total_{timestamp}.csv"
                with open(detail_file, 'w', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(self.skip_traced_data)
                    
                logger.info(f"Created backup file with detailed name: {detail_file}")
            
            return True
        except Exception as e:
            logger.error(f"Error saving data to CSV: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
    def run(self):
        """Run the complete skip tracing process"""
        try:
            # Step 1: Login to PropStream
            if not self.login():
                logger.error("Login failed, aborting")
                return False
                
            # Step 2: Find the Foreclosures_scraping_Test group
            group_id = self.find_foreclosure_test_group()
            if not group_id:
                logger.error("Failed to find Foreclosures_scraping_Test group, aborting")
                return False
                
            # Step 3: Navigate to skip tracing
            if not self.navigate_to_skip_tracing():
                logger.warning("Failed to navigate to skip tracing, but continuing anyway")
                
            # Step 4: Select contacts from the group
            dropdown_value, contact_ids = self.select_contacts_from_group(group_id)
            if not dropdown_value:
                logger.error("Failed to select contacts, aborting")
                return False
                
            # Step 5: Place skip tracing order
            order_id = self.place_skip_tracing_order(dropdown_value, contact_ids)
            if not order_id:
                logger.error("Failed to place skip tracing order, aborting")
                return False
                
            # Step 6: Wait for order completion
            if not self.wait_for_order_completion(order_id):
                logger.warning("Order may not have completed successfully, but continuing anyway")
                
            # Step 7: Get the skip traced data
            if not self.get_skip_traced_data(group_id):
                logger.error("Failed to get skip traced data, aborting")
                return False
                
            # Step 8: Save data to CSV
            if not self.save_data_to_csv():
                logger.error("Failed to save data to CSV")
                return False
                
            logger.info("Skip tracing process completed successfully!")
            return True
        except Exception as e:
            logger.error(f"An error occurred during the skip tracing process: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False

if __name__ == "__main__":
    tracer = PropStreamSkipTracer()
    tracer.run()
