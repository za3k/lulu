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

from dotenv import load_dotenv
from IPython.terminal.embed import InteractiveShellEmbed
from pathlib import Path
from pathlib import Path
from playwright.async_api import async_playwright
from PyPDF2 import PdfReader
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.units import inch, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from urllib.parse import urlparse
import argparse
import asyncio
import code
import json
import nest_asyncio
import os
import sys
import time
import time
import traceback

load_dotenv()

# Conversion factor: millimeters to points (1 point = 1/72 inch = 25.4/72 mm)
MM_TO_POINTS = 2.83465

START_URL = "https://www.lulu.com/account/wizard/draft/start"
PROJECT_ID_FILE = Path(".lulu_project_counter.txt")

# Login credentials from environment variables
LULU_USERNAME = os.environ.get("LULU_USERNAME", "")
LULU_PASSWORD = os.environ.get("LULU_PASSWORD", "")
cost_text = None

BOOK_SIZES = {
    ("Pocket Book", 108, 175),
    ("Novella", 127, 203),
    ("Digest", 140, 216),
    ("A5", 148, 210),
    ("US Trade", 152, 229),
    ("Royal", 156, 234),
    ("Executive", 178, 254),
    ("Crown Quarto", 189, 246),
    ("Small Square", 190, 190),
    ("A4", 210, 297),
    ("Square", 216, 216),
    ("US Letter", 216, 279),
    ("Small Landscape", 229, 179),
    ("US Letter Landscape", 279, 216),
    ("A4 Landscape", 297, 210),
}
# Pages: 2-800 in general, varies by binding type
BINDINGS = ("Paperback Perfect Bound", "Paperback Coil Bound", "Paperback Saddle Stitch", "Hardcover Case Wrap", "Hardcover Linen Wrap")
COLOR = ("Standard Black & White", "Premium Black & White", "Standard Color", "Premium Color")
PAPER_TYPES = ("60# Uncoated Cream", "60# Uncoated White", "80# Coated White")
COVER_FINISH = ("Glossy", "Matte")

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

async def wait_for_any(page, conditions, poll_interval_ms=500, timeout_ms=5000):
    """
    Wait for any of multiple conditions to be true.
    
    Args:
        page: Playwright page object
        conditions: List of (selector, description) tuples to check
        poll_interval_ms: How often to check (milliseconds)
        timeout_ms: Overall timeout in milliseconds
    
    Returns:
        Description string of the condition that was met, or None if timeout
    
    Example:
        result = await wait_for_any(page, [
            ("text=Success", "success"),
            ("text=Error", "error"),
            ("button=Retry", "retry")
        ], timeout_ms=10000)
        if result == "success":
            print("Success!")
        elif result == "error":
            print("Error occurred")
    """
    iterations = timeout_ms // poll_interval_ms
    
    for i in range(iterations):
        for idx, (selector, description) in enumerate(conditions):
            if await check_for_selector(page, selector, timeout=100):
                return description
        await page.wait_for_timeout(poll_interval_ms)
    
    return None

async def check_for_text(page, text, timeout=30000):
    """Wait for text to appear on the page."""
    try:
        await wait_for_text(page, text, timeout)
        return True
    except:
        return False

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
        #print(f"Waited {int(elapsed*1000)}/{timeout}ms")
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
    await page.wait_for_timeout(500)
    
    # Trigger change event to make sure UI updates
    await page.evaluate("(input) => { input.dispatchEvent(new Event('change', { bubbles: true })); }", file_input)
    
    print(f"✓ Uploaded {description}")


async def wait_for_captcha(page, text):
    dots = 0
    print(f"Waiting for: {repr(text)}")
    while not await check_for_text(page, text, 1000):
        # Check if CAPTCHA is present, wait for user to solve it if so.
        if dots == 0:
            print("Please complete CAPTCHA/login manually", end='', file=sys.stderr)
        print(".", end='', file=sys.stderr) 
        dots += 1
        sys.stderr.flush()
    if dots > 0:
        print(file=sys.stderr)

async def ensure_logged_in(page):
    """
    Ensure user is logged in. Automates login if needed.
    Returns True if logged in successfully.
    """
    print("Checking login status...")
    await page.goto(START_URL)
    
    dots = 0
    while True:
        if await check_for_selector(page, "text=Select a Product Type", timeout=1000):
            print("✓ Already logged in")
            return True
        elif await check_for_selector(page, "input[name=username]", timeout=100):
            print("❌ Not logged in. Attempting automated login...")
            return await do_login(page)
        else:
            # Check if CAPTCHA is present, wait for user to solve it if so.
            if dots == 0:
                print("Please complete CAPTCHA/login manually", end='', file=sys.stderr)
            print(".", end='', file=sys.stderr) 
            dots += 1
            sys.stderr.flush()
    if dots > 0:
        print(file=sys.stderr)
    
async def do_login(page):
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


async def create_book_page2(page, pdf_path, cover_path, binding="Unknown Binding Type"):
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
    await page.wait_for_timeout(2000)
    print("✓ Page loaded, starting upload...")
    
    await upload_file(page, pdf_path, "pdf book")
    
    # Wait for upload flow to start OR detect immediate failure
    print("⏳ Waiting for upload to start...")
    result = await wait_for_any(page, [
        ("text=Your file is uploading", "upload_started"),
    ], timeout_ms=5000)
    
    match result:
        case "upload_started":
            print("✓ Upload started")
            print("⏳ Waiting for button to disappear")
            await page.locator("[data-testid='interior-file-upload-button']").wait_for(state='hidden')
            await page.wait_for_timeout(200)
        case None:
            print("⚠️  Upload status unclear after 5 seconds")
            return False
        case _:
            assert False, f"Unexpected result from wait_for_any: {result}"
    
    # Wait for validation to start
    print("⏳ Waiting for validation...")
    result = await wait_for_any(page, [
        ("text=Your file is validating", "upload_validating"),
        ("[data-testid='interior-file-upload-button']", "reset")
    ], timeout_ms=5000)
    match result:
        case "upload_validating":
            print("✓ Validation started")
        case "reset":
            print("⚠️  Upload lost, page reverted to upload button")
            buttons = await page.query_selector_all("text=Upload your PDF file")
            for i, btn in enumerate(buttons):
                visible = await btn.is_visible()
                print(f"Button {i}: visible={visible}; {btn}")
            return "RETRY"
        case None:
            print("⚠️  Upload status unclear after 5 seconds")
        case _:
            assert False, f"Unexpected result from wait_for_any: {result}"
    
    # Wait for final result - success or error
    print("⏳ Waiting for validation result...")
    result = await wait_for_any(page, [
        ("text=Your Book file was successfully uploaded!", "success"),
        ("[data-testid*='file-upload-notification-error']", "error"),
        ("[data-testid='interior-file-upload-button']", "reset")
    ], timeout_ms=120000)
    
    match result:
        case "success":
            print("✓ PDF validated successfully")
        case "error":
            print("❌ Page 2 failed - PDF upload error")
            return False
        case "reset":
            print("⚠️  Upload lost, page reverted to upload button")
            return "RETRY"
        case None:
            print("⚠️  Page 2 status unclear - check manually")
            return False
        case _:
            assert False, f"Unexpected validation result: {result}"
    
    # Extract page count from the page (should match our PDF info)
    page_count_input = await page.query_selector("input[id='page-count']")
    if page_count_input:
        num_pages_str = await page_count_input.get_attribute("value")
        num_pages = int(num_pages_str) if num_pages_str else pdf_info['page_count']
        print(f"📖 Page count from form: {num_pages}")
    else:
        num_pages = pdf_info['page_count']
        print(f"📖 Using PDF page count: {num_pages}")
    
    # Set global cost_text from the form (will be used in page 5)
    global cost_text
    print("📊 Setting up AJAX logging...")
    ajax_log_file = Path("lulu_ajax_requests.log")
    ajax_requests = []
    
    async def log_request(request):
        # Filter for lulu.com domain only
        if request.resource_type in ["xhr", "fetch"]:
            try:
                domain = urlparse(request.url).netloc
                if domain.endswith('lulu.com'):
                    req_data = {
                        'url': request.url,
                        'method': request.method,
                        'post_data': None,
                        'response': None
                    }
                    
                    # Try to get POST data, handle binary data gracefully
                    try:
                        req_data['post_data'] = request.post_data
                    except:
                        req_data['post_data'] = "<binary or non-UTF8 data>"
                    
                    ajax_requests.append(req_data)
            except:
                pass
    
    async def log_response(response):
        # Filter for lulu.com domain only
        try:
            domain = urlparse(response.url).netloc
            if response.request.resource_type in ["xhr", "fetch"] and domain.endswith('lulu.com'):
                # Find the matching request
                for req in ajax_requests:
                    if req['url'] == response.url and req['response'] is None:
                        try:
                            req['response'] = await response.text()
                        except Exception as e:
                            req['response'] = f"<error reading response: {e}>"
                        break
        except:
            pass
    
    page.on("request", log_request)
    page.on("response", log_response)
    
    # Interior Color
    await select_radio(page, "Standard Black & White")
    
    # Paper Type
    await select_radio(page, "60# White")

    # Binding Type - choose based on page count
    await select_radio(page, binding)

    # Cover Finish (this is the last selection before price)
    await select_radio(page, "Glossy")

    # Wait for print cost to appear with actual value (not $0.00)
    await wait_for_text(page, "Print Cost", timeout=10000)
    
    # Wait for actual price to load (it starts as $0.00)
    print("⏳ Waiting for price to calculate...")
    global cost_text
    for attempt in range(30):  # Wait up to 30 seconds
        await page.wait_for_timeout(1000)
        cost_elem = await page.query_selector("[data-testid='print-cost']")
        if cost_elem:
            cost_text = await cost_elem.inner_text()
            if cost_text and cost_text.strip() != "$0.00":
                print(f"💰 Print Cost: {cost_text}")
                break
    else:
        print("⚠️  Price still showing $0.00 after 30 seconds")
    
    # Give responses time to complete
    await page.wait_for_timeout(1000)
    
    # Write AJAX requests to file
    with open(ajax_log_file, 'w') as f:
        f.write(f"AJAX Requests Log - {len(ajax_requests)} requests captured\n")
        f.write("=" * 80 + "\n\n")
        for i, req in enumerate(ajax_requests):
            f.write(f"Request {i+1}:\n")
            f.write(f"  URL: {req['url']}\n")
            f.write(f"  Method: {req['method']}\n")
            if req['post_data']:
                f.write(f"  POST Data: {req['post_data']}\n")
            if req['response']:
                f.write(f"  Response: {req['response']}\n")
            else:
                f.write(f"  Response: <no response captured>\n")
            f.write("\n" + "-" * 80 + "\n\n")
    
    print(f"📝 Logged {len(ajax_requests)} AJAX requests to {ajax_log_file}")

    # Select "Upload Your Cover"
    await select_radio(page, "Upload Your Cover")
    
    # Save reference to the first file input (interior PDF)
    initial_file_inputs = await page.query_selector_all("input[type='file']")
    first_input = initial_file_inputs[0] if initial_file_inputs else None
    print(f"📍 Tracked first file input (interior)")
    
    # Wait for cover upload section to appear - look for a NEW file input
    print("⏳ Waiting for cover upload section to load...")
    cover_input = None
    for attempt in range(10):
        await page.wait_for_timeout(1000)
        file_inputs = await page.query_selector_all("input[type='file']")
        print(f"  Attempt {attempt+1}: Found {len(file_inputs)} file inputs")
        
        # Look for a file input that isn't the first one
        for inp in file_inputs:
            if first_input and inp != first_input:
                cover_input = inp
                print(f"✓ Found new file input (cover)")
                break
            elif not first_input and len(file_inputs) > 1:
                # If we lost reference to first input, just use second one
                cover_input = file_inputs[1]
                print(f"✓ Found second file input (cover)")
                break
        
        if cover_input:
            break
    
    if not cover_input:
        raise Exception("Cover file input did not appear after 10 seconds")
    
    # Upload cover
    print(f"📤 Uploading cover: {cover_path}")
    await cover_input.set_input_files(str(cover_path))
    await page.evaluate("(input) => { input.dispatchEvent(new Event('change', { bubbles: true })); }", cover_input)
    
    print("⏳ Waiting for cover to upload and validate...")
    # Wait for cover validation messages
    if await check_for_selector(page, "text=Your file is uploading", timeout=10000):
        print("✓ Cover upload started")
    
    if await check_for_selector(page, "text=Your file is normalizing", timeout=30000):
        print("✓ Cover validation started")
    
    # Wait for cover validation to complete
    result = await wait_for_any(page, [
        ("text=You successfully uploaded a cover file!", "success"),
        ("text=We found some fonts", "font_error")
    ], timeout_ms=120000)
    
    match result:
        case "success":
            print("✓ Cover validated successfully")
        case "font_error":
            print("❌ Cover validation failed - font embedding issue")
            return False
        case None:
            print("⚠️  Cover validation status unclear")
        case _:
            assert False, f"Unexpected cover validation result: {result}"

    # Wait for the preview to generate
    await wait_for_text(page, "Use this preview window to see how your Book will look.", timeout=10000)
    
    # Wait for user to review
    input("⏸️  Press Enter to continue after reviewing the book preview...")

    # Click "Review Book" to continue
    await click_button(page, "Review Book")
    
    print("✓ Page 2 complete")
    return True

async def create_book_page3(page):
    await click_button(page, "Confirm and Publish")

    print("✓ Page 3 complete")
    return True

async def create_book_page4(page):
    await click_button(page, "Add to Cart")

    print("✓ Page 4 complete")
    return True

async def create_book_page5(page):
    # Verify the total is what we expect
    print(f"Waiting for cart total to be: {cost_text}")
    print("This may need the user to delete old cart items.")
    lastMsg = None
    while True:
        cost_elem = await page.query_selector("[data-testid='subtotal-amount']")
        if cost_elem:
            cart_cost_text = await cost_elem.inner_text()
            if cart_cost_text == cost_text: break
            msg = f"💰 Cost: {repr(cart_cost_text)} (should be {repr(cost_text)})"
            if msg != lastMsg:
                print(msg)
                lastMsg = msg
        await page.wait_for_timeout(500)

    await click_button(page, "Checkout")

    print("✓ Page 5 complete")
    return True

async def create_book_page6(page):
    await wait_for_text(page, "Enter Your Shipping Address")

    await page.get_by_test_id('address-autocomplete-input').fill(os.environ.get("STREET_ADDRESS", ""))
    await fill_field(page, "First Name", os.environ.get("NAME_FIRST", ""))
    await fill_field(page, "Last Name", os.environ.get("NAME_LAST", ""))
    await fill_field(page, "Country", os.environ.get("COUNTRY", ""))
    await fill_field(page, "State", os.environ.get("STATE", ""))
    await fill_field(page, "City", os.environ.get("CITY", ""))
    await fill_field(page, "Postal Code", os.environ.get("ZIP", ""))
    await fill_field(page, "Phone Number", os.environ.get("PHONE", ""))

    await click_button(page, "Choose Delivery Method")

    print("✓ Page 6 complete")
    return True

