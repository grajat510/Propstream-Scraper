import os
import re
import time
import csv
import base64
import logging
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError, Error
import argparse

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

class PropStreamPlaywrightScraper:
    def __init__(self, username, password):
        self.username = username
        # Decode the password if it's base64 encoded
        try:
            self.password = base64.b64decode(password).decode('utf-8')
        except:
            self.password = password  # Use as-is if not base64 encoded
            
        self.base_url = "https://app.propstream.com"
        self.login_url = "https://login.propstream.com/"
        self.browser = None
        self.page = None
        self.extracted_data = []
        self.skip_trace_list_name = None
    
    async def setup_browser(self, headless=False, use_mock=False):
        """Initialize browser session"""
        logger.info("Setting up browser")
        
        # Check if the file exists
        file_path = "foreclosures_processed.csv"
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            logger.info("Creating a sample CSV file for testing")
            # Create a sample file
            with open(file_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Name', 'Address', 'City', 'State', 'Zip', 'Email'])
                writer.writerow(['John Doe', '123 Main St', 'Anytown', 'MI', '49503', 'john@example.com'])
                writer.writerow(['Jane Smith', '456 Oak Ave', 'Somewhere', 'MI', '49504', 'jane@example.com'])
            logger.info(f"Created sample file: {file_path}")
        else:
            logger.info(f"Found file: {file_path}")
            # Check file size and content
            file_size = os.path.getsize(file_path)
            logger.info(f"File size: {file_size} bytes")
            
            if file_size > 0:
                with open(file_path, 'r', newline='', encoding='utf-8', errors='ignore') as f:
                    sample = f.read(1000)
                    logger.info(f"File sample: {sample[:100]}...")
        
        if use_mock:
            logger.info("Mock mode enabled, skipping browser setup")
            return None
            
        playwright = await async_playwright().start()
        
        # Set slower navigation options
        slow_mo = 100  # Slow down by 100ms
        self.browser = await playwright.chromium.launch(
            headless=headless, 
            slow_mo=slow_mo,
            args=["--disable-web-security", "--disable-features=IsolateOrigins,site-per-process"]
        )
        
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            ignore_https_errors=True
        )
        
        # Set longer timeouts
        self.context.set_default_timeout(120000)  # 2 minutes timeout
        
        self.page = await self.context.new_page()
        
        # Enable request/response logging
        self.page.on("request", lambda request: logger.debug(f">> Request: {request.method} {request.url}"))
        self.page.on("response", lambda response: logger.debug(f"<< Response: {response.status} {response.url}"))
        
        # Add custom headers that mimic browser behavior
        await self.page.set_extra_http_headers({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Cache-Control": "max-age=0",
            "X-Requested-With": "XMLHttpRequest"
        })
        
        # Enable JavaScript console logging
        self.page.on("console", lambda msg: logger.debug(f"CONSOLE: {msg.text}"))
        
        return self.page
    
    async def login(self, use_mock=False):
        """Login to PropStream"""
        if use_mock:
            logger.info("Using mock login for testing purposes")
            return True
            
        logger.info("Logging in to PropStream...")
        try:
            await self.page.goto(self.login_url, wait_until="networkidle")
            
            # Fill username
            await self.page.fill('input[name="username"]', self.username)
            
            # Fill password
            await self.page.fill('input[name="password"]', self.password)
            
            # Click login button and wait for navigation to complete
            logger.info("Clicking login button and waiting for navigation")
            
            # Use promise_all to wait for multiple events
            async with self.page.expect_navigation(wait_until="networkidle", timeout=30000):
                await self.page.click('button[type="submit"]')
            
            logger.info("Login successful")
            
            # After login, check for and handle the PropStream updates popup
            try:
                # Take a screenshot to see what's on screen
                await self.page.screenshot(path="after_login_before_popup.png")
                
                # Wait for the PropStream updates popup to appear
                logger.info("Checking for PropStream updates popup...")
                
                # Look for the Close button in the updates popup
                close_button_selectors = [
                    'button:has-text("Close")',
                    '.close-button',
                    '.modal-close',
                    '.popup-close',
                    'button:below(div:has-text("PROPSTREAM Updates"))'
                ]
                
                for selector in close_button_selectors:
                    try:
                        if await self.page.query_selector(selector):
                            logger.info(f"Found Close button with selector: {selector}")
                            await self.page.click(selector, timeout=5000)
                            logger.info("Clicked Close button on updates popup")
                            break
                    except Exception as e:
                        logger.debug(f"Could not click Close button with selector {selector}: {str(e)}")
                
                # Wait a moment for the popup to disappear
                await asyncio.sleep(2)
                
                # Navigate to the main dashboard URL
                dashboard_url = "https://app.propstream.com/"
                logger.info(f"Navigating to main dashboard: {dashboard_url}")
                await self.page.goto(dashboard_url, wait_until="networkidle")
                
                # Take a screenshot after handling the popup
                await self.page.screenshot(path="after_popup_handling.png")
                
            except Exception as e:
                logger.warning(f"Error handling updates popup: {str(e)}")
                # Even if we can't handle the popup, try to continue with the process
            
            # Save cookies for potential future use
            cookies = await self.context.cookies()
            with open("propstream_cookies.json", "w") as f:
                import json
                json.dump(cookies, f)
            logger.info("Saved cookies for future sessions")
            
            return True
                
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            # Take a screenshot of the failed login for debugging
            await self.page.screenshot(path="login_error.png")
            return False
    
    async def import_file(self, file_path):
        """Import a file to PropStream and create a new group"""
        logger.info(f"Importing file: {file_path}")
        try:
            # Make sure we're on the main dashboard
            await self.page.goto(f"{self.base_url}", wait_until="networkidle")
            logger.info("Navigated to dashboard")
            
            # Take a screenshot of the dashboard for debugging
            await self.page.screenshot(path="dashboard.png")
            
            # Wait a moment for any popups to appear
            await asyncio.sleep(2)
            
            # Check for and close any popups that might be visible
            try:
                # Look for various close buttons in popups
                popup_close_selectors = [
                    'button:has-text("Close")',
                    '.close-button',
                    '.modal-close',
                    '.popup-close',
                    'span.close',
                    'button.btn-close'
                ]
                
                for selector in popup_close_selectors:
                    try:
                        # Check if the selector exists and is visible
                        close_button = await self.page.query_selector(selector)
                        if close_button:
                            is_visible = await close_button.is_visible()
                            if is_visible:
                                logger.info(f"Found popup close button with selector: {selector}")
                                await close_button.click()
                                logger.info("Clicked close button on popup")
                                # Wait a moment for the popup to close
                                await asyncio.sleep(1)
                                break
                    except Exception as e:
                        logger.debug(f"Could not interact with close button selector {selector}: {str(e)}")
            except Exception as e:
                logger.warning(f"Error handling popups: {str(e)}")
            
            # Try multiple selectors for the "Import List" button
            logger.info("Looking for 'Import List' button")
            import_button_selectors = [
                'div.src-components-Button-style__FABy8__content:text("Import List")',
                'button:has-text("Import List")',
                'span:text("Import List")',
                '[data-testid="import-list-button"]',
                '.import-list-btn',
                'div:text("Import List"):visible',
                'div.src-app-utils-Button-style__jfMOa__content:text("Import List")',
                'div[class*="Button-style"]:has-text("Import List")'
            ]
            
            # Take screenshot of the UI
            await self.page.screenshot(path="before_import_button_click.png")
            
            button_found = False
            for selector in import_button_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        is_visible = await element.is_visible()
                        if is_visible:
                            logger.info(f"Found 'Import List' button with selector: {selector}")
                            await element.click(timeout=10000)
                            button_found = True
                            logger.info(f"Clicked 'Import List' button with selector: {selector}")
                            break
                except Exception as e:
                    logger.warning(f"Could not click button with selector {selector}: {str(e)}")
            
            if not button_found:
                # Search for any button that might contain "Import" or "List"
                logger.info("Trying to find Import List button by examining all buttons")
                buttons = await self.page.query_selector_all('button, div[role="button"], [class*="button"], [class*="Button"]')
                
                for button in buttons:
                    try:
                        # Check if the button is visible
                        is_visible = await button.is_visible()
                        if not is_visible:
                            continue
                            
                        button_text = await button.inner_text()
                        logger.info(f"Found button with text: {button_text}")
                        
                        # Check if the text contains "import" or "list" (case insensitive)
                        if "import" in button_text.lower() or "list" in button_text.lower():
                            logger.info(f"Clicking button with text: {button_text}")
                            await button.click()
                            button_found = True
                            break
                    except Exception as e:
                        logger.debug(f"Error examining button: {str(e)}")
                
            if not button_found:
                # Take a screenshot to help debug the issue
                await self.page.screenshot(path="import_button_not_found.png")
                
                # Try clicking on the first navigation element that might lead to the import page
                try:
                    sidebar_buttons = await self.page.query_selector_all('a[href], div[role="link"], [class*="navigation"], [class*="sidebar"]')
                    for button in sidebar_buttons:
                        try:
                            is_visible = await button.is_visible()
                            if is_visible:
                                button_text = await button.inner_text()
                                logger.info(f"Trying sidebar element with text: {button_text}")
                                if "lead" in button_text.lower() or "import" in button_text.lower() or "contact" in button_text.lower():
                                    await button.click()
                                    logger.info(f"Clicked sidebar element: {button_text}")
                                    await asyncio.sleep(2)
                                    # Now try again to find the Import List button
                                    for selector in import_button_selectors:
                                        try:
                                            if await self.page.query_selector(selector):
                                                await self.page.click(selector, timeout=5000)
                                                logger.info(f"Found Import List button after navigation")
                                                button_found = True
                                                break
                                        except Exception:
                                            continue
                                    if button_found:
                                        break
                        except Exception:
                            continue
                except Exception as e:
                    logger.warning(f"Error trying sidebar navigation: {str(e)}")
            
            if not button_found:
                logger.error("Could not find or click 'Import List' button")
                await self.page.screenshot(path="import_button_not_found_final.png")
                
                # As a last resort, try to use the direct URL for importing
                try:
                    logger.info("Trying to navigate directly to import URL")
                    await self.page.goto(f"{self.base_url}/import", wait_until="networkidle")
                    # Check if we're on an import page
                    if "import" in self.page.url.lower():
                        logger.info("Successfully navigated to import page via direct URL")
                        button_found = True
                    else:
                        logger.warning("Direct URL navigation did not reach import page")
                except Exception as e:
                    logger.error(f"Error navigating to direct import URL: {str(e)}")
                    return None
            
            if not button_found:
                return None
            
            logger.info("Clicked 'Import List' button, waiting for file upload dialog")
            
            # Wait for the file upload dialog to appear
            await self.page.wait_for_selector('input[type="file"]', state="attached", timeout=20000)
            
            # Use the file input to upload the file
            logger.info(f"Uploading file: {file_path}")
            input_file = await self.page.query_selector('input[type="file"]')
            await input_file.set_input_files(file_path)
            
            # Wait for the file to upload and show in the UI
            try:
                await self.page.wait_for_selector(f'div:text("{os.path.basename(file_path)}")', timeout=30000)
                logger.info("File uploaded successfully")
            except TimeoutError:
                logger.warning("File name not visible in UI, but proceeding")
            
            # Take screenshot after file upload
            await self.page.screenshot(path="file_uploaded.png")
            
            # Select "Create New" radio button
            try:
                await self.page.click('input[value="new"]', timeout=10000)
                logger.info("Selected 'Create New' option")
            except Exception as e:
                logger.warning(f"Could not click 'Create New' radio button: {str(e)}")
                # Try alternative selectors
                selectors = [
                    'label:has-text("Create New")',
                    'div:has-text("Create New") input',
                    '[value="new"]'
                ]
                for selector in selectors:
                    try:
                        await self.page.click(selector, timeout=5000)
                        logger.info(f"Selected 'Create New' using selector: {selector}")
                        break
                    except Exception:
                        continue
            
            # Generate a group name with timestamp to ensure uniqueness
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            group_name = f"Foreclosures_scraping_Test_{timestamp}"
            
            # Wait for the "Add To Group" dialog box
            logger.info("Waiting for 'Add To Group' dialog")
            try:
                await self.page.wait_for_selector('input[placeholder="New Group"]', timeout=15000)
            except TimeoutError:
                logger.warning("New Group input not found with expected selector")
                # Try alternative selectors
                selectors = [
                    'input[placeholder*="Group"]',
                    'input[placeholder="Add a name"]',
                    'input.new-group-input'
                ]
                for selector in selectors:
                    try:
                        await self.page.wait_for_selector(selector, timeout=5000)
                        logger.info(f"Found group name input with selector: {selector}")
                        # Update the selector for the next step
                        new_group_selector = selector
                        break
                    except TimeoutError:
                        continue
                else:
                    # Take screenshot if we can't find the input
                    await self.page.screenshot(path="group_input_not_found.png")
                    logger.error("Could not find group name input with any selector")
                    return None
            
            # Enter the new group name
            logger.info(f"Setting group name: {group_name}")
            try:
                await self.page.fill('input[placeholder="New Group"]', group_name)
            except Exception:
                # Use the alternative selector if we found one
                if 'new_group_selector' in locals():
                    await self.page.fill(new_group_selector, group_name)
                else:
                    # Try to find any input field that might be for the group name
                    inputs = await self.page.query_selector_all('input:visible')
                    for input_elem in inputs:
                        try:
                            placeholder = await input_elem.get_attribute('placeholder')
                            if placeholder and ('group' in placeholder.lower() or 'name' in placeholder.lower()):
                                await input_elem.fill(group_name)
                                logger.info(f"Filled group name in input with placeholder: {placeholder}")
                                break
                        except Exception:
                            continue
            
            # Click the "Save" button
            logger.info("Clicking 'Save' button")
            save_selectors = [
                'button[type="submit"]:has-text("Save")',
                'button:has-text("Save")',
                '.save-button',
                '[data-testid="save-button"]'
            ]
            
            save_clicked = False
            for selector in save_selectors:
                try:
                    if await self.page.query_selector(selector):
                        await self.page.click(selector, timeout=5000)
                        save_clicked = True
                        logger.info(f"Clicked Save with selector: {selector}")
                        break
                except Exception:
                    continue
            
            if not save_clicked:
                # Try to find any button that might be the save button
                buttons = await self.page.query_selector_all('button:visible')
                for button in buttons:
                    try:
                        button_text = await button.inner_text()
                        if "save" in button_text.lower() or "done" in button_text.lower() or "ok" in button_text.lower():
                            await button.click()
                            save_clicked = True
                            logger.info(f"Clicked button with text: {button_text}")
                            break
                    except Exception:
                        continue
            
            if not save_clicked:
                await self.page.screenshot(path="save_button_not_found.png")
                logger.warning("Could not find or click 'Save' button")
            
            # Wait for the import to complete - look for success indicators
            try:
                await self.page.wait_for_selector('div:text("Import completed")', timeout=120000)
                logger.info("Import completed successfully")
            except TimeoutError:
                logger.warning("Import completion message not found, but proceeding")
                
                # Check if we're back on the main page
                try:
                    main_page_indicators = [
                        'div.src-components-Button-style__FABy8__content:text("Import List")',
                        'button:has-text("Import List")',
                        'div.dashboard-container',
                        'div.main-content'
                    ]
                    
                    for indicator in main_page_indicators:
                        try:
                            if await self.page.wait_for_selector(indicator, timeout=5000):
                                logger.info(f"Returned to main page, detected with: {indicator}")
                                break
                        except TimeoutError:
                            continue
                except Exception:
                    logger.warning("Not on main page, but continuing")
            
            # Take a final screenshot
            await self.page.screenshot(path="after_import.png")
            
            # Save the group name for later use
            self.group_name = group_name
            logger.info(f"Group created with name: {group_name}")
            
            return group_name
            
        except Exception as e:
            logger.error(f"Error importing file: {str(e)}")
            await self.page.screenshot(path="import_error.png")
            return None
    
    async def navigate_to_skip_tracing(self):
        """Navigate to the skip tracing page"""
        logger.info("Navigating to skip tracing")
        try:
            # Click on the Skip Tracing icon in the sidebar
            await self.page.click('a:has(svg.icon-iconContactAppends):has-text("Skip Tracing")')
            
            # Wait for the skip tracing page to load
            await self.page.wait_for_selector('div.src-components-Button-style__FABy8__content:text("Select Contacts")', timeout=30000)
            logger.info("Successfully navigated to skip tracing page")
            return True
        except Exception as e:
            logger.error(f"Error navigating to skip tracing: {str(e)}")
            await self.page.screenshot(path="skip_tracing_nav_error.png")
            return False
    
    async def select_contacts_for_skip_tracing(self):
        """Select contacts for skip tracing"""
        logger.info("Selecting contacts for skip tracing")
        try:
            # Click on "Select Contacts" button
            await self.page.click('div.src-components-Button-style__FABy8__content:text("Select Contacts")')
            
            # Wait for the dropdown to appear
            await self.page.wait_for_selector('select.src-components-base-Dropdown-style__X5sdo__control')
            
            # Find the option that contains our group name
            dropdown = await self.page.query_selector('select.src-components-base-Dropdown-style__X5sdo__control')
            
            # Click to open the dropdown
            await dropdown.click()
            
            # Find the option that matches our group name (or partial match)
            options = await self.page.query_selector_all('option')
            target_option = None
            
            for option in options:
                option_text = await option.inner_text()
                # Check if our group name is contained in the option text
                if self.group_name in option_text:
                    target_option = option
                    option_value = await option.get_attribute('value')
                    logger.info(f"Found our group in dropdown: {option_text} with value {option_value}")
                    break
            
            # If we found our option, select it
            if target_option:
                await target_option.click()
                logger.info(f"Selected group from dropdown")
            else:
                # No exact match, try to find the closest match
                for option in options:
                    option_text = await option.inner_text()
                    parts = self.group_name.split('_')
                    if parts[0] in option_text and parts[1] in option_text:
                        target_option = option
                        option_value = await option.get_attribute('value')
                        logger.info(f"Found similar group in dropdown: {option_text} with value {option_value}")
                        break
                
                if target_option:
                    await target_option.click()
                    logger.info(f"Selected similar group from dropdown")
                else:
                    logger.error("Could not find our group in the dropdown")
                    return False
            
            # Wait for contacts to load
            await asyncio.sleep(2)
            
            # Check if there's a "Check All" checkbox or similar
            try:
                # Look for checkbox in the header
                header_checkbox = await self.page.query_selector('div.ag-header-cell div.ag-checkbox-input')
                if header_checkbox:
                    await header_checkbox.click()
                    logger.info("Clicked header checkbox to select all contacts")
                else:
                    # If no header checkbox, try to click individual checkboxes
                    checkboxes = await self.page.query_selector_all('div.ag-checkbox-input')
                    if checkboxes:
                        for checkbox in checkboxes:
                            await checkbox.click()
                        logger.info(f"Clicked {len(checkboxes)} individual checkboxes")
                    else:
                        logger.warning("No checkboxes found, but continuing")
            except Exception as e:
                logger.warning(f"Error selecting checkboxes: {str(e)}")
            
            # Click "Add Selected Contacts" button
            await self.page.click('span.src-components-base-Button-style__FBPrq__text:text("Add Selected Contacts")')
            
            # Wait for the contacts to be added
            await asyncio.sleep(2)
            
            # Click "Done" button
            await self.page.click('span.src-components-base-Button-style__FBPrq__text:text("Done")')
            
            logger.info("Successfully selected contacts for skip tracing")
            return True
        except Exception as e:
            logger.error(f"Error selecting contacts for skip tracing: {str(e)}")
            await self.page.screenshot(path="select_contacts_error.png")
            return False
    
    async def place_skip_tracing_order(self):
        """Place a skip tracing order"""
        logger.info("Placing skip tracing order")
        try:
            # Click "Next" button
            await self.page.click('div.src-components-Button-style__FABy8__content:text("Next")')
            logger.info("Clicked 'Next' button")
            
            # Wait for page to load
            await asyncio.sleep(2)
            
            # Click "Place Order" button
            await self.page.click('div.src-components-Button-style__FABy8__content:text("Place Order")')
            logger.info("Clicked 'Place Order' button")
            
            # Wait for the "I Accept" button to appear
            await self.page.wait_for_selector('span.src-components-base-Button-style__FBPrq__text:text("I Accept")')
            
            # Click "I Accept" button
            await self.page.click('span.src-components-base-Button-style__FBPrq__text:text("I Accept")')
            logger.info("Clicked 'I Accept' button")
            
            # Wait for the "OK" button to appear
            await self.page.wait_for_selector('div.src-components-Button-style__FABy8__content:text("Ok")')
            
            # Click "OK" button
            await self.page.click('div.src-components-Button-style__FABy8__content:text("Ok")')
            logger.info("Clicked 'OK' button")
            
            # Wait for the "Name Your List" field to appear
            await self.page.wait_for_selector('input.src-app-Contacts-AppendJobEditor-style__BidIc__input')
            
            # Get the auto-generated list name
            input_element = await self.page.query_selector('input.src-app-Contacts-AppendJobEditor-style__BidIc__input')
            list_name = await input_element.get_attribute('value')
            self.skip_trace_list_name = list_name
            logger.info(f"Skip trace list name: {list_name}")
            
            # Save the list name to a file for reference
            with open("skip_trace_list_name.txt", "w", encoding="utf-8") as f:
                f.write(list_name)
            
            # Click "Done" button to confirm the list name
            await self.page.click('div.src-components-Button-style__FABy8__content:text("Done")')
            logger.info("Clicked 'Done' button to confirm list name")
            
            # Wait for the order to be placed
            await asyncio.sleep(15)
            
            logger.info("Skip tracing order placed successfully")
            return list_name
            
        except Exception as e:
            logger.error(f"Error placing skip tracing order: {str(e)}")
            await self.page.screenshot(path="place_order_error.png")
            return None
    
    async def wait_for_order_completion(self, max_retries=12, wait_interval=30):
        """Wait for the skip tracing order to complete"""
        logger.info("Waiting for skip tracing order to complete...")
        
        for attempt in range(max_retries):
            logger.info(f"Check attempt {attempt+1}/{max_retries}")
            
            try:
                # Navigate to contacts page
                await self.page.goto(f"{self.base_url}/contact", wait_until="networkidle")
                
                # Look for completion indicators
                skip_trace_section = await self.page.query_selector('div.src-app-components-ToggleList-style__cNA8V__name:has-text("Skip Tracing")')
                
                if skip_trace_section:
                    logger.info("Found Skip Tracing section in sidebar")
                    
                    # Wait for the job to appear in the list
                    logger.info(f"Looking for job with name: {self.skip_trace_list_name}")
                    list_name_elements = await self.page.query_selector_all('div.src-app-components-ToggleList-style__tt0fX__labelName')
                    
                    # Check each job name for a match
                    for element in list_name_elements:
                        job_name = await element.inner_text()
                        logger.info(f"Found job: {job_name}")
                        
                        if job_name == self.skip_trace_list_name:
                            logger.info(f"Found our skip tracing job: {job_name}")
                            
                            # Check if this job has completed by looking at neighboring elements
                            parent = await element.query_selector('xpath=..')
                            if parent:
                                # Try to see if there's a quantity indicator
                                quantity_element = await parent.query_selector('div.src-app-components-ToggleList-style__orTGe__labelQuantity')
                                if quantity_element:
                                    quantity_text = await quantity_element.inner_text()
                                    logger.info(f"Job has quantity indicator: {quantity_text}")
                                    
                                    # If we see a number in parentheses, that likely means the job has contacts
                                    if '(' in quantity_text and ')' in quantity_text:
                                        logger.info("Order appears to be complete based on contact count")
                                        return True
                            
                            # Even if we can't confirm completion, try clicking on the job
                            await element.click()
                            logger.info(f"Clicked on job: {job_name}")
                            
                            # Wait for the contact data to load
                            await asyncio.sleep(5)
                            
                            # Look for indicators that data has loaded
                            grid_loaded = await self.page.query_selector('div.ag-center-cols-container')
                            if grid_loaded:
                                logger.info("Contact grid is loaded, assuming order is complete")
                                return True
                    
                    logger.info(f"Job not found or not complete yet. Waiting {wait_interval} seconds before next check...")
                else:
                    logger.warning("Skip Tracing section not found in sidebar")
            
            except Exception as e:
                logger.error(f"Error checking order status: {str(e)}")
            
            # Wait before next check
            await asyncio.sleep(wait_interval)
        
        logger.warning(f"Max retries ({max_retries}) reached. Assuming order is complete and continuing.")
        return True
    
    async def extract_skip_traced_data(self):
        """Extract the skip traced contact data"""
        logger.info("Extracting skip traced data")
        
        try:
            # Make sure we're on the contacts page showing our skip traced list
            if self.skip_trace_list_name:
                # Navigate to contacts page
                await self.page.goto(f"{self.base_url}/contact", wait_until="networkidle")
                
                # Find and click on our skip trace job in the left sidebar
                list_name_elements = await self.page.query_selector_all('div.src-app-components-ToggleList-style__tt0fX__labelName')
                job_clicked = False
                
                for element in list_name_elements:
                    job_name = await element.inner_text()
                    if job_name == self.skip_trace_list_name:
                        await element.click()
                        job_clicked = True
                        logger.info(f"Clicked on job: {job_name}")
                        break
                
                if not job_clicked:
                    logger.warning(f"Could not find job with name: {self.skip_trace_list_name}")
                    return False
                
                # Wait for the grid to load
                await asyncio.sleep(5)
            
            # Extract data from the contacts grid
            logger.info("Extracting contact data from grid")
            
            # Get all rows in the grid
            rows = await self.page.query_selector_all('div.ag-row')
            logger.info(f"Found {len(rows)} contact rows")
            
            extracted_data = []
            
            for row_index, row in enumerate(rows):
                logger.info(f"Processing row {row_index+1}")
                
                # Extract name
                name_cell = await row.query_selector('[col-id="name"]')
                name = await name_cell.inner_text() if name_cell else f"Contact {row_index+1}"
                
                # Extract mobile phone
                mobile_cell = await row.query_selector('[id^="cell-mobilePhone-"]')
                mobile_phone = await mobile_cell.inner_text() if mobile_cell else ""
                
                # Extract landline phone
                landline_cell = await row.query_selector('[id^="cell-landlinePhone-"]')
                landline_phone = await landline_cell.inner_text() if landline_cell else ""
                
                # Extract other phone (based on selector provided)
                other_phone_cell = await row.query_selector(':nth-child(4)')
                other_phone = await other_phone_cell.inner_text() if other_phone_cell else ""
                
                # Extract email
                email_cell = await row.query_selector(':nth-child(5)')
                email = await email_cell.inner_text() if email_cell else ""
                
                # Store the extracted data
                contact_data = {
                    'Name': name,
                    'Mobile Phone': mobile_phone,
                    'Landline': landline_phone,
                    'Phone': other_phone,
                    'Email': email
                }
                
                extracted_data.append(contact_data)
                logger.info(f"Extracted data for contact: {name}")
            
            self.extracted_data = extracted_data
            logger.info(f"Extracted data for {len(extracted_data)} contacts")
            
            return len(extracted_data) > 0
            
        except Exception as e:
            logger.error(f"Error extracting skip traced data: {str(e)}")
            await self.page.screenshot(path="extract_data_error.png")
            return False
    
    async def save_data_to_csv(self, output_file=None):
        """Save extracted data to CSV file"""
        if not self.extracted_data:
            logger.warning("No data to save")
            return None
            
        if not output_file:
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            group_prefix = self.group_name.split('_')[0] if hasattr(self, 'group_name') else "PropStream"
            output_file = f"{group_prefix}_skip_traced_{timestamp}.csv"
        
        try:
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Name', 'Mobile Phone', 'Landline', 'Phone', 'Email']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for contact in self.extracted_data:
                    writer.writerow(contact)
            
            logger.info(f"Saved {len(self.extracted_data)} contacts to {output_file}")
            
            # Create a backup with more detailed filename
            contacts_with_phones = sum(1 for c in self.extracted_data if any([
                c.get('Mobile Phone'), c.get('Landline'), c.get('Phone')
            ]))
            
            backup_file = f"skip_traced_{group_prefix}_{contacts_with_phones}_phones_{len(self.extracted_data)}_total_{timestamp}.csv"
            
            with open(backup_file, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Name', 'Mobile Phone', 'Landline', 'Phone', 'Email']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for contact in self.extracted_data:
                    writer.writerow(contact)
            
            logger.info(f"Created backup file: {backup_file}")
            
            return output_file
        except Exception as e:
            logger.error(f"Error saving data to CSV: {str(e)}")
            return None
    
    async def close(self):
        """Close browser and clean up"""
        if self.browser:
            await self.browser.close()
            logger.info("Browser closed")
        else:
            logger.info("No browser instance to close")
    
    async def run(self, file_path, output_file=None, headless=False, use_mock=False):
        """Run the full process"""
        try:
            # Initialize browser only if not in mock mode
            if not use_mock:
                await self.setup_browser(headless=headless, use_mock=use_mock)
                
                # Login
                if not await self.login(use_mock=use_mock):
                    logger.error("Login failed, aborting")
                    return False
            
            if use_mock:
                logger.info("Using mock workflow for testing purposes")
                # Create a mock group and skip trace job
                self.group_name = f"Test_Group_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                self.skip_trace_list_name = f"Skip_Trace_{datetime.now().strftime('%m/%d/%Y - %H%M%S')}"
                
                # Create mock data
                self.extracted_data = [
                    {'Name': 'John Doe', 'Mobile Phone': '(555) 123-4567', 'Landline': '(555) 765-4321', 'Phone': '', 'Email': 'john@example.com'},
                    {'Name': 'Jane Smith', 'Mobile Phone': '(555) 987-6543', 'Landline': '', 'Phone': '(555) 567-8901', 'Email': 'jane@example.com'},
                    {'Name': 'Bob Johnson', 'Mobile Phone': '(555) 234-5678', 'Landline': '(555) 876-5432', 'Phone': '', 'Email': 'bob@example.com'}
                ]
                
                # Save mock data to CSV
                csv_file = await self.save_data_to_csv(output_file)
                if not csv_file:
                    logger.error("Saving mock data to CSV failed")
                    return False
                
                logger.info(f"Mock process completed successfully. Mock data saved to {csv_file}")
                return True
            else:
                # Import file
                group_name = await self.import_file(file_path)
                if not group_name:
                    logger.error("File import failed, aborting")
                    return False
                    
                # Navigate to skip tracing
                if not await self.navigate_to_skip_tracing():
                    logger.error("Navigation to skip tracing failed, aborting")
                    return False
                    
                # Select contacts for skip tracing
                if not await self.select_contacts_for_skip_tracing():
                    logger.error("Contact selection failed, aborting")
                    return False
                    
                # Place skip tracing order
                list_name = await self.place_skip_tracing_order()
                if not list_name:
                    logger.error("Placing skip tracing order failed, aborting")
                    return False
                    
                # Wait for order to complete
                if not await self.wait_for_order_completion():
                    logger.warning("Order completion timeout, but continuing")
                    
                # Extract skip traced data
                if not await self.extract_skip_traced_data():
                    logger.error("Data extraction failed, aborting")
                    return False
                    
                # Save data to CSV
                csv_file = await self.save_data_to_csv(output_file)
                if not csv_file:
                    logger.error("Saving data to CSV failed")
                    return False
                    
                logger.info(f"Process completed successfully. Data saved to {csv_file}")
                return True
            
        except Exception as e:
            logger.error(f"Error during process: {str(e)}")
            if self.page and not use_mock:
                await self.page.screenshot(path="error.png")
            return False
            
        finally:
            if not use_mock:
                await self.close()

# Example usage
async def main():
    parser = argparse.ArgumentParser(description='PropStream Playwright Scraper')
    parser.add_argument('--mock', action='store_true', help='Use mock workflow for testing')
    parser.add_argument('--headless', action='store_true', help='Run in headless mode')
    parser.add_argument('--file', type=str, default="foreclosures_processed.csv", help='CSV file to upload')
    args = parser.parse_args()
    
    # Your PropStream credentials
    username = "mikerossgrandrapidsrealty@gmail.com"
    password = "MTEyMSRTdW4="  # Base64 encoded password
    
    # Create the scraper
    scraper = PropStreamPlaywrightScraper(username, password)
    
    # Run the scraper with configuration options
    await scraper.run(
        file_path=args.file, 
        headless=args.headless,
        use_mock=args.mock
    )

if __name__ == "__main__":
    asyncio.run(main()) 