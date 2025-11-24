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
from PyPDF2 import PdfReader
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, mm

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


def get_pdf_info(pdf_path):
    """
    Extract page count and dimensions from a PDF.
    
    Returns:
        dict with keys: page_count, width_inches, height_inches, width_mm, height_mm
    """
    reader = PdfReader(str(pdf_path))
    page_count = len(reader.pages)
    
    # Get dimensions from first page
    first_page = reader.pages[0]
    mediabox = first_page.mediabox
    
    # Dimensions are in points (1/72 inch)
    width_pts = float(mediabox.width)
    height_pts = float(mediabox.height)
    
    width_inches = width_pts / 72.0
    height_inches = height_pts / 72.0
    
    width_mm = width_inches * 25.4
    height_mm = height_inches * 25.4
    
    return {
        'page_count': page_count,
        'width_inches': width_inches,
        'height_inches': height_inches,
        'width_mm': width_mm,
        'height_mm': height_mm,
    }


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
    
    if await check_for_selector(page, "text=Select a Product Type", timeout=1500):
        print("✓ Already logged in")
        return True
    
    print("❌ Not logged in. Attempting automated login...")
    
    # Check if CAPTCHA is present, wait for user to solve it if so.
    dots = 0
    while (not await check_for_selector(page, "text=Select a Product Type", timeout=100) and
           not await check_for_selector(page, "input[name='username']", timeout=100)):
        if dots == 0:
            print("Please complete CAPTCHA/login manually", end='', file=sys.stderr)
        print(".", end='', file=sys.stderr) 
        dots += 1
        time.sleep(1)
        sys.stderr.flush()
    if dots > 0:
        print(file=sys.stderr)

    if await check_for_selector(page, "text=Select a Product Type", timeout=100):
        print("✓ Already logged in")
        return True
    
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


async def create_book_page2(page, pdf_path, cover_path, title="Untitled Book", subtitle="", author="Anonymous"):
    """
    Page 2: Upload PDF interior file.
    
    Args:
        page: Playwright page object
        pdf_path: Path to PDF file to upload
        cover_path: Path to generated cover PDF
        title: Book title
        subtitle: Book subtitle (optional)
        author: Author name
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

    print("✓ PDF validated successfully")
    
    # Get PDF info for page count
    pdf_info = get_pdf_info(pdf_path)
    
    # Extract page count from the page (should match our PDF info)
    page_count_input = await page.query_selector("input[id='page-count']")
    if page_count_input:
        num_pages_str = await page_count_input.get_attribute("value")
        num_pages = int(num_pages_str) if num_pages_str else pdf_info['page_count']
        print(f"📖 Page count from form: {num_pages}")
    else:
        num_pages = pdf_info['page_count']
        print(f"📖 Using PDF page count: {num_pages}")
    
    # Interior Color
    await select_radio(page, "Standard Black & White")
    
    # Paper Type
    await select_radio(page, "60# White")

    # Binding Type - choose based on page count
    if num_pages > 23:
        await select_radio(page, "Hardcover Case Wrap")
    else:
        await select_radio(page, "Paperback Saddle Stitch")

    # Cover Finish
    await select_radio(page, "Glossy")

    # Wait for print cost to appear
    await wait_for_text(page, "Print Cost", timeout=10000)
    
    # Extract and print the cost
    cost_elem = await page.query_selector("[data-testid='print-cost']")
    if cost_elem:
        cost_text = await cost_elem.inner_text()
        print(f"💰 Print Cost: {cost_text}")

    # Select "Upload Your Cover"
    await select_radio(page, "Upload Your Cover")
    
    # Wait for cover upload section to be ready
    await page.wait_for_timeout(1000)
    
    # Upload cover - find the second file input (index 1)
    print(f"📤 Uploading cover: {cover_path}")
    file_inputs = await page.query_selector_all("input[type='file']")
    if len(file_inputs) < 2:
        raise Exception("Cover file input not found")
    
    cover_input = file_inputs[1]  # Second file input is for cover
    await cover_input.set_input_files(str(cover_path))
    await page.evaluate("(input) => { input.dispatchEvent(new Event('change', { bubbles: true })); }", cover_input)
    
    print("⏳ Waiting for cover to upload and validate...")
    await page.wait_for_timeout(5000)
    
    # Wait for user to review
    input("⏸️  Press Enter to continue after reviewing the book preview...")

    # Click "Review Book" to continue
    await click_button(page, "Review Book")
    
    print("✓ Page 2 complete")
    return True


def get_spine_width(page_count):
    """
    Get spine width in mm for hardcover based on page count.
    Returns None if hardcover not available (< 24 pages).
    
    Based on Lulu's hardcover spine width table.
    """
    spine_table = [
        (0, 23, None),
        (24, 84, 6),
        (85, 140, 13),
        (141, 168, 16),
        (169, 194, 17),
        (195, 222, 19),
        (223, 250, 21),
        (251, 278, 22),
        (279, 306, 24),
        (307, 334, 25),
        (335, 360, 27),
        (361, 388, 29),
        (389, 416, 30),
        (417, 444, 32),
        (445, 472, 33),
        (473, 500, 35),
        (501, 528, 37),
        (529, 556, 38),
        (557, 582, 40),
        (583, 610, 41),
        (611, 638, 43),
        (639, 666, 44),
        (667, 694, 46),
        (695, 722, 48),
        (723, 750, 49),
        (751, 778, 51),
        (779, 799, 52),
        (800, 800, 54),
    ]
    
    for min_pages, max_pages, width_mm in spine_table:
        if min_pages <= page_count <= max_pages:
            return width_mm
    
    # If beyond 800 pages, extrapolate (though this is unlikely)
    if page_count > 800:
        return 54 + ((page_count - 800) // 28) * 2
    
    return None


def generate_cover_pdf(output_path, title, subtitle, author, front_width_mm, front_height_mm, spine_width_mm):
    """
    Generate a hardcover wraparound PDF.
    
    For hardcover: printed 0.75" larger than trim size, wrapped around board.
    
    Args:
        output_path: Where to save the cover PDF
        title: Book title
        subtitle: Book subtitle  
        author: Author name
        front_width_mm: Front cover width (trim size)
        front_height_mm: Front cover height (trim size)
        spine_width_mm: Spine width in mm
    """
    # Hardcover is 0.75" (19.05mm) larger than trim size
    wrap_extension_mm = 19.05
    
    # Calculate dimensions
    # Front/back each: trim_size + wrap_extension on all sides
    front_total_width_mm = front_width_mm + (2 * wrap_extension_mm)
    front_total_height_mm = front_height_mm + (2 * wrap_extension_mm)
    
    # Total cover width: back + spine + front
    total_width_mm = front_total_width_mm + spine_width_mm + front_total_width_mm
    total_height_mm = front_total_height_mm
    
    print(f"📐 Cover dimensions: {total_width_mm:.1f}mm x {total_height_mm:.1f}mm")
    print(f"   Front: {front_total_width_mm:.1f}mm x {front_total_height_mm:.1f}mm")
    print(f"   Spine: {spine_width_mm}mm")
    print(f"   Back: {front_total_width_mm:.1f}mm x {front_total_height_mm:.1f}mm")
    
    # Convert to points for ReportLab (1mm = 2.83465 points)
    total_width_pts = total_width_mm * 2.83465
    total_height_pts = total_height_mm * 2.83465
    
    # Create PDF
    c = canvas.Canvas(str(output_path), pagesize=(total_width_pts, total_height_pts))
    
    # Set background to white
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, total_width_pts, total_height_pts, fill=True, stroke=False)
    
    # Calculate positions (in points)
    front_start_x = (front_total_width_mm + spine_width_mm) * 2.83465
    spine_start_x = front_total_width_mm * 2.83465
    
    # Front cover text
    c.setFillColorRGB(0, 0, 0)
    
    # Title on front (large, centered)
    c.setFont("Helvetica-Bold", 36)
    front_center_x = front_start_x + (front_total_width_mm * 2.83465 / 2)
    c.drawCentredString(front_center_x, total_height_pts * 0.6, title)
    
    # Subtitle on front (medium)
    if subtitle:
        c.setFont("Helvetica", 24)
        c.drawCentredString(front_center_x, total_height_pts * 0.5, subtitle)
    
    # Author on front (bottom)
    c.setFont("Helvetica", 18)
    c.drawCentredString(front_center_x, total_height_pts * 0.2, author)
    
    # Spine text (vertical, centered)
    spine_center_x = spine_start_x + (spine_width_mm * 2.83465 / 2)
    
    c.saveState()
    c.translate(spine_center_x, total_height_pts / 2)
    c.rotate(90)
    
    c.setFont("Helvetica-Bold", 14)
    # Draw title and author on spine
    spine_text = f"{title}  —  {author}"
    c.drawCentredString(0, 0, spine_text)
    
    c.restoreState()
    
    # Back cover is blank (as requested)
    
    c.save()
    print(f"✓ Generated cover PDF: {output_path}")


async def automate_book_upload(pdf_path=None, title="Untitled Book", subtitle="", author="Anonymous"):
    """
    Full automation: upload a book to Lulu.
    Handles login automatically if needed.
    
    Args:
        pdf_path: Path to PDF file to upload. Required.
        title: Book title
        subtitle: Book subtitle (optional)
        author: Author name
    """
    if not pdf_path:
        print("❌ Error: pdf_path is required")
        return
    
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        print(f"❌ Error: PDF file not found: {pdf_path}")
        return
    
    # Get PDF info and generate cover upfront, before any browser interaction
    print("📄 Analyzing PDF...")
    pdf_info = get_pdf_info(pdf_path)
    print(f"📊 PDF Info: {pdf_info['page_count']} pages, {pdf_info['width_mm']:.1f}mm x {pdf_info['height_mm']:.1f}mm")
    
    # Calculate spine width
    spine_width_mm = get_spine_width(pdf_info['page_count'])
    if spine_width_mm:
        print(f"📏 Spine width for {pdf_info['page_count']} pages: {spine_width_mm}mm")
    else:
        print(f"⚠️  Using default spine width (book has {pdf_info['page_count']} pages)")
        spine_width_mm = 6  # Default fallback
    
    # Generate cover PDF
    cover_path = Path(pdf_path).parent / f"cover_{Path(pdf_path).stem}.pdf"
    print(f"📐 Generating cover PDF...")
    generate_cover_pdf(
        cover_path,
        title,
        subtitle,
        author,
        pdf_info['width_mm'],
        pdf_info['height_mm'],
        spine_width_mm
    )
    
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
        
        # Page 2: Upload PDF and cover
        if not await create_book_page2(page, pdf_path, cover_path, title, subtitle, author):
            print("❌ Failed to upload PDF")
            await context.close()
            return
        
        # TODO: Add more pages here as we implement them
        print("⏸️  Pausing for manual continuation...")
        input("Press Enter to close browser...")
        
        await context.close()


if __name__ == "__main__":
    import sys
    
    # Usage: python lulu_automation.py <pdf_path> [title] [subtitle] [author]
    if len(sys.argv) < 2:
        print("Usage: python lulu_automation.py <pdf_path> [title] [subtitle] [author]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "Untitled Book"
    subtitle = sys.argv[3] if len(sys.argv) > 3 else ""
    author = sys.argv[4] if len(sys.argv) > 4 else "Anonymous"
    
    asyncio.run(automate_book_upload(pdf_path, title, subtitle, author))