async def create_book_page7(page):
    await wait_for_text(page, "Choose Your Delivery Method")

    # Use standard mail -- they have to take a long time for the first book anyway.
    await page.click("[data-testid='shipping-option']:has-text('Mail')")

    await click_button(page, "Continue to Payment")
    print("✓ Page 7 complete")
    return True

async def create_book_page8(page):
    total_cost = await page.get_by_test_id("total-amount").text_content()
    print(f"Total cost will be: {total_cost}")
    input("Press ENTER to confirm, Ctrl-C to cancel")

    # Shipping address is billing address

    await click_button(page, "Choose Payment Method")
    
    print("✓ Page 8 complete")
    return True

async def create_book_page9(page):
    await wait_for_text(page, "Choose Your Payment Method")

    await page.get_by_label("accordionToggle").click()

    payment = page.get_by_title("IFrame for card Number").content_frame
    exp_frame = page.get_by_title("Iframe for expiry date").content_frame
    sec_frame = page.get_by_title("Iframe for security code").content_frame

    await payment.get_by_label("Card number").fill(os.environ.get("CC_NUM", ""))
    await payment.locator("input[name='cc-name']").fill(os.environ.get("CC_NAME", ""))
    await sec_frame.get_by_label("Security code").fill(os.environ.get("CC_CVV", ""))
    await exp_frame.get_by_label("Expiry date").fill(os.environ.get("CC_EXP", ""))

    a = input("Press Y to really, definitely buy this")
    while a.strip() not in "yYnN":
        a = input("Press Y to really, definitely buy this")

    if a.strip() in "yY":
        await click_button(page, "Pay Now with Credit Card")

        print("✓ Page 9 complete")
        return True
    elif a.strip() in "nN":
        return False

async def create_book_page10(page)
    await wait_for_text(page, "Thanks for ordering")
    how_long = await page.get_by_test_id("shipping-method-delivery-time").text_content()
    print(f"How long it will be: {how_long}")
    print("✓ Page 10 complete")

