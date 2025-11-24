#!/usr/bin/env python3
"""
Lulu.com book upload automation
Phase 1: Manual login to capture cookies
"""

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
        # Launch browser in headed mode so user can interact
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
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
    await save_cookies_interactive()
    print("\nTesting cookies...")
    await test_saved_cookies()


if __name__ == "__main__":
    asyncio.run(main())
