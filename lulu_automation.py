#!/usr/bin/env python3
"""
Lulu.com book upload automation
Phase 1: Manual login to capture cookies

Author: Claude (Anthropic AI Assistant)
License: MIT
"""

# TODO: Instead of waiting for user to press Enter, watch for a specific
# authentication cookie to be set (e.g., session token or auth cookie)
# and automatically proceed once detected

import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

COOKIES_FILE = Path("lulu_cookies.json")
START_URL = "https://www.lulu.com/account/wizard/draft/start"


async def save_cookies_interactive():
    """
    Open browser, let user log in manually, then save cookies.
    """
    async with async_playwright() as p:
        # Launch browser in headed mode with stealth settings
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        # Remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        page = await context.new_page()
        
        print("Opening Lulu.com...")
        print("Please log in manually and solve any CAPTCHAs.")
        print("Once you're logged in and see the dashboard, press Enter here...")
        
        await page.goto(START_URL)
        
        # Wait for user to complete login
        input()
        
        # Save cookies
        cookies = await context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"✓ Saved {len(cookies)} cookies to {COOKIES_FILE}")
        
        await browser.close()


async def save_cookies_persistent():
    """
    Alternative: Use persistent browser context (like a real Chrome profile).
    This often works better with CAPTCHAs since it looks more like a real browser.
    """
    async with async_playwright() as p:
        # Use a persistent context with user data dir
        user_data_dir = Path("./chrome_profile")
        user_data_dir.mkdir(exist_ok=True)
        
        context = await p.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )
        
        page = context.pages[0] if context.pages else await context.new_page()
        
        print("Opening Lulu.com with persistent profile...")
        print("Please log in manually and solve any CAPTCHAs.")
        print("Once you're logged in and see the dashboard, press Enter here...")
        
        await page.goto(START_URL)
        
        # Wait for user to complete login
        input()
        
        # Save cookies
        cookies = await context.cookies()
        COOKIES_FILE.write_text(json.dumps(cookies, indent=2))
        print(f"✓ Saved {len(cookies)} cookies to {COOKIES_FILE}")
        
        await context.close()


async def test_saved_cookies():
    """
    Test that saved cookies work by navigating to the start page.
    """
    if not COOKIES_FILE.exists():
        print("No cookies file found. Run save_cookies_interactive() first.")
        return
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        
        # Load cookies
        cookies = json.loads(COOKIES_FILE.read_text())
        await context.add_cookies(cookies)
        
        page = await context.new_page()
        print("Testing saved cookies...")
        await page.goto(START_URL)
        
        # Wait a bit to see if we're logged in
        await asyncio.sleep(3)
        
        # Check if we're still logged in (you can verify visually)
        print("Check if you're logged in. Press Enter to close...")
        input()
        
        await browser.close()


async def main():
    """Main entry point - saves cookies interactively."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--persistent":
        print("Using persistent browser context (better for CAPTCHA)...")
        await save_cookies_persistent()
    else:
        print("Using regular context (pass --persistent flag if CAPTCHA fails)...")
        await save_cookies_interactive()
    
    print("\nTesting cookies...")
    await test_saved_cookies()


if __name__ == "__main__":
    asyncio.run(main())