def open_repl(page, message="Manual continuation"):
    """Open an interactive REPL with page and all helpers available."""
    print(f"⏸️  {message}...")
    print("\n🐍 Entering Python REPL. Variables available:")
    print("   page, asyncio, and all helper functions")
    print("   Use 'await' for async functions (e.g., await fill_field(page, 'name', 'value'))")
    print("   Type 'exit()' or Ctrl+D to exit REPL and close browser\n")
    
    # Use globals() and add page/asyncio
    repl_locals = globals().copy()
    repl_locals['page'] = page
    repl_locals['asyncio'] = asyncio
    
    # Try IPython first for better experience (tab completion, await support)
    try:
        # Allow nested event loops (needed since we're already in async context)
        nest_asyncio.apply()
        
        print("✓ Using IPython (tab completion enabled)")
        ipshell = InteractiveShellEmbed(user_ns=repl_locals)
        # Enable top-level await
        ipshell.autoawait = True
        ipshell()
    except ImportError as e:
        # Fall back to standard REPL
        print("→ Using standard REPL")
        print("   (install 'ipython' and 'nest-asyncio' for better experience)")
        print("   To run async: asyncio.create_task(your_async_function())")
        code.interact(local=repl_locals)
    except Exception as e:
        print(f"⚠️  IPython failed ({e}), using standard REPL")
        code.interact(local=repl_locals)

async def process_pages_1_to_4(page, pdf_path, cover_path, binding):
    """
    Process pages 1-4 of the book creation flow.
    
    Returns True if successful, False otherwise.
    Returns "RETRY" if upload failed and should retry entire process.
    """
    await create_book_page1(page)
    result = await create_book_page2(page, pdf_path, cover_path, binding)
    if result == "RETRY":
        return "RETRY"
    elif not result:
        return False
    await create_book_page3(page)
    await create_book_page4(page)
    return True

async def process_page_5_onwards(page):
    """
    Process page 5 onwards (cart and checkout).
    
    Returns True if successful, False otherwise.
    """
    try:
        await wait_for_captcha(page, "Your Cart")
        if not await create_book_page5(page):
            return False

        if not await create_book_page6(page):
            return False

        if not await create_book_page7(page):
            return False
        
        if not await create_book_page8(page):
            return False

        if not await create_book_page9(page):
            return False

        if not await create_book_page10(page):
            return False
    except Exception as e:
        print(f"\n❌ Exception occurred: {e}")
        import traceback
        traceback.print_exc()
        print("\nOpening REPL for debugging...")
        open_repl(page, "Error occurred - opening REPL for debugging")
        return False
    
    # Success - open REPL for manual continuation
    #open_repl(page, "Pausing for manual continuation")
    return True

