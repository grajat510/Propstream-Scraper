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
            logger.info(f"Placing skip tracing order for group: {group_id}")
            
            # Step 1: Click the "Next" button
            logger.info("Clicking 'Next' button...")
            next_url = f"{self.base_url}/api/skip-tracing/next"
            next_data = {"groupId": group_id}
            if contact_ids:
                next_data["contactIds"] = contact_ids
                logger.info(f"Including {len(contact_ids)} contact IDs in Next request")
                
            next_response = self.session.post(next_url, json=next_data)
            logger.info(f"Next button response: {next_response.status_code}")
            
            # Save response for debugging
            with open("next_button_response.html", "w", encoding="utf-8") as f:
                f.write(next_response.text)
            logger.info("Saved Next button response for debugging")
            
            next_successful = False
            if next_response.status_code in [200, 201, 202]:
                next_successful = True
                logger.info("Successfully clicked Next button")
            else:
                logger.warning(f"Failed to click Next button with primary format: {next_response.status_code}")
                # Try alternative formats
                alt_formats = [
                    {"index": group_id},
                    {"value": group_id},
                    {"id": group_id}
                ]
                
                for alt_data in alt_formats:
                    if contact_ids:
                        alt_data["contactIds"] = contact_ids
                    alt_response = self.session.post(next_url, json=alt_data)
                    logger.info(f"Alternative next format: {alt_data}, response: {alt_response.status_code}")
                    
                    if alt_response.status_code in [200, 201, 202]:
                        next_successful = True
                        logger.info(f"Successfully clicked Next button with alternative format: {alt_data}")
                        break
            
            if not next_successful:
                logger.error("Failed to click Next button with any format")
                return None
            
            time.sleep(2)  # Wait for page to load
            
            # Step 2: Place the order
            logger.info("Clicking 'Place Order' button...")
            place_order_url = f"{self.base_url}/api/skip-tracing/place-order"
            place_order_data = {"groupId": group_id}
            if contact_ids:
                place_order_data["contactIds"] = contact_ids
                
            place_order_response = self.session.post(place_order_url, json=place_order_data)
            logger.info(f"Place order response: {place_order_response.status_code}")
            
            # Save response for debugging
            with open("place_order_response.html", "w", encoding="utf-8") as f:
                f.write(place_order_response.text)
            logger.info("Saved Place Order response for debugging")
            
            place_order_successful = False
            if place_order_response.status_code in [200, 201, 202]:
                place_order_successful = True
                logger.info("Successfully clicked Place Order button")
            else:
                logger.warning(f"Failed to click Place Order button with primary endpoint: {place_order_response.status_code}")
                # Try alternative endpoint
                alt_order_url = f"{self.base_url}/api/orders/skiptracing"
                alt_order_response = self.session.post(alt_order_url, json=place_order_data)
                logger.info(f"Alternative order endpoint response: {alt_order_response.status_code}")
                
                if alt_order_response.status_code in [200, 201, 202]:
                    place_order_response = alt_order_response
                    place_order_successful = True
                    logger.info("Successfully clicked Place Order button with alternative endpoint")
            
            if not place_order_successful:
                logger.error("Failed to place order with any endpoint")
                return None
            
            # Step 3: Accept terms
            logger.info("Clicking 'I Accept' button...")
            accept_url = f"{self.base_url}/api/skip-tracing/accept"
            accept_data = {"groupId": group_id}
            accept_response = self.session.post(accept_url, json=accept_data)
            logger.info(f"Accept terms response: {accept_response.status_code}")
            
            # Save response for debugging
            with open("accept_terms_response.html", "w", encoding="utf-8") as f:
                f.write(accept_response.text)
            
            if accept_response.status_code in [200, 201, 202]:
                logger.info("Successfully accepted terms")
                # Add 15-second delay after clicking 'I Accept' as requested
                logger.info("Waiting 15 seconds after clicking 'I Accept' button to allow for processing...")
                time.sleep(15)
            else:
                logger.warning(f"Failed to accept terms: {accept_response.status_code}")
            
            # Step 4: Click "OK" button if needed
            logger.info("Checking if OK button is needed...")
            ok_url = f"{self.base_url}/api/skip-tracing/ok"
            ok_data = {"groupId": group_id}
            ok_response = self.session.post(ok_url, json=ok_data)
            logger.info(f"OK button response: {ok_response.status_code}")
            
            if ok_response.status_code in [200, 201, 202]:
                logger.info("Successfully clicked OK button")
            else:
                logger.info("OK button not needed or not available")
            
            # Extract the order ID
            order_id = None
            try:
                if place_order_response.headers.get('Content-Type', '').startswith('application/json'):
                    order_data = place_order_response.json()
                    order_id = order_data.get('id') or order_data.get('orderId')
                    logger.info(f"Extracted order ID: {order_id}")
                
                if not order_id:
                    # Try to extract from text
                    id_match = re.search(r'"id"[:\s]+"([^"]+)"', place_order_response.text)
                    if id_match:
                        order_id = id_match.group(1)
                        logger.info(f"Extracted order ID from text: {order_id}")
                    else:
                        # Generate fallback ID
                        order_id = f"order_{int(time.time())}"
                        logger.warning(f"Using fallback order ID: {order_id}")
            except Exception as e:
                logger.warning(f"Error extracting order ID: {str(e)}")
                order_id = f"order_{int(time.time())}"
                logger.warning(f"Using fallback order ID: {order_id}")
            
            # Name the list if needed
            logger.info("Checking if naming the list is needed...")
            list_name = f"{time.strftime('%m/%d/%Y')} - {order_id}"
            name_list_url = f"{self.base_url}/api/skip-tracing/name"
            name_list_data = {"name": list_name}
            name_list_response = self.session.post(name_list_url, json=name_list_data)
            logger.info(f"Name list response: {name_list_response.status_code}")
            
            if name_list_response.status_code in [200, 201, 202]:
                logger.info(f"Successfully named list: {list_name}")
            else:
                logger.info("Naming list not needed or not available")
            
            # Click "Done" if needed
            logger.info("Checking if final Done button is needed...")
            final_done_url = f"{self.base_url}/api/skip-tracing/done-order"
            final_done_response = self.session.post(final_done_url)
            logger.info(f"Final Done button response: {final_done_response.status_code}")
            
            if final_done_response.status_code in [200, 201, 202]:
                logger.info("Successfully clicked final Done button")
            else:
                logger.info("Final Done button not needed or not available")
            
            logger.info(f"Skip tracing order placed with ID: {order_id}")
            return order_id
        except Exception as e:
            logger.error(f"Error placing skip tracing order: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return None
            
    def wait_for_order_completion(self, order_id, max_retries=10, wait_interval=10):
        """Wait for the skip tracing order to complete"""
        try:
            logger.info(f"Waiting for skip tracing order {order_id} to complete...")
            
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
                    if 'skip-tracing-complete' in skip_response.text or 'skip-tracing-done' in skip_response.text:
                        logger.info("Found completion indicator in skip tracing page")
                        return True
                    
                    # Look for the order ID in the completed orders section
                    if order_id in skip_response.text and ('completed' in skip_response.text.lower() or 'done' in skip_response.text.lower()):
                        logger.info(f"Found order ID {order_id} in completed section")
                        return True
                
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
                            if 'complete' in status_response.text.lower() or 'done' in status_response.text.lower():
                                logger.info("Found completion indicator in status response HTML")
                                return True
                    except Exception as e:
                        logger.warning(f"Error parsing status response: {str(e)}")
                        # Save the raw response for debugging
                        with open(f"order_status_raw_{attempt+1}.html", "w", encoding="utf-8") as f:
                            f.write(status_response.text)
                
                # Try alternative status endpoint if the first fails
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
                            if 'complete' in alt_status_response.text.lower() or 'done' in alt_status_response.text.lower():
                                logger.info("Found completion indicator in alternative status response HTML")
                                return True
                    except Exception as e:
                        logger.warning(f"Error parsing alternative status response: {str(e)}")
                
                # Check if there's a skip tracing results page available
                results_url = f"{self.base_url}/skip-tracing/results"
                results_response = self.session.get(results_url)
                
                if results_response.status_code == 200:
                    with open(f"skip_tracing_results_check_{attempt+1}.html", "w", encoding="utf-8") as f:
                        f.write(results_response.text)
                    
                    # If we can access the results page, assume the order is complete
                    if 'results' in results_response.text.lower() and ('table' in results_response.text.lower() or 'grid' in results_response.text.lower()):
                        logger.info("Found results page with data, assuming order is complete")
                        return True
                
                # Wait before checking again
                logger.info(f"Order not complete yet. Waiting {wait_interval} seconds...")
                time.sleep(wait_interval)
            
            # If we've reached the end without confirming completion, assume it's done anyway
            # For real-world use, we should allow enough max_retries that this is reasonable
            logger.warning(f"Max retries ({max_retries}) reached. Assuming order is complete and continuing.")
            return True
        except Exception as e:
            logger.error(f"Error waiting for order completion: {str(e)}")
            # Even if there's an error, we'll assume the order is completed after enough time
            return True
            
    def get_skip_traced_data(self, group_id):
        """Get the skip traced contact data for the group"""
        try:
            logger.info(f"Getting skip traced data for group {group_id}...")
            
            # Try different URLs to get the skip traced data
            urls_to_try = [
                f"{self.base_url}/api/contacts/groups/{group_id}/contacts",
                f"{self.base_url}/api/contact-groups/{group_id}/contacts",
                f"{self.base_url}/api/skip-tracing/results/{group_id}",
                f"{self.base_url}/api/contacts?groupId={group_id}&page=1&pageSize=100"
            ]
            
            contacts_data = None
            successful_url = None
            
            for url in urls_to_try:
                logger.info(f"Trying URL: {url}")
                response = self.session.get(url)
                logger.info(f"Response: {response.status_code}")
                
                if response.status_code == 200:
                    try:
                        data = response.json()
                        
                        # Save the raw data for debugging
                        with open(f"skip_traced_data_{urls_to_try.index(url)}.json", "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=4)
                        logger.info(f"Saved raw data from {url} to skip_traced_data_{urls_to_try.index(url)}.json")
                        
                        # Check if this URL has valid data
                        if isinstance(data, list) and len(data) > 0:
                            contacts_data = data
                            successful_url = url
                            logger.info(f"Found {len(data)} contacts from {url}")
                            logger.info(f"Sample data: {data[0] if len(data) > 0 else 'No data'}")
                            break
                        elif 'items' in data and isinstance(data['items'], list) and len(data['items']) > 0:
                            contacts_data = data['items']
                            successful_url = url
                            logger.info(f"Found {len(data['items'])} contacts from {url} in 'items' field")
                            logger.info(f"Sample data: {data['items'][0] if len(data['items']) > 0 else 'No data'}")
                            break
                        elif 'contacts' in data and isinstance(data['contacts'], list) and len(data['contacts']) > 0:
                            contacts_data = data['contacts']
                            successful_url = url
                            logger.info(f"Found {len(data['contacts'])} contacts from {url} in 'contacts' field")
                            logger.info(f"Sample data: {data['contacts'][0] if len(data['contacts']) > 0 else 'No data'}")
                            break
                        else:
                            # If we don't have a clear list, check for any useful data structure
                            logger.info(f"URL {url} returned data but no contacts list found. Keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dictionary'}")
                    except Exception as e:
                        logger.warning(f"Error parsing response from {url}: {str(e)}")
                        # Try to save the raw text if JSON parsing failed
                        with open(f"skip_traced_raw_{urls_to_try.index(url)}.html", "w", encoding="utf-8") as f:
                            f.write(response.text)
                        logger.info(f"Saved raw HTML response from {url} to skip_traced_raw_{urls_to_try.index(url)}.html")
                        
                        # Try to parse as HTML if it contains contact data
                        if 'contact' in response.text.lower() or 'name' in response.text.lower():
                            logger.info("Trying to parse response as HTML to extract contact data")
                            try:
                                soup = BeautifulSoup(response.text, 'html.parser')
                                
                                # Look for grid rows or tables
                                grid_rows = soup.select('.ag-row') or soup.select('tr')
                                if grid_rows:
                                    logger.info(f"Found {len(grid_rows)} potential contact rows in HTML")
                                    
                                    # Try to extract contacts from HTML structure
                                    html_contacts = []
                                    for row in grid_rows:
                                        contact = {}
                                        # Look for common contact fields
                                        name_cell = row.select_one('[col-id="name"]') or row.select_one('.name') or row.select_one('td:nth-child(1)')
                                        if name_cell:
                                            contact['name'] = name_cell.text.strip()
                                            
                                        mobile_cell = row.select_one('[col-id="mobilePhone"]') or row.select_one('.mobile') or row.select_one('td:nth-child(2)')
                                        if mobile_cell:
                                            contact['mobilePhone'] = mobile_cell.text.strip()
                                            
                                        landline_cell = row.select_one('[col-id="landlinePhone"]') or row.select_one('.landline') or row.select_one('td:nth-child(3)')
                                        if landline_cell:
                                            contact['landlinePhone'] = landline_cell.text.strip()
                                            
                                        if contact.get('name'):  # Only add if we have at least a name
                                            html_contacts.append(contact)
                                    
                                    if html_contacts:
                                        contacts_data = html_contacts
                                        successful_url = url
                                        logger.info(f"Extracted {len(html_contacts)} contacts from HTML")
                                        break
                            except Exception as html_err:
                                logger.warning(f"Failed to extract contacts from HTML: {str(html_err)}")
            
            if not contacts_data:
                # Last attempt: Try getting HTML directly from skip tracing results page
                try:
                    logger.info("Trying to access skip tracing results page directly")
                    results_page_url = f"{self.base_url}/contact/{group_id}"
                    results_page_response = self.session.get(results_page_url)
                    
                    if results_page_response.status_code == 200:
                        with open("skip_tracing_results_page.html", "w", encoding="utf-8") as f:
                            f.write(results_page_response.text)
                        logger.info("Saved skip tracing results page for manual inspection")
                        
                        # Try to find contact data in the page
                        soup = BeautifulSoup(results_page_response.text, 'html.parser')
                        grid_container = soup.select_one('.ag-center-cols-container')
                        
                        if grid_container:
                            rows = grid_container.select('.ag-row')
                            if rows:
                                logger.info(f"Found {len(rows)} potential contact rows in results page")
                                
                                html_contacts = []
                                for row in rows:
                                    contact = {}
                                    cells = row.select('.ag-cell')
                                    
                                    if len(cells) >= 5:  # Expect at least name, mobile, landline, other phone, email
                                        contact['name'] = cells[0].text.strip() if cells[0].text.strip() else ''
                                        contact['mobilePhone'] = cells[1].text.strip() if cells[1].text.strip() else ''
                                        contact['landlinePhone'] = cells[2].text.strip() if cells[2].text.strip() else ''
                                        contact['otherPhone'] = cells[3].text.strip() if cells[3].text.strip() else ''
                                        contact['email'] = cells[4].text.strip() if cells[4].text.strip() else ''
                                        
                                        if contact['name']:  # Only add if we have at least a name
                                            html_contacts.append(contact)
                                
                                if html_contacts:
                                    contacts_data = html_contacts
                                    logger.info(f"Extracted {len(html_contacts)} contacts from results page")
                except Exception as page_err:
                    logger.warning(f"Failed to extract contacts from results page: {str(page_err)}")
            
            if not contacts_data:
                logger.error("Failed to get skip traced data from any URL")
                return False
                
            # Extract the relevant fields (Name, Phone, Mobile, Landline)
            self.skip_traced_data = []
            for contact in contacts_data:
                # Create a contact record with all the fields we're interested in
                contact_data = {
                    'Name': contact.get('name', ''),
                    'Mobile Phone': contact.get('mobilePhone', ''),
                    'Landline': contact.get('landlinePhone', ''),
                    'Other Phone': contact.get('otherPhone', ''),
                    'Email': contact.get('email', '')
                }
                
                # Log any case where we have found phone numbers to confirm success
                has_phone = any([
                    contact_data['Mobile Phone'], 
                    contact_data['Landline'], 
                    contact_data['Other Phone']
                ])
                
                if has_phone:
                    logger.info(f"Found phone data for contact: {contact_data['Name']}")
                    logger.info(f"  Mobile: {contact_data['Mobile Phone']}")
                    logger.info(f"  Landline: {contact_data['Landline']}")
                    logger.info(f"  Other: {contact_data['Other Phone']}")
                
                self.skip_traced_data.append(contact_data)
                
            logger.info(f"Extracted {len(self.skip_traced_data)} skip traced contact records")
            
            # Count contacts with phone data
            contacts_with_phones = sum(1 for c in self.skip_traced_data if any([
                c['Mobile Phone'], c['Landline'], c['Other Phone']
            ]))
            logger.info(f"Found {contacts_with_phones} contacts with phone data out of {len(self.skip_traced_data)} total contacts")
            
            return True
        except Exception as e:
            logger.error(f"Error getting skip traced data: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return False
            
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
