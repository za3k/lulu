#!/usr/bin/env python3
"""
Lulu.com book upload automation

Author: Claude (Anthropic AI Assistant)
License: MIT

To use with a .env file:
    pip install python-dotenv --break-system-packages
    
    Create a .env file with:
    LULU_USERNAME=your-username
    LULU_PASSWORD=your-password
    
    Then run: python lulu_automation.py
"""

# TODO: Instead of waiting for user to press Enter, watch for a specific
# authentication cookie to be set (e.g., session token or auth cookie)
# and automatically proceed once detected

import json
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import time

load_dotenv()

START_URL = "https://www.lulu.com/account/wizard/draft/start"
PROJECT_ID_FILE = Path(".lulu_project_counter.txt")

# Login credentials from environment variables
LULU_USERNAME = os.environ.get("LULU_USERNAME", "")
LULU_PASSWORD = os.environ.get("LULU_PASSWORD", "")

if not LULU_USERNAME or not LULU_PASSWORD:
    print("⚠️  Warning: LULU_USERNAME and LULU_PASSWORD not set in environment")
    print("   Set them in a .env file or export them before running")


def get_next_project_id():
    """Get next sequential project ID, persisted to disk."""
    if PROJECT_ID_FILE.exists():
        current_id = int(PROJECT_ID_FILE.read_text().strip())
    else:
        current_id = 0
    
    next_id = current_id + 1
    PROJECT_ID_FILE.write_text(str(next_id))
    return next_id


# Reusable automation primitives

async def wait_for_text(page, text, timeout=30000):
    """Wait for text to appear on the page."""
    print(f"⏳ Waiting for text: '{text}'")
    await page.wait_for_selector(f"text={text}", timeout=timeout)
    print(f"✓ Found text: '{text}'")


async def click_button(page, text):
    """Click a button with the given text."""
    print(f"🖱️  Clicking button: '{text}'")
    await page.click(f"button:has-text('{text}')")
    await page.wait_for_timeout(500)  # Small delay after click


async def check_for_selector(page, selector, timeout=1000):
    """
    Check if a selector exists on the page.
    
    Args:
        page: Playwright page object
        selector: CSS selector to check for
        timeout: How long to wait in milliseconds
        
    Returns:
        True if selector found, False otherwise
    """
    try:
        start = time.time()
        await page.wait_for_selector(selector, timeout=timeout)
        elapsed = time.time() - start
        print(f"Waited {int(elapsed*1000)}/{timeout}ms")
        return True
    except:
        return False


async def select_radio(page, value):
    """Select a radio button by clicking its label."""
    print(f"◉ Selecting: '{value}'")
    await page.click(f"label:has-text('{value}')")
    await page.wait_for_timeout(300)


async def fill_field(page, label, value):
    """Fill a text field identified by its label."""
    print(f"✏️  Filling field '{label}' with: '{value}'")
    
    # Try standard patterns first (next sibling, following sibling, placeholder)
    simple_selectors = [
        f"label:has-text('{label}') + input",
        f"label:has-text('{label}') ~ input",
        f"input[placeholder*='{label}']"
    ]
    
    for selector in simple_selectors:
        if await check_for_selector(page, selector, timeout=500):
            await page.fill(selector, value)
            await page.wait_for_timeout(300)
            return
    
    # Try previous sibling case (input before label)
    label_elem = await page.query_selector(f"label:has-text('{label}')")
    if label_elem:
        input_elem = await page.evaluate_handle("(el) => el.previousElementSibling", label_elem)
        if input_elem:
            await input_elem.as_element().fill(value)
            await page.wait_for_timeout(300)
            return
    
    raise Exception(f"Could not find field '{label}'")


async def fill_field_by_selector(page, selectors, value, description="field"):
    """
    Try multiple selectors to fill a field.
    
    Args:
        page: Playwright page object
        selectors: List of CSS selectors to try
        value: Value to fill
        description: Description for logging
    """
    print(f"✏️  Filling {description} with: '{value}'")
    for selector in selectors:
        if await check_for_selector(page, selector, timeout=500):
            await page.fill(selector, value)
            await page.wait_for_timeout(300)
            return True
    raise Exception(f"Could not find {description} using any selector")


async def click_by_selector(page, selectors, description="button"):
    """
    Try multiple selectors to click an element.
    
    Args:
        page: Playwright page object
        selectors: List of CSS selectors to try
        description: Description for logging
    """
    print(f"🖱️  Clicking {description}")
    for selector in selectors:
        if await check_for_selector(page, selector, timeout=500):
            await page.click(selector)
            await page.wait_for_timeout(500)
            return True
    raise Exception(f"Could not find {description} using any selector")


async def upload_file(page, file_path, description="file"):
    """
    Upload a file by finding the file input element.
    
    Args:
        page: Playwright page object
        file_path: Path to file to upload
        description: Description for logging
    """
    print(f"📤 Uploading {description}: {file_path}")
    
    # Find the file input - it's often hidden, so we look for any file input
    file_input = await page.query_selector("input[type='file']")
    if not file_input:
        raise Exception(f"Could not find file input for {description}")
    
    await file_input.set_input_files(str(file_path))
    
    # Trigger change event to make sure UI updates
    await page.evaluate("(input) => { input.dispatchEvent(new Event('change', { bubbles: true })); }", file_input)
    
    await page.wait_for_timeout(1000)  # Wait a bit for upload to process
    print(f"✓ Uploaded {description}")


async def ensure_logged_in(context, page):
    """
    Ensure user is logged in. Automates login if needed.
    Returns True if logged in successfully.
    """
    print("Checking login status...")
    await page.goto(START_URL)
    
    if await check_for_selector(page, "text=Select a Product Type", timeout=1000):
        print("✓ Already logged in")
        return True
    
    print("❌ Not logged in. Attempting automated login...")
    
    # Check if CAPTCHA is present, wait for user to solve it if so.
    dots = 0
    while (not await check_for_selector(page, "text=Select a Product Type", timeout=100) and
           not await check_for_selector(page, "input[name=username]", timeout=100)):
        if dots == 0:
            print("Please complete CAPTCHA/login manually", end='', file=sys.stderr)
        print(".", end='', file=sys.stderr) 
        dots += 1
        time.sleep(1)
        sys.stderr.flush()
    if dots > 0:
        print(file=sys.stderr)
    
    await fill_field_by_selector(
        page,
        ["input[name='username'], input[id*='username']"],
        LULU_USERNAME,
        "username"
    )
    
    await fill_field_by_selector(
        page,
        ["input[type='password']", "input[name='password']", "input[id*='password']"],
        LULU_PASSWORD,
        "password"
    )
    
    await click_by_selector(
        page,
        ["button[type='submit']", "button:has-text('Log in')", "button:has-text('Sign in')", "input[type='submit']"],
        "login button"
    )
    
    print("⏳ Waiting for login to complete...")
    
    # Wait for successful login
    if await check_for_selector(page, "text=Select a Product Type", timeout=5000):
        print("✓ Logged in successfully")
        return True
    
    # Check again
    if await check_for_selector(page, "text=Select a Product Type", timeout=2000):
        print("✓ Login completed")
        return True
    
    print("❌ Still not logged in. Exiting.")
    return False


async def create_book_page1(page, project_title=None):
    """
    Page 1: Select product type and fill initial details.
    
    Args:
        page: Playwright page object
        project_title: Optional project title. If None, uses sequential ID.
    """
    # Wait for page to load - check for "Select a Product Type"
    await wait_for_text(page, "Select a Product Type")
    
    # Select "Print Book" (already default, but click to be safe)
    await select_radio(page, "Print Book")
    
    # Select "Print Your Book" goal
    await select_radio(page, "Print Your Book")
    
    # Generate project title if not provided
    if project_title is None:
        project_id = get_next_project_id()
        project_title = f"Book_{project_id}"
    
    print(f"📘 Project title: {project_title}")
    
    # Fill project title field
    await fill_field(page, "project title", project_title)
    
    # Skip "Book language (optional)" - it's complicated autocomplete
    
    # Fill Book category with "Fiction"
    await fill_field(page, "Book category", "Fiction")
    
    # Click "Design your project" to continue
    await click_button(page, "Design your project")
    
    print("✓ Page 1 complete")


async def create_book_page2(page, pdf_path):
    """
    Page 2: Upload PDF interior file.
    
    Args:
        page: Playwright page object
        pdf_path: Path to PDF file to upload
    """
    print(f"📄 Uploading PDF: {pdf_path}")
    
    # Wait for page to fully load - look for file inputs
    print("⏳ Waiting for page to load...")
    await page.wait_for_timeout(2000)
    
    # Find all file inputs
    file_inputs = await page.query_selector_all("input[type='file']")
    
    if len(file_inputs) == 0:
        raise Exception("No file inputs found on page")
    
    print(f"✓ Found {len(file_inputs)} file input(s)")
    
    # Use the first file input (likely the interior PDF)
    # Input 0 should be the interior, Input 4 might be the cover
    print("✓ Page loaded, starting upload...")
    await upload_file(page, pdf_path, "pdf book")
    
    # Wait for upload flow to start (avoid race condition)
    print("⏳ Waiting for upload to start...")
    if await check_for_selector(page, "text=Your file is uploading", timeout=5000):
        print("✓ Upload started")
    
    # Wait for validation to start
    print("⏳ Waiting for validation...")
    if await check_for_selector(page, "text=Your file is validating", timeout=30000):
        print("✓ Validation started")
    
    # Wait for final result - success or error
    print("⏳ Waiting for validation result...")
    success = await check_for_selector(page, "text=Your Book file was successfully uploaded!", timeout=120000)
    error = await check_for_selector(page, "[data-testid*='file-upload-notification-error']", timeout=1000)
    
    if error:
        print("❌ Page 2 failed - PDF upload error")
        return False
    elif not success:
        print("⚠️  Page 2 status unclear - check manually")
        return False

    # Interior Color
    await select_radio(page, "Standard Black")
    #await select_radio(page, "Standard Color")
    
    # Paper Type
    await select_radio(page, "60# White")

    # Binding Type
    hardcover_spine = {
        (0, 23): None,
        (24, 84): 6,
        # TODO: ...
    }
    if num_pages > 23: # TODO: This is not actually defined
        await select_radio(page, "Hardcover Case Wrap") # Choice A, will be selected if not greyed out
    else
        await select_radio(page, "Paperback Saddle Stitch") # Choice B, needed for short books.
    #await select_radio(page, "Paperback Perfect Bound") # Choice A

    # Cover Finish
    await select_radio(page, "Glossy")

    await wait_for_text(page, "Print Cost")
    # TODO: data-testid[print-cost] -- print it!

    await select_radio(page, "Upload Your Cover")
    # TODO: Upload the cover, now. It should be a one-page PDF with wraparound format, including the back, spine, and front. Spine width is a function of page size and number, but not sure what exactly.

    input("Press Enter to continue after reviewing the book preview")

    # Click "Design your project" to continue
    await click_button(page, "Review Book")
    
    print("✓ Page 1 complete")


async def automate_book_upload(pdf_path=None):
    """
    Full automation: upload a book to Lulu.
    Handles login automatically if needed.
    
    Args:
        pdf_path: Path to PDF file to upload. Required.
    """
    if not pdf_path:
        print("❌ Error: pdf_path is required")
        return
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"❌ Error: PDF file not found: {pdf_path}")
        return
    
    async with async_playwright() as p:
        # Use persistent context with saved profile
        user_data_dir = Path("./chrome_profile")
        user_data_dir.mkdir(exist_ok=True)
        
        context = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("🚀 Starting book upload automation...")
        
        # Ensure we're logged in
        if not await ensure_logged_in(context, page):
            print("❌ Failed to log in")
            await context.close()
            return
        
        # Page 1: Initial setup
        await create_book_page1(page)
        
        # Page 2: Upload PDF
        if not await create_book_page2(page, pdf_path):
            print("❌ Failed to upload PDF")
            await context.close()
            return
        
        # TODO: Add more pages here as we implement them
        print("⏸️  Pausing for manual continuation...")
        input("Press Enter to close browser...")
        
        await context.close()


if __name__ == "__main__":
    import sys
    
    # Single mode: always run automation (will log in if needed)
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(automate_book_upload(pdf_path))