def get_spine_width(page_count, binding):
    """
    Get spine width in mm for hardcover based on page count.
    Returns None if hardcover not available (< 24 pages).
    
    Based on Lulu's hardcover spine width table.
    """
    spine_table = [
        (2, 23, 0),
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
    
    return None


def generate_cover_pdf(output_path, title, subtitle, author, front_width_mm, front_height_mm, num_pages, binding):
    """
    Generate a wraparound cover PDF for hardcover or paperback.
    
    For hardcover: printed 0.75" larger than trim size, wrapped around board.
    For paperback: includes 0.125" (3.175mm) bleed on all outer edges.
    
    Args:
        output_path: Where to save the cover PDF
        title: Book title
        subtitle: Book subtitle  
        author: Author name
        front_width_mm: Front cover width (trim size)
        front_height_mm: Front cover height (trim size)
        TODO: add 2 params
    """

    spine_width_mm = get_spine_width(num_pages, binding)
    assert spine_width_mm is not None, f"Invalid number of pages {num_pages} for binding '{binding}'"
    print(f"📏 Spine width for {num_pages} pages: {spine_width_mm}mm")
        
    if binding == "Hardcover Case Wrap":
        # Hardcover specifications per Lulu documentation:
        # - 0.75" (19.05mm) wrap on top, bottom, and outer (right) edges
        # - NO wrap on spine-side (left) edges - those are glued to the book
        # - 0.125" (3.175mm) overhang that wraps around, adding to total dimensions
        wrap_mm = 19.05  # 0.75 inches
        overhang_mm = 3.175 # 0.125" inches
        
        # Each panel: outer_edge_wrap + trim_width (no wrap on spine side)
        panel_width_mm = wrap_mm + front_width_mm
        
        # Total width: back_panel + spine + front_panel + overhang
        total_width_mm = panel_width_mm + spine_width_mm + panel_width_mm + (2 * overhang_mm)
        
        # Total height: trim + top_wrap + bottom_wrap + overhang  
        total_height_mm = front_height_mm + (2 * wrap_mm) + (2 * overhang_mm)
    elif binding == "Paperback Saddle Stitch":
        # Paperback has 0.125" (3.175mm) bleed on outer edges
        bleed_mm = 3.175
        
        # Calculate dimensions
        # Width: bleed + back + spine + front + bleed
        total_width_mm = bleed_mm + front_width_mm + spine_width_mm + front_width_mm + bleed_mm
        # Height: bleed + height + bleed
        total_height_mm = bleed_mm + front_height_mm + bleed_mm
    else:
        assert False, f"Don't know how to calculte cover size for: {binding}" 
    
    print(f"📐 Cover dimensions ({binding}): {total_width_mm:.1f}mm x {total_height_mm:.1f}mm")
    print(f"   Interior: {front_width_mm:.1f}mm x {front_height_mm:.1f}mm")
    print(f"   Spine: {spine_width_mm}mm")
    
    # Convert to points for ReportLab
    total_width_pts = total_width_mm * MM_TO_POINTS
    total_height_pts = total_height_mm * MM_TO_POINTS
    
    # Create PDF with embedded fonts
    c = canvas.Canvas(str(output_path), pagesize=(total_width_pts, total_height_pts))
    
    # Use TrueType fonts which will be embedded
    
    # Try multiple common font locations
    font_paths = [
        ('/usr/share/fonts/TTF/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'),
    ]
    
    title_font = None
    body_font = None
    
    for regular_path, bold_path in font_paths:
        try:
            if Path(regular_path).exists() and Path(bold_path).exists():
                pdfmetrics.registerFont(TTFont('DejaVuSans', regular_path))
                pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', bold_path))
                title_font = 'DejaVuSans-Bold'
                body_font = 'DejaVuSans'
                print(f"  Using DejaVu fonts from {regular_path} (will be embedded)")
                break
        except:
            continue
    
    if not title_font:
        raise Exception("DejaVuSans font not found -- unable to embed PDF fonts for Lulu")
    
    # Set background to white
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, total_width_pts, total_height_pts, fill=True, stroke=False)
    
    # Calculate positions (in points)
    if binding == "Hardcover Case Wrap":
        # Layout: [overhang][back_panel][spine][front_panel][overhang]
        # Overhang is split on left and right outer edges
        # Spine starts after: overhang + back_panel
        spine_start_x = (overhang_mm + panel_width_mm) * MM_TO_POINTS
        # Front starts after: overhang + back_panel + spine
        front_start_x = (overhang_mm + panel_width_mm + spine_width_mm) * MM_TO_POINTS
        front_center_x = front_start_x + (panel_width_mm * MM_TO_POINTS / 2)
    else:
        # For paperback: bleed + back + spine
        front_start_x = (bleed_mm + front_width_mm + spine_width_mm) * MM_TO_POINTS
        spine_start_x = (bleed_mm + front_width_mm) * MM_TO_POINTS
        front_center_x = front_start_x + (front_width_mm * MM_TO_POINTS / 2)
    
    # Front cover text
    c.setFillColorRGB(0, 0, 0)
    
    # Title on front (large, centered)
    c.setFont(title_font, 36)
    c.drawCentredString(front_center_x, total_height_pts * 0.6, title)
    
    # Subtitle on front (medium)
    if subtitle:
        c.setFont(body_font, 24)
        c.drawCentredString(front_center_x, total_height_pts * 0.5, subtitle)
    
    # Author on front (bottom)
    c.setFont(body_font, 18)
    c.drawCentredString(front_center_x, total_height_pts * 0.2, author)
    
    # Spine text (vertical, centered) - only if spine is wide enough
    if spine_width_mm >= 6:
        spine_center_x = spine_start_x + (spine_width_mm * MM_TO_POINTS / 2)
        
        c.saveState()
        c.translate(spine_center_x, total_height_pts / 2)
        c.rotate(90)
        
        c.setFont(title_font, 14)
        if subtitle:
            spine_text = f"{title}  —  {subtitle}"
        else:
            spine_text = f"{title}"
        # Draw text with vertical offset - after rotation, y=0 is the baseline. Just a rough guess.
        c.drawCentredString(0, -13/3, spine_text)
        
        c.restoreState()
    
    # Back cover is blank (as requested)
    
    # Save with embedded fonts
    c.save()
    print(f"✓ Generated cover PDF with embedded fonts: {output_path}")


async def automate_book_upload(pdf_path=None, title="Untitled Book", subtitle="", author="Anonymous", cart_mode=False, cart_cost=None):
    """
    Full automation: upload a book to Lulu.
    Handles login automatically if needed.
    
    Args:
        pdf_path: Path to PDF file to upload. Required for pages 1-4.
        title: Book title
        subtitle: Book subtitle (optional)
        author: Author name
        cart_mode: If True, skip pages 1-4 and go straight to cart
        cart_cost: Expected cart cost (e.g., "4.00 USD")
    """
    global cost_text
    
    if cart_mode:
        if not cart_cost:
            print("❌ Error: --cart requires a cost value")
            return False
        # Format cost to Lulu's format with USD suffix (e.g., "4.50 USD")
        cost_value = float(cart_cost.replace(" USD", "").strip())
        cost_text = f"{cost_value:.2f} USD"
        print(f"💰 Cart mode: expecting total of {cost_text}")
    else:
        if not pdf_path:
            print("❌ Error: pdf_path is required")
            return False
        
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            print(f"❌ Error: PDF file not found: {pdf_path}")
            return False
        
        # Get PDF info and generate cover upfront, before any browser interaction
        print("📄 Analyzing PDF...")
        pdf_info = get_pdf_info(pdf_path)
        print(f"📊 PDF Info: {pdf_info['page_count']} pages, {pdf_info['width_mm']:.1f}mm x {pdf_info['height_mm']:.1f}mm")
        
        num_pages = pdf_info['page_count']
        if num_pages > 23:
            binding = "Hardcover Case Wrap"
        else:
            binding = "Paperback Saddle Stitch"

        
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
            num_pages = num_pages,
            binding = binding,
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
        if not await ensure_logged_in(page):
            print("❌ Failed to log in")
            await context.close()
            return False
        
        if cart_mode:
            # Navigate directly to cart
            print("🛒 Navigating to cart...")
            await page.goto("https://www.lulu.com/cart")
            await page.wait_for_timeout(2000)
        else:
            # Process pages 1-4
            result = await process_pages_1_to_4(page, pdf_path, cover_path, binding)
            if result == "RETRY":
                await context.close()
                return "RETRY"  # Signal to retry entire process
            elif not result:
                print("❌ Failed during pages 1-4")
                await context.close()
                return False
        
        # Process page 5 onwards
        if not await process_page_5_onwards(page):
            print("❌ Failed during page 5+")
            await context.close()
            return False
        
        await context.close()
        return True


if __name__ == "__main__":
    
    parser = argparse.ArgumentParser(description='Automate Lulu.com book upload')
    parser.add_argument('pdf_path', nargs='?', help='Path to PDF file to upload (not needed with --cart)')
    parser.add_argument('title', nargs='?', default='Untitled Book', help='Book title')
    parser.add_argument('subtitle', nargs='?', default='', help='Book subtitle')
    parser.add_argument('author', nargs='?', default='Anonymous', help='Author name')
    parser.add_argument('--cart', type=str, metavar='COST', help='Skip to cart mode with expected cost (e.g., "4.00 USD")')
    
    args = parser.parse_args()
    
    cart_mode = args.cart is not None
    
    if not cart_mode and not args.pdf_path:
        parser.error("pdf_path is required unless using --cart")
    
    # Retry logic - only retry on "RETRY" signal (upload failures)
    max_retries = 3
    for attempt in range(max_retries):
        if attempt > 0:
            print(f"\n🔄 Retry attempt {attempt + 1}/{max_retries}")
        
        try:
            result = asyncio.run(automate_book_upload(
                args.pdf_path,
                args.title,
                args.subtitle,
                args.author,
                cart_mode=cart_mode,
                cart_cost=args.cart
            ))
            
            if result == "RETRY":
                print(f"⚠️  Upload failed, retrying entire process (attempt {attempt + 1}/{max_retries})")
                print("   Retrying...")
                continue
            elif result:
                print("✅ Process completed successfully")
                sys.exit(0)
            else:
                print("❌ Process failed")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ Exception occurred: {e}")
            traceback.print_exc()
            sys.exit(1)
    
    print(f"❌ Failed after {max_retries} retry attempts")
    sys.exit(1)

