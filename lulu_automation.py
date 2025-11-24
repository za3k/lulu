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

# Try to load .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

COOKIES_FILE = Path("lulu_cookies.json")
START_URL = "https://www.lulu.com/account/wizard/draft/start"
PROJECT_ID_FILE = Path("lulu_project_counter.txt")

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


async def select_radio(page, value):
    """Select a radio button by clicking its label."""
    print(f"◉ Selecting: '{value}'")
    await page.click(f"label:has-text('{value}')")
    await page.wait_for_timeout(300)


async def fill_field(page, label, value):
    """Fill a text field identified by its label."""
    print(f"✏️  Filling field '{label}' with: '{value}'")
    # Find input associated with label
    input_selector = f"label:has-text('{label}') + input, label:has-text('{label}') ~ input, input[placeholder*='{label}']"
    await page.fill(input_selector, value)
    await page.wait_for_timeout(300)


async def fill_field_by_selectors(page, selectors, value, description="field"):
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
        try:
            await page.fill(selector, value, timeout=2000)
            await page.wait_for_timeout(300)
            return True
        except:
            continue
    raise Exception(f"Could not find {description} using any selector")


async def click_by_selectors(page, selectors, description="button"):
    """
    Try multiple selectors to click an element.
    
    Args:
        page: Playwright page object
        selectors: List of CSS selectors to try
        description: Description for logging
    """
    print(f"🖱️  Clicking {description}")
    for selector in selectors:
        try:
            await page.click(selector, timeout=2000)
            await page.wait_for_timeout(500)
            return True
        except:
            continue
    raise Exception(f"Could not find {description} using any selector")


async def ensure_logged_in(context, page):
    """
    Ensure user is logged in. Automates login if needed.
    Returns True if logged in successfully.
    """
    print("🔐 Checking login status...")
    await page.goto(START_URL)
    
    try:
        # Check if we're already logged in
        await page.wait_for_selector("text=Select a Product Type", timeout=1000)
        print("✓ Already logged in")
        return True
    except:
        print("❌ Not logged in. Attempting automated login...")
        
        # Fill in username
        await fill_field_by_selectors(
            page,
            ["input[type='text']", "input[name='username']", "input[id*='username']", "input[type='email']", "input[name='email']"],
            LULU_USERNAME,
            "username"
        )
        
        # Fill in password
        await fill_field_by_selectors(
            page,
            ["input[type='password']", "input[name='password']", "input[id*='password']"],
            LULU_PASSWORD,
            "password"
        )
        
        # Click login button
        await click_by_selectors(
            page,
            ["button[type='submit']", "button:has-text('Log in')", "button:has-text('Sign in')", "input[type='submit']"],
            "login button"
        )
        
        print("⏳ Waiting for login to complete...")
        
        # Wait for either successful login or CAPTCHA
        try:
            await page.wait_for_selector("text=Select a Product Type", timeout=15000)
            print("✓ Logged in successfully")
            return True
        except:
            print("⚠️  Login may require CAPTCHA or failed.")
            print("Please complete login manually, then press Enter...")
            input()
            
            # Check again
            try:
                await page.wait_for_selector("text=Select a Product Type", timeout=2000)
                print("✓ Login completed")
                return True
            except:
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
    
    # Pause to verify inputs before continuing
    input("Press Enter to click 'Design your project'")
    
    # Click "Design your project" to continue
    await click_button(page, "Design your project")
    
    print("✓ Page 1 complete")


async def automate_book_upload(pdf_path=None):
    """
    Full automation: upload a book to Lulu.
    Handles login automatically if needed.
    
    Args:
        pdf_path: Path to PDF file to upload. If None, will need to be provided.
    """
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
        await ensure_logged_in(context, page)
        
        # Page 1: Initial setup
        await create_book_page1(page)
        
        # TODO: Add more pages here as we implement them
        print("⏸️  Pausing for manual continuation...")
        input("Press Enter to close browser...")
        
        await context.close()


if __name__ == "__main__":
    import sys
    
    # Single mode: always run automation (will log in if needed)
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(automate_book_upload(pdf_path))
