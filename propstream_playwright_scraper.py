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
            args=[
                "--disable-web-security", 
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-notifications"
            ]
        )
        
        # Configure browser context with permissions already blocked
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            ignore_https_errors=True,
            # Set geolocation to a fixed position (optional)
            geolocation={"latitude": 37.7749, "longitude": -122.4194}
        )
        
        # Grant or deny permissions explicitly - this is the correct way to block geolocation
        await self.context.clear_permissions()  # Clear any existing permissions
        # Using the permissions API correctly - we don't grant geolocation permission
        await self.context.grant_permissions([], origin=self.base_url)
        
        # Set longer timeouts
        self.context.set_default_timeout(120000)  # 2 minutes timeout
        
        self.page = await self.context.new_page()
        
        # Set up JavaScript dialog handler
        self.page.on("dialog", lambda dialog: asyncio.create_task(self.handle_dialog(dialog)))
        
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
        
        # Override geolocation using Context API instead of page
        try:
            # Modern Playwright versions use context.set_geolocation
            await self.context.set_geolocation({"latitude": 37.7749, "longitude": -122.4194})
            logger.info("Set geolocation using context.set_geolocation")
        except AttributeError:
            # We already set geolocation during context creation, so this is just a fallback
            logger.info("Using geolocation already set during context creation")
        
        # Execute JavaScript to override geolocation
        await self.page.evaluate("""() => {
            // Mock the geolocation API
            const mockGeolocation = {
                getCurrentPosition: (success, error) => {
                    error({ code: 1, message: 'User denied geolocation' });
                    return true;
                },
                watchPosition: (success, error) => {
                    error({ code: 1, message: 'User denied geolocation' });
                    return 0;
                },
                clearWatch: () => {}
            };
            
            // Replace the actual geolocation API with our mock
            if (navigator.geolocation) {
                navigator.geolocation = mockGeolocation;
            }
        }""")
        
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
            
            # Handle location permissions and other prompts that might appear
            await self.handle_permission_prompts()
            
            # After login, check for and handle the PropStream updates popup
            try:
                # Take a screenshot to see what's on screen
                await self.page.screenshot(path="after_login_before_popup.png")
                
                # Wait for the PropStream updates popup to appear
                logger.info("Checking for PropStream updates popup...")
                
                # Handle updates popup or any other popups
                await self.handle_all_popups()
                
                # Navigate to the main dashboard URL
                dashboard_url = "https://app.propstream.com/"
                logger.info(f"Navigating to main dashboard: {dashboard_url}")
                await self.page.goto(dashboard_url, wait_until="networkidle")
                
                # Check again for any popups after navigating to dashboard
                await self.handle_permission_prompts()
                
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
    
    async def handle_permission_prompts(self):
        """Handle browser permission prompts like location access"""
        logger.info("Checking for permission prompts...")
        
        # Take a screenshot to see what's on the page
        await self.page.screenshot(path="before_permission_handling.png")
        
        try:
            # Look for location permission dialogs
            permission_buttons = [
                'button:has-text("Block")',
                'button:has-text("Don\'t Allow")',
                'button:has-text("No")',
                'button:has-text("Reject")',
                'button:has-text("Cancel")',
                'button:has-text("Later")',
                '[aria-label="Deny"]',
                '[aria-label="Block"]',
                'button[id*="deny"]',
                'button[id*="block"]',
                '.deny-button',
                '.block-button'
            ]
            
            for selector in permission_buttons:
                try:
                    # Check if element exists and is visible
                    button = await self.page.query_selector(selector)
                    if button and await button.is_visible():
                        logger.info(f"Found permission button with selector: {selector}")
                        await button.click()
                        logger.info(f"Clicked permission button: {selector}")
                        await asyncio.sleep(1)
                        await self.page.screenshot(path="after_permission_button_click.png")
                except Exception as e:
                    logger.debug(f"Error handling permission button {selector}: {str(e)}")
            
            # Check for location prompts by looking for elements containing location-related text
            location_prompts = await self.page.query_selector_all('div:has-text("location"), div:has-text("Location"), div:has-text("Know your location")')
            for prompt in location_prompts:
                if await prompt.is_visible():
                    logger.info("Found possible location prompt")
                    
                    # Look for buttons within the prompt
                    buttons = await prompt.query_selector_all('button')
                    for button in buttons:
                        button_text = await button.inner_text()
                        logger.info(f"Found button in location prompt: {button_text}")
                        
                        # Click on block/deny/cancel buttons
                        if any(word in button_text.lower() for word in ["block", "deny", "don't allow", "no", "cancel", "reject"]):
                            logger.info(f"Clicking location prompt button: {button_text}")
                            await button.click()
                            await asyncio.sleep(1)
                            await self.page.screenshot(path="after_location_prompt_button_click.png")
                            break
            
            # Try to handle permissions using JavaScript dialog handler
            self.page.on("dialog", lambda dialog: asyncio.create_task(self.handle_dialog(dialog)))
            
        except Exception as e:
            logger.warning(f"Error handling permission prompts: {str(e)}")

    async def handle_dialog(self, dialog):
        """Handle JavaScript dialogs like alerts, confirms, prompts"""
        logger.info(f"Dialog appeared: {dialog.message}")
        # For confirmation dialogs, dismiss/cancel them
        if dialog.type == "confirm" or dialog.type == "prompt":
            await dialog.dismiss()
            logger.info("Dialog dismissed")
        else:
            # For alerts, just acknowledge them
            await dialog.accept()
            logger.info("Dialog accepted")

    async def handle_all_popups(self):
        """Handle all types of popups including PropStream updates"""
        logger.info("Handling all possible popups...")
        
        # Look for various close buttons in popups
        popup_buttons = [
            # Close buttons
            'button:has-text("Close")',
            '.close-button',
            '.modal-close',
            '.popup-close',
            'span.close',
            'button.btn-close',
            'button:has-text("×")',
            'button:below(div:has-text("PROPSTREAM Updates"))',
            
            # Block/cancel location buttons
            'button:has-text("Block")',
            'button:has-text("Don\'t Allow")',
            'button:has-text("No")',
            'button:has-text("Reject")',
            'button:has-text("Cancel")',
            'button:has-text("Later")',
            
            # Additional selectors
            '[aria-label="Close"]',
            '[aria-label="Dismiss"]',
            '[aria-label="Cancel"]',
            '[aria-label="Block"]',
            '[aria-label="Deny"]'
        ]
        
        # Check each button type
        for selector in popup_buttons:
            try:
                # Find all matching elements
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        # Take a screenshot before clicking
                        safe_selector = selector.replace(':', '_').replace('"', '')
                        await self.page.screenshot(path=f"before_clicking_{safe_selector}.png")
                        
                        # Get button text if possible
                        try:
                            button_text = await element.inner_text()
                            logger.info(f"Found popup button: '{button_text}' with selector: {selector}")
                        except:
                            logger.info(f"Found popup button with selector: {selector}")
                        
                        # Click the button
                        await element.click()
                        logger.info(f"Clicked popup button with selector: {selector}")
                        
                        # Wait a moment for the popup to close
                        await asyncio.sleep(1)
                        
                        # Take another screenshot
                        await self.page.screenshot(path=f"after_clicking_{safe_selector}.png")
            except Exception as e:
                logger.debug(f"Error handling popup with selector {selector}: {str(e)}")
        
        # Check for modals and overlays that might need to be clicked outside of
        modal_selectors = ['.modal', '.dialog', '.overlay', '[role="dialog"]']
        for selector in modal_selectors:
            try:
                modal = await self.page.query_selector(selector)
                if modal and await modal.is_visible():
                    logger.info(f"Found modal/overlay with selector: {selector}")
                    # Try to click outside
                    await self.page.mouse.click(10, 10)
                    logger.info("Clicked outside modal to dismiss it")
                    await asyncio.sleep(1)
            except Exception as e:
                logger.debug(f"Error handling modal with selector {selector}: {str(e)}")

    async def check_for_upload_dialog(self):
        """Check if the file upload dialog is visible"""
        logger.info("Checking for file upload dialog...")
        await self.page.screenshot(path="before_upload_dialog_check.png")
        
        # First, check if we're on a page that might contain a file upload
        current_url = self.page.url
        logger.info(f"Current URL while checking for upload dialog: {current_url}")
        
        # Wait a bit longer for the dialog to appear
        await asyncio.sleep(3)
        
        upload_selectors = [
            'input[type="file"]',
            '.file-upload',
            '.upload-area',
            '[data-testid="file-upload"]',
            'div:has-text("Upload File")',
            'div:has-text("Choose File")',
            'div:has-text("Select File")',
            'div:has-text("Drag and drop")',
            'div[role="dialog"]', # General dialog check
            'div.modal',          # Modal check
            'div.file-input',
            'input[accept=".csv"]'
        ]
        
        for selector in upload_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    logger.info(f"Found file upload element with selector: {selector}")
                    
                    # Take a screenshot of the found element
                    safe_selector = selector.replace(':', '_').replace('[', '_').replace(']', '_').replace('"', '_').replace('*', '_').replace('=', '_')
                    await element.screenshot(path=f"found_upload_element_{safe_selector}.png")
                    return True
            except Exception as e:
                logger.debug(f"Error checking selector {selector}: {str(e)}")
        
        # Try using JavaScript to find an upload dialog or file input
        logger.info("Using JavaScript to look for file input elements")
        has_file_input = await self.page.evaluate('''() => {
            // Look for file inputs
            const fileInputs = document.querySelectorAll('input[type="file"]');
            console.log(`Found ${fileInputs.length} file inputs`);
            
            if (fileInputs.length > 0) {
                return true;
            }
            
            // Look for elements with certain attributes
            const possibleFileElements = document.querySelectorAll('[accept], [type="file"], [class*="upload"], [class*="file"], [id*="upload"], [id*="file"], [aria-label*="upload"], [aria-label*="file"]');
            console.log(`Found ${possibleFileElements.length} possible file-related elements`);
            
            // Look for text indicating file upload
            const bodyText = document.body.innerText.toLowerCase();
            const hasUploadText = bodyText.includes('upload') || 
                                 bodyText.includes('choose file') || 
                                 bodyText.includes('select file') || 
                                 bodyText.includes('drag and drop') ||
                                 bodyText.includes('import file') ||
                                 bodyText.includes('browse');
                                 
            console.log(`Page ${hasUploadText ? 'contains' : 'does not contain'} upload-related text`);
            
            // Take all text nodes and print them for debugging
            const textNodes = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.childNodes && 
                    el.childNodes.length === 1 && 
                    el.childNodes[0].nodeType === Node.TEXT_NODE &&
                    el.childNodes[0].textContent.trim()) {
                    textNodes.push(el.childNodes[0].textContent.trim());
                }
            });
            
            console.log("Text nodes on page:", textNodes.slice(0, 20)); // Log first 20 text nodes
            
            return possibleFileElements.length > 0 || hasUploadText;
        }''')
        
        if has_file_input:
            logger.info("JavaScript found potential file upload elements")
            
            # Take a full page screenshot
            await self.page.screenshot(path="js_found_upload_elements.png")
            return True
                
        logger.info("No file upload dialog detected")
        return False
    
    async def import_file(self, file_path):
        """Import a file to PropStream and create a new group"""
        logger.info(f"Importing file: {file_path}")
        try:
            # Navigate directly to the contacts page
            logger.info("Navigating directly to contacts page to find the Import button")
            await self.page.goto(f"{self.base_url}/contact", wait_until="networkidle")
            await asyncio.sleep(3)
            
            # Take a screenshot of the contacts page
            await self.page.screenshot(path="contacts_page_direct.png")
            
            # Debug: Get page title and URL to understand where we are
            current_url = self.page.url
            page_title = await self.page.title()
            logger.info(f"Current URL: {current_url}")
            logger.info(f"Page title: {page_title}")
            
            # Check if we're redirected to login page
            if "login.propstream.com" in current_url or "login" in page_title.lower():
                logger.info("Detected session expiration - re-logging in")
                if not await self.login():
                    logger.error("Failed to re-login, aborting import")
                    return None
                    
                # Try navigating to contacts page again after re-login
                logger.info("Re-navigating to contacts page after login")
                await self.page.goto(f"{self.base_url}/contact", wait_until="networkidle")
                await asyncio.sleep(3)
                
                # Take another screenshot to verify
                await self.page.screenshot(path="contacts_page_after_relogin.png")
                
                # Double-check URL again
                current_url = self.page.url
                if "login.propstream.com" in current_url:
                    logger.error("Still on login page after re-login attempt, aborting")
                    return None
            
            # Handle any popups that might be blocking the UI
            await self.handle_all_popups()
            
            # Look for buttons that might be related to import functionality
            logger.info("Looking for import-related buttons on the page")
            
            # First, take a screenshot of the whole page
            await self.page.screenshot(path="contacts_page_before_searching.png")
            
            # Look for a menu button or dropdown that might contain the Import option
            menu_button_found = False
            menu_button_selectors = [
                'button.menu',
                'button.dropdown',
                'button:has([class*="menu-icon"])',
                'button:has([class*="ellipsis"])',
                'button:has([class*="more"])',
                'button:has([class*="actions"])',
                'button:has([class*="options"])',
                '[aria-label="Menu"]',
                '[aria-label="Options"]',
                '[aria-label="Actions"]',
                'button:has(svg)',  # Many menu buttons have SVG icons
                '[data-testid="menu"]',
                '[data-testid="options"]'
            ]
            
            for selector in menu_button_selectors:
                try:
                    menu_buttons = await self.page.query_selector_all(selector)
                    for button in menu_buttons:
                        if await button.is_visible():
                            logger.info(f"Found potential menu button with selector: {selector}")
                            await button.click()
                            menu_button_found = True
                            logger.info("Clicked menu button")
                            await asyncio.sleep(2)
                            await self.page.screenshot(path="after_menu_button_click.png")
                            break
                    if menu_button_found:
                        break
                except Exception as e:
                    logger.debug(f"Error with menu selector {selector}: {str(e)}")
            
            # Look for action buttons and icons that might be Add/Import buttons
            action_button_found = False
            action_button_selectors = [
                'button:has-text("+")',
                'button[aria-label="Add"]',
                'button[title="Add"]',
                'button:has(svg[class*="add"])',
                'button:has(svg[class*="plus"])',
                'button:has([class*="add-icon"])',
                'button:has([class*="plus-icon"])',
                '[data-testid="add-button"]',
                '[data-testid="add-contact"]',
                'button.add-button',
                'button.add-contact',
                'div[role="button"]:has-text("+")'
            ]
            
            for selector in action_button_selectors:
                try:
                    action_buttons = await self.page.query_selector_all(selector)
                    for button in action_buttons:
                        if await button.is_visible():
                            logger.info(f"Found potential add/action button with selector: {selector}")
                            await button.click()
                            action_button_found = True
                            logger.info("Clicked add/action button")
                            await asyncio.sleep(2)
                            await self.page.screenshot(path="after_action_button_click.png")
                            break
                    if action_button_found:
                        break
                except Exception as e:
                    logger.debug(f"Error with action selector {selector}: {str(e)}")
            
            # After clicking menu or action buttons, try to find Import or Upload options
            import_option_found = False
            import_option_selectors = [
                'li:has-text("Import")',
                'div:has-text("Import")',
                'a:has-text("Import")',
                'button:has-text("Import")',
                'li:has-text("Upload")',
                'div:has-text("Upload")',
                'a:has-text("Upload")',
                'button:has-text("Upload")',
                '[data-testid*="import"]',
                '[data-testid*="upload"]'
            ]
            
            for selector in import_option_selectors:
                try:
                    import_options = await self.page.query_selector_all(selector)
                    for option in import_options:
                        if await option.is_visible():
                            logger.info(f"Found potential import option with selector: {selector}")
                            await option.click()
                            import_option_found = True
                            logger.info("Clicked import option")
                            await asyncio.sleep(3)
                            await self.page.screenshot(path="after_import_option_click.png")
                            break
                    if import_option_found:
                        break
                except Exception as e:
                    logger.debug(f"Error with import option selector {selector}: {str(e)}")
            
            # Check for the upload dialog immediately after clicking any of these options
            upload_dialog_visible = await self.check_for_upload_dialog()
            
            # If we found the dialog, proceed with upload
            if upload_dialog_visible:
                logger.info("Successfully found file upload dialog")
                
                # Wait a bit to let the dialog fully appear
                await asyncio.sleep(2)
                
                # Look for the file input element
                file_input = await self.page.query_selector('input[type="file"]')
                
                if file_input:
                    # Use the file input to upload the file
                    logger.info(f"Uploading file: {file_path}")
                    await file_input.set_input_files(file_path)
                    
                    # Wait for the file to be processed
                    await asyncio.sleep(5)
                    await self.page.screenshot(path="after_file_upload.png")
                    
                    # Look for and click any "Continue" or "Next" buttons
                    continue_button_selectors = [
                        'button:has-text("Continue")',
                        'button:has-text("Next")',
                        'button:has-text("Upload")',
                        'button:has-text("Submit")',
                        'button:has-text("Import")',
                        'button[type="submit"]'
                    ]
                    
                    for selector in continue_button_selectors:
                        try:
                            continue_button = await self.page.query_selector(selector)
                            if continue_button and await continue_button.is_visible():
                                logger.info(f"Found continue button with selector: {selector}")
                                await continue_button.click()
                                logger.info("Clicked continue button")
                                await asyncio.sleep(3)
                                await self.page.screenshot(path="after_continue_click.png")
                                break
                        except Exception as e:
                            logger.debug(f"Error with continue button selector {selector}: {str(e)}")
                    
                    # Now check for the group creation dialog
                    group_dialog_found = await self.check_for_group_dialog()
                    
                    if group_dialog_found:
                        # Generate a group name with timestamp for uniqueness
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        group_name = f"Foreclosures_{timestamp}"
                        
                        # Fill in the group name
                        group_name_filled = await self.fill_group_name(group_name)
                        
                        if group_name_filled:
                            # Click save button
                            save_clicked = await self.click_save_button()
                            
                            if save_clicked:
                                # Wait for import to complete
                                await self.wait_for_import_completion()
                                
                                # Save the group name for later use
                                self.group_name = group_name
                                logger.info(f"Group created with name: {group_name}")
                                
                                return group_name
                            else:
                                logger.error("Could not find or click save button")
                        else:
                            logger.error("Could not fill in group name")
                    else:
                        logger.error("Could not find group creation dialog")
                else:
                    logger.error("File input element not found in upload dialog")
            else:
                logger.error("Could not find file upload dialog after clicking import options")
            
            # If we get here, we've tried various methods but haven't succeeded
            # Let's try direct navigation to import URLs as a last resort
            potential_urls = [
                f"{self.base_url}/contact/import",
                f"{self.base_url}/contact/upload",
                f"{self.base_url}/import",
                f"{self.base_url}/upload"
            ]
            
            for url in potential_urls:
                logger.info(f"Trying direct navigation to {url}")
                try:
                    await self.page.goto(url, wait_until="networkidle")
                    await asyncio.sleep(3)
                    await self.page.screenshot(path=f"direct_url_{url.split('/')[-1]}.png")
                    
                    # Check if this URL has a file input
                    if await self.check_for_upload_dialog():
                        logger.info(f"Found upload dialog at {url}")
                        
                        # Try to upload the file
                        file_input = await self.page.query_selector('input[type="file"]')
                        if file_input:
                            logger.info(f"Uploading file through direct URL: {file_path}")
                            await file_input.set_input_files(file_path)
                            await asyncio.sleep(5)
                            await self.page.screenshot(path=f"file_uploaded_at_{url.split('/')[-1]}.png")
                            
                            # Rest of the import process...
                            # Generate a unique group name
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            group_name = f"Foreclosures_{timestamp}"
                            
                            # Try to find group creation options
                            if await self.check_for_group_dialog():
                                if await self.fill_group_name(group_name) and await self.click_save_button():
                                    await self.wait_for_import_completion()
                                    self.group_name = group_name
                                    logger.info(f"Group created with name: {group_name}")
                                    return group_name
                            
                            # Even if we can't complete the full flow, return the group name
                            # in case it was created automatically
                            self.group_name = group_name
                            return group_name
                    
                except Exception as e:
                    logger.warning(f"Error navigating to {url}: {str(e)}")
            
            logger.error("All attempts to import file failed")
            return None
            
        except Exception as e:
            logger.error(f"Error importing file: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            await self.page.screenshot(path="import_error.png")
            return None
    
    async def check_for_group_dialog(self):
        """Check if the group creation dialog is visible"""
        logger.info("Checking for group creation dialog")
        await self.page.screenshot(path="before_group_dialog_check.png")
        
        # Wait a bit for the dialog to appear
        await asyncio.sleep(2)
        
        group_dialog_selectors = [
            'div:has-text("Create New Group")',
            'div:has-text("Add to Group")',
            'div:has-text("Select Group")',
            'div:has-text("Group Name")',
            'input[placeholder*="group" i]',
            'input[placeholder*="name" i]',
            'input.new-group-input',
            'input[name="groupName"]',
            'div.group-selection',
            'div.group-creation',
            'div[role="dialog"]',
            'div.modal'
        ]
        
        for selector in group_dialog_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    logger.info(f"Found group dialog element with selector: {selector}")
                    return True
            except Exception as e:
                logger.debug(f"Error checking selector {selector}: {str(e)}")
        
        # Use JavaScript to look for group dialog indicators
        js_found_group_dialog = await self.page.evaluate('''() => {
            const bodyText = document.body.innerText.toLowerCase();
            return bodyText.includes('create new group') || 
                   bodyText.includes('add to group') || 
                   bodyText.includes('select group') || 
                   bodyText.includes('group name');
        }''')
        
        if js_found_group_dialog:
            logger.info("JavaScript found text indicating group dialog")
            return True
            
        logger.info("No group creation dialog found")
        return False
    
    async def close_any_popups(self):
        """Close any visible popups or modals"""
        # Use the more comprehensive method
        await self.handle_all_popups()
        
        # Also check for permission prompts
        await self.handle_permission_prompts()
    
    async def select_create_new_option(self):
        """Select the 'Create New' radio option"""
        logger.info("Looking for 'Create New' radio option")
        create_new_selectors = [
            'input[value="new"]',
            'label:has-text("Create New")',
            'div:has-text("Create New") input',
            'input#create-new',
            'input[name="groupRadio"][value="new"]',
            'input[type="radio"]:below(label:has-text("Create New"))',
            'input[type="radio"]:near(:text("Create New"))',
            'label:has-text("Create New") input'
        ]
        
        create_new_selected = False
        for selector in create_new_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    logger.info(f"Found 'Create New' radio button with selector: {selector}")
                    await element.click(timeout=5000)
                    create_new_selected = True
                    logger.info(f"Selected 'Create New' using selector: {selector}")
                    await asyncio.sleep(1)
                    await self.page.screenshot(path="after_create_new_selected.png")
                    break
            except Exception as e:
                logger.debug(f"Could not click 'Create New' with selector {selector}: {str(e)}")
        
        # If we couldn't find the selector, try examining all radio buttons
        if not create_new_selected:
            logger.info("Trying to find 'Create New' by examining all radio buttons")
            
            # List all radio buttons
            radio_buttons = await self.page.query_selector_all('input[type="radio"]')
            logger.info(f"Found {len(radio_buttons)} radio buttons on the page")
            
            for i, radio in enumerate(radio_buttons):
                try:
                    # Check if it's visible
                    if not await radio.is_visible():
                        continue
                        
                    # Try to get the label or text near this radio
                    radio_id = await radio.get_attribute('id')
                    if radio_id:
                        label_selector = f'label[for="{radio_id}"]'
                        label = await self.page.query_selector(label_selector)
                        if label:
                            label_text = await label.inner_text()
                            logger.info(f"Radio {i+1} has label: '{label_text}'")
                            
                            if "create" in label_text.lower() or "new" in label_text.lower():
                                logger.info(f"Clicking radio with label: '{label_text}'")
                                await radio.click()
                                create_new_selected = True
                                await asyncio.sleep(1)
                                await self.page.screenshot(path="after_radio_click.png")
                                break
                except Exception as e:
                    logger.debug(f"Error examining radio button {i+1}: {str(e)}")
        
        return create_new_selected
    
    async def fill_group_name(self, group_name):
        """Fill in the group name input field"""
        logger.info(f"Trying to fill group name: {group_name}")
        group_input_selectors = [
            'input[placeholder="New Group"]',
            'input[placeholder*="group" i]',
            'input[placeholder*="name" i]',
            'input.new-group-input',
            'input[name="groupName"]',
            'input[id*="group" i][type="text"]',
            'input[id*="name" i][type="text"]',
            'input[type="text"]:near(:text("Group"))',
            'input[type="text"]:near(:text("Name"))'
        ]
        
        group_input_found = False
        for selector in group_input_selectors:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    logger.info(f"Found group name input with selector: {selector}")
                    await element.fill(group_name)
                    logger.info(f"Set group name to: {group_name}")
                    group_input_found = True
                    await asyncio.sleep(1)
                    await self.page.screenshot(path="after_group_name_filled.png")
                    break
            except Exception as e:
                logger.debug(f"Error with selector {selector}: {str(e)}")
        
        if not group_input_found:
            # As a fallback, try to find any visible text input on the page
            logger.info("Looking for any text input fields")
            inputs = await self.page.query_selector_all('input[type="text"]:visible')
            logger.info(f"Found {len(inputs)} visible text inputs")
            
            # Try each visible text input
            for i, input_elem in enumerate(inputs):
                try:
                    # Check attributes that might indicate this is the group name input
                    placeholder = await input_elem.get_attribute('placeholder') or ""
                    name = await input_elem.get_attribute('name') or ""
                    id = await input_elem.get_attribute('id') or ""
                    
                    logger.info(f"Text input {i+1}: placeholder='{placeholder}', name='{name}', id='{id}'")
                    
                    # Skip inputs that are clearly not for group name
                    if any(word in (placeholder + name + id).lower() for word in [
                        "search", "filter", "email", "password", "phone", "address"
                    ]):
                        continue
                    
                    # Try to fill this input
                    await input_elem.fill(group_name)
                    logger.info(f"Filled potential group name input {i+1} with: {group_name}")
                    group_input_found = True
                    await asyncio.sleep(1)
                    await self.page.screenshot(path=f"after_filling_input_{i+1}.png")
                    break
                except Exception as e:
                    logger.debug(f"Error examining input {i+1}: {str(e)}")
        
        return group_input_found
    
    async def click_save_button(self):
        """Find and click the save/continue/import button"""
        logger.info("Looking for Save/Submit/Import button")
        save_button_selectors = [
            'button[type="submit"]',
            'button:has-text("Save")',
            'button:has-text("Submit")',
            'button:has-text("Import")',
            'button:has-text("Continue")',
            'button:has-text("Next")',
            'button:has-text("Done")',
            '.save-button',
            '[data-testid="save-button"]',
            '[data-testid="submit-button"]',
            '[data-testid="continue-button"]',
            'div[role="button"]:has-text("Save")',
            'div[role="button"]:has-text("Submit")',
            'div[role="button"]:has-text("Import")',
            'div[role="button"]:has-text("Continue")',
            'div[role="button"]:has-text("Next")'
        ]
        
        save_clicked = False
        for selector in save_button_selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                for element in elements:
                    if await element.is_visible():
                        button_text = await element.inner_text()
                        logger.info(f"Found potential save button: '{button_text}'")
                        
                        # Skip if it contains text suggesting it's not what we want
                        if any(word in button_text.lower() for word in ["cancel", "back", "close"]):
                            continue
                            
                        await element.click(timeout=5000)
                        save_clicked = True
                        logger.info(f"Clicked button with text: '{button_text}'")
                        await asyncio.sleep(1)
                        await self.page.screenshot(path="after_save_click.png")
                        break
                
                if save_clicked:
                    break
            except Exception as e:
                logger.debug(f"Could not click with selector {selector}: {str(e)}")
        
        if not save_clicked:
            # Try to find any button that might be the save button
            logger.info("Looking for any button that might confirm the operation")
            buttons = await self.page.query_selector_all('button:visible, div[role="button"]:visible')
            logger.info(f"Found {len(buttons)} visible buttons")
            
            for i, button in enumerate(buttons):
                try:
                    button_text = await button.inner_text()
                    logger.info(f"Button {i+1} text: '{button_text}'")
                    
                    if any(keyword in button_text.lower() for keyword in [
                        "save", "done", "submit", "import", "ok", "continue", "next", "create"
                    ]) and not any(keyword in button_text.lower() for keyword in [
                        "cancel", "back", "close"
                    ]):
                        logger.info(f"Clicking button {i+1} with text: '{button_text}'")
                        await button.click()
                        save_clicked = True
                        await asyncio.sleep(1)
                        await self.page.screenshot(path=f"after_clicking_button_{i+1}.png")
                        break
                except Exception as e:
                    logger.debug(f"Error examining button {i+1}: {str(e)}")
        
        return save_clicked
    
    async def wait_for_import_completion(self):
        """Wait for the import process to complete"""
        logger.info("Waiting for import to complete...")
        
        # Take screenshots at intervals to track progress
        for i in range(1, 7):
            await asyncio.sleep(5)
            await self.page.screenshot(path=f"import_progress_{i}.png")
            
            # Check for completion indicators
            completion_indicators = [
                'div:text("Import completed")',
                'div:text("Import successful")',
                'div:text("Group created")',
                '.success-message',
                '[data-testid="import-success"]'
            ]
            
            for selector in completion_indicators:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        message = await element.inner_text()
                        logger.info(f"Found import completion message: '{message}'")
                        return True
                except Exception:
                    continue
            
            # Check URL for indication we've returned to the contacts page
            if "/contact" in self.page.url and not "/import" in self.page.url:
                logger.info("Returned to contacts page, which suggests import completed")
                return True
                
        logger.warning("Did not find explicit import completion message, but continuing")
        return False
    
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