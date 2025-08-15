from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
import os, time, glob, shutil, logging, traceback
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# ========== Models ==========

class ScrapeRequest(BaseModel):
    email: str
    password: str
    auth_token: str
    linkedin_url: str
    number: str

class UploadRequest(BaseModel):
    email: str
    password: str
    download_link: str
    run_id: str

# ========== Download Helper ==========

def wait_for_download(download_dir, timeout=120):
    """Improved download detection with better file handling"""
    logger.info("⏳ Waiting for file download and release...")
    end_time = time.time() + timeout
    last_file_count = 0
    stable_count = 0

    while time.time() < end_time:
        try:
            # Get all files in download directory
            files = glob.glob(os.path.join(download_dir, "*"))
            
            # Filter out temporary files
            valid_files = [
                f for f in files
                if not f.endswith(".crdownload") 
                and not f.endswith(".tmp") 
                and not f.endswith(".part")
                and os.path.isfile(f)
                and os.path.getsize(f) > 0  # Ensure file has content
            ]

            current_file_count = len(valid_files)
            logger.info(f"📁 Files in download dir: {current_file_count} (valid), {len(files)} (total)")

            # Check if we have a new file
            if current_file_count > last_file_count:
                latest_file = max(valid_files, key=os.path.getctime)
                logger.info(f"📄 Found potential download: {os.path.basename(latest_file)}")
                
                # Check if file is stable (not being written to)
                try:
                    size1 = os.path.getsize(latest_file)
                    time.sleep(3)  # Wait a bit longer
                    size2 = os.path.getsize(latest_file)
                    
                    if size1 == size2 and size1 > 0:
                        # Try to open the file to ensure it's not locked
                        with open(latest_file, "rb") as test_file:
                            test_file.read(1024)  # Read a small chunk
                        
                        logger.info(f"✅ File is stable and unlocked: {latest_file} ({size2} bytes)")
                        return os.path.abspath(latest_file)
                    else:
                        logger.info(f"📝 File still being written: {size1} -> {size2} bytes")
                        
                except (PermissionError, OSError) as e:
                    logger.warning(f"⚠️ File access error: {e}")
                    
            elif current_file_count == last_file_count and current_file_count > 0:
                stable_count += 1
                if stable_count > 5:  # File count stable for 5 iterations
                    latest_file = max(valid_files, key=os.path.getctime)
                    if os.path.getsize(latest_file) > 0:
                        return os.path.abspath(latest_file)

            last_file_count = current_file_count
            time.sleep(2)  # Check every 2 seconds

        except Exception as e:
            logger.warning(f"⚠️ Error checking downloads: {e}")
            time.sleep(2)

    raise TimeoutError(f"⛔ File did not fully download or unlock in {timeout} seconds.")

# ========== Improved Chrome Setup ==========

def setup_chrome_driver(download_dir: Optional[str] = None):
    """Setup Chrome WebDriver with comprehensive error suppression"""
    try:
        options = Options()
        
        # Basic headless configuration
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        
        # Disable automation detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Disable unnecessary services that cause errors
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-features=TranslateUI")
        options.add_argument("--disable-ipc-flooding-protection")
        
        # Disable Google services and GCM
        options.add_argument("--disable-sync")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-component-update")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-domain-reliability")
        
        # Disable ML/AI features that cause TensorFlow errors
        options.add_argument("--disable-features=OptimizationHints")
        options.add_argument("--disable-features=VizDisplayCompositor")
        options.add_argument("--disable-features=TranslateBubbleUI")
        options.add_argument("--disable-machine-learning-service")
        options.add_argument("--disable-ml-service")
        
        # Disable logging and notifications
        options.add_argument("--disable-logging")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_argument("--disable-web-security")
        options.add_argument("--allow-running-insecure-content")
        
        # Performance improvements
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--start-maximized")
        
        # Set user agent to avoid detection
        options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # Suppress log levels to reduce console noise
        options.add_argument("--log-level=3")  # Only show fatal errors
        options.add_argument("--silent")
        
        # Set download preferences if download_dir is provided
        if download_dir:
            prefs = {
                "download.default_directory": download_dir,
                "download.prompt_for_download": False,
                "download.directory_upgrade": True,
                "safebrowsing.enabled": False,  # Disable safe browsing
                "safebrowsing.disable_download_protection": True,
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_settings.popups": 0,
                "profile.managed_default_content_settings.images": 2  # Don't load images
            }
            options.add_experimental_option("prefs", prefs)
        
        # Create service with reduced logging
        service = Service()
        service.log_level = 'OFF'  # Disable ChromeDriver logs
        
        # Initialize driver
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(45)
        
        # Execute script to remove webdriver property
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        logger.info("✅ Chrome WebDriver initialized successfully")
        return driver
        
    except WebDriverException as e:
        logger.error("❌ Failed to initialize Chrome WebDriver: %s", e)
        raise HTTPException(status_code=500, detail=f"WebDriver initialization failed: {str(e)}")
    except Exception as e:
        logger.error("❌ Unexpected error in WebDriver setup: %s", e)
        raise HTTPException(status_code=500, detail=f"Unexpected WebDriver error: {str(e)}")

# ========== Safe Element Interaction ==========

def safe_find_element(driver, wait, by, selector, timeout=15, description="element"):
    """Safely find an element with proper error handling"""
    try:
        logger.info(f"🔍 Looking for {description}: {selector}")
        element = wait.until(EC.presence_of_element_located((by, selector)))
        logger.info(f"✅ Found {description}")
        return element
    except TimeoutException:
        logger.error(f"❌ Timeout waiting for {description}: {selector}")
        # Take a screenshot for debugging if possible
        try:
            driver.save_screenshot(f"error_{description.replace(' ', '_')}.png")
            logger.info(f"📸 Screenshot saved for debugging: error_{description.replace(' ', '_')}.png")
        except:
            pass
        raise HTTPException(status_code=500, detail=f"Could not find {description} on page")
    except Exception as e:
        logger.error(f"❌ Error finding {description}: {e}")
        raise HTTPException(status_code=500, detail=f"Error locating {description}: {str(e)}")

def safe_click(driver, wait, element, description="element"):
    """Safely click an element with proper error handling"""
    try:
        logger.info(f"🖱️ Clicking {description}")
        # Scroll element into view first
        driver.execute_script("arguments[0].scrollIntoView(true);", element)
        time.sleep(1)
        
        # Wait for element to be clickable
        wait.until(EC.element_to_be_clickable(element))
        
        # Use JavaScript click for reliability
        driver.execute_script("arguments[0].click();", element)
        logger.info(f"✅ Clicked {description}")
        time.sleep(2)
    except Exception as e:
        logger.error(f"❌ Error clicking {description}: {e}")
        raise HTTPException(status_code=500, detail=f"Could not click {description}: {str(e)}")

# ========== Endpoint 1: Improved Scrape ==========

@app.post("/run_scrape/")
def run_scrape(data: ScrapeRequest):
    driver = None
    try:
        logger.info("🚀 Starting scrape process...")
        
        # Setup WebDriver
        driver = setup_chrome_driver()
        wait = WebDriverWait(driver, 30)

        # Step 1: Login to Vayne.io
        logger.info("🔐 Logging into Vayne.io...")
        driver.get("https://www.vayne.io/users/sign_in")
        
        email_input = safe_find_element(driver, wait, By.ID, "user_email", description="email input")
        password_input = safe_find_element(driver, wait, By.ID, "user_password", description="password input")
        
        email_input.clear()
        email_input.send_keys(data.email)
        password_input.clear()
        password_input.send_keys(data.password + Keys.RETURN)
        
        logger.info("✅ Login form submitted")
        time.sleep(5)

        # Step 2: Update LinkedIn authentication token
        logger.info("🔑 Updating LinkedIn authentication token...")
        driver.get("https://www.vayne.io/linkedin_authentication/edit")
        
        token_input = safe_find_element(driver, wait, By.CSS_SELECTOR, "input[type='text']", description="auth token input")
        token_input.clear()
        token_input.send_keys(data.auth_token)
        
        update_button = safe_find_element(driver, wait, By.XPATH, "//button[normalize-space(text())='Update']", description="update button")
        safe_click(driver, wait, update_button, "update button")
        
        logger.info("✅ Auth token updated")
        time.sleep(3)

        # Step 3: Create new URL check
        logger.info("🔗 Creating URL check...")
        driver.get("https://www.vayne.io/url_checks/new")
        
        url_input = safe_find_element(driver, wait, By.CSS_SELECTOR, "textarea[name='url_check[url]']", description="URL input")
        url_input.clear()
        url_input.send_keys(data.linkedin_url)
        
        check_button = safe_find_element(driver, wait, By.XPATH, "//a[@data-action='order-creation#checkUrl']", description="check URL button")
        safe_click(driver, wait, check_button, "check URL button")
        
        logger.info("✅ URL check initiated")
        time.sleep(10)

        # Step 4: Set number of leads
        logger.info(f"🔢 Setting number of leads to: {data.number}")
        limit_input = safe_find_element(driver, wait, By.ID, "order_limit", description="order limit input")
        limit_input.clear()
        limit_input.send_keys(data.number)
        
        logger.info(f"✅ Number of leads set to: {data.number}")
        time.sleep(5)

        # Step 5: Create order
        logger.info("📋 Creating order...")
        create_button = safe_find_element(driver, wait, By.XPATH, "//input[@type='submit' and @value='Create Order']", description="create order button")
        safe_click(driver, wait, create_button, "create order button")
        
        logger.info("✅ Order creation initiated")
        time.sleep(10)

        # Step 6: Get order ID from orders page
        logger.info("📄 Retrieving order details...")
        driver.get("https://www.vayne.io/orders")
        time.sleep(10)
        orders_container = safe_find_element(driver, wait, By.ID, "order_items_leads", description="orders container")
        latest_order_div = orders_container.find_element(By.CSS_SELECTOR, "li.col-span-1")
        latest_order_id = latest_order_div.get_attribute("id")
        
        if not latest_order_id:
            raise HTTPException(status_code=500, detail="Could not retrieve order ID")
            
        order_id = latest_order_id.split("_")[-1]
        csv_url = f"https://www.vayne.io/orders/{order_id}/download_export"
        
        logger.info(f"✅ Order created successfully with ID: {order_id}")
        
        return {
            "status": "success",
            "order_id": order_id,
            "csv_url": csv_url,
            "message": f"Scrape completed successfully. Order ID: {order_id}"
        }

    except HTTPException:
        raise
    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error("❌ Unexpected error in run_scrape: %s\nTraceback: %s", e, error_traceback)
        raise HTTPException(status_code=500, detail=f"Scraping failed: {str(e)}")
    finally:
        if driver:
            try:
                driver.quit()
                logger.info("🧹 WebDriver cleanup completed")
            except Exception as e:
                logger.warning("⚠️ Error during WebDriver cleanup: %s", e)

# ========== Endpoint 2: Simplified Download CSV ==========

@app.post("/download_csv/")
def download_csv(data: UploadRequest):
    """Downloads a CSV file and returns it as a file response"""
    # Use absolute path to ensure proper directory creation
    DOWNLOAD_DIR = r"C:\developer\Vayne\selenium\downloads"
    driver = None
    downloaded_file = None
    
    try:
        logger.info("📁 Starting CSV download process...")
        
        # Create download directory if it doesn't exist
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        # Clear any existing files in the download directory
        for existing_file in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                os.remove(existing_file)
                logger.info(f"🧹 Removed existing file: {os.path.basename(existing_file)}")
            except Exception as e:
                logger.warning(f"⚠️ Could not remove {existing_file}: {e}")

        # Setup Chrome with download preferences
        driver = setup_chrome_driver(download_dir=DOWNLOAD_DIR)
        wait = WebDriverWait(driver, 60)

        # Step 1: Login to Vayne.io (REQUIRED before download)
        logger.info("🔐 Logging into Vayne.io for download...")
        driver.get("https://www.vayne.io/users/sign_in")
        
        email_input = safe_find_element(driver, wait, By.ID, "user_email", description="email input")
        password_input = safe_find_element(driver, wait, By.ID, "user_password", description="password input")
        
        email_input.clear()
        email_input.send_keys(data.email)
        password_input.clear()
        password_input.send_keys(data.password + Keys.RETURN)
        
        logger.info("⏳ Waiting for login to complete...")
        time.sleep(8)

        # Step 2: Verify login success by checking URL change
        try:
            wait.until(lambda driver: "sign_in" not in driver.current_url)
            logger.info("✅ Login successful - redirected from sign_in page")
        except TimeoutException:
            logger.warning("⚠️ Login verification timeout - checking current URL")
            current_url = driver.current_url
            logger.info(f"Current URL: {current_url}")
            if "sign_in" in current_url:
                raise HTTPException(status_code=401, detail="Login failed - still on sign_in page")

        # Step 3: Navigate to download URL 
        logger.info(f"⬇️ Accessing download URL: {data.download_link}")
        driver.get(data.download_link)
        
        # Wait a moment for page/download to load
        time.sleep(5)
        
        # Step 4: Check if we got HTML (error page) instead of file download
        current_url = driver.current_url
        page_source = driver.page_source
        
        # If we're still on the same URL and have HTML content, it means no download occurred
        if current_url == data.download_link and len(page_source) > 1000:
            logger.warning("⚠️ Received HTML page instead of file download - file still processing")
            logger.info(f"Current URL: {current_url}")
            logger.info(f"Page source length: {len(page_source)} characters")
            
            # Check for specific error messages in the HTML
            html_lower = page_source.lower()
            error_message = "File is still being processed"
            
            if "something went wrong" in html_lower:
                error_message = "Server error - file may still be processing"
            elif "not found" in html_lower:
                error_message = "File not found - may not be generated yet"
            elif "error" in html_lower:
                error_message = "Server error encountered"
            
            return {
                "status": "processing",
                "message": "File is still being processed",
                "details": error_message,
                "suggestion": "Please wait a few minutes and try again",
                "run_id": data.run_id,
                "download_url": data.download_link,
                "response_type": "html"
            }
        
        # Step 5: If no HTML error page, check for actual file download
        logger.info("✅ No error page detected - checking for downloaded file...")
        
        try:
            # Wait for download to complete (shorter timeout since we already waited)
            downloaded_file = wait_for_download(DOWNLOAD_DIR, timeout=30)
            logger.info("✅ File download detected!")
            
        except TimeoutError:
            # No file was downloaded, but also no error page - might be a redirect or other issue
            logger.warning("⚠️ No file download detected and no clear error page")
            return {
                "status": "processing", 
                "message": "No file download occurred - likely still processing",
                "suggestion": "Please try again in a few minutes",
                "run_id": data.run_id,
                "download_url": data.download_link,
                "response_type": "no_download"
            }
        
        # Close driver early to free resources
        if driver:
            driver.quit()
            driver = None
            logger.info("🧹 WebDriver closed after download")

        # Step 6: Verify file exists and has content
        if not os.path.exists(downloaded_file):
            raise FileNotFoundError("Downloaded file not found")
            
        file_size = os.path.getsize(downloaded_file)
        if file_size == 0:
            raise ValueError("Downloaded file is empty")
            
        original_filename = os.path.basename(downloaded_file)
        new_filename = f"vayne_export_{data.run_id}.csv"
        
        logger.info(f"✅ CSV file downloaded successfully. Size: {file_size} bytes, Name: {original_filename}")
        
        # Step 7: Return the file as a response
        return FileResponse(
            path=downloaded_file,
            media_type='text/csv',
            filename=new_filename,
            headers={
                "Content-Disposition": f"attachment; filename={new_filename}",
                "X-Run-ID": data.run_id,
                "X-File-Size": str(file_size),
                "X-Original-Filename": original_filename,
                "X-Download-Status": "completed"
            }
        )

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error("❌ Error in download_csv: %s\nTraceback: %s", e, error_traceback)
        
        # Clean up the file if it was downloaded but an error occurred
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
                logger.info("🧹 Cleaned up downloaded file after error")
            except:
                pass
        
        raise HTTPException(status_code=500, detail=f"CSV download failed: {str(e)}")

    finally:
        # Cleanup WebDriver if still open
        if driver:
            try:
                driver.quit()
                logger.info("🧹 WebDriver cleanup completed")
            except Exception as e:
                logger.warning("⚠️ Error during WebDriver cleanup: %s", e)

# ========== Endpoint 3: Alternative - Return CSV content as text/csv ==========

@app.post("/download_csv_content/")
def download_csv_content(data: UploadRequest):
    """Alternative endpoint that downloads the CSV and returns its content"""
    DOWNLOAD_DIR = r"C:\developer\Vayne\selenium\downloads"
    driver = None
    
    try:
        logger.info("📁 Starting CSV download process...")
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)

        # Clear existing files
        for existing_file in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
            try:
                os.remove(existing_file)
            except:
                pass

        # Setup Chrome with download preferences
        driver = setup_chrome_driver(download_dir=DOWNLOAD_DIR)
        wait = WebDriverWait(driver, 60)

        # Login to Vayne.io
        logger.info("🔐 Logging into Vayne.io for download...")
        driver.get("https://www.vayne.io/users/sign_in")
        
        email_input = safe_find_element(driver, wait, By.ID, "user_email", description="email input")
        password_input = safe_find_element(driver, wait, By.ID, "user_password", description="password input")
        
        email_input.clear()
        email_input.send_keys(data.email)
        password_input.clear()
        password_input.send_keys(data.password + Keys.RETURN)
        time.sleep(8)

        # Download file by navigating to URL
        logger.info(f"⬇️ Downloading CSV file from: {data.download_link}")
        driver.get(data.download_link)
        time.sleep(3)
        
        downloaded_file = wait_for_download(DOWNLOAD_DIR, timeout=120)

        # Read the CSV file content
        logger.info("📄 Reading CSV file content...")
        with open(downloaded_file, 'r', encoding='utf-8') as file:
            csv_content = file.read()
        
        file_size = len(csv_content.encode('utf-8'))
        file_name = f"vayne_export_{data.run_id}.csv"
        
        logger.info(f"✅ CSV file read successfully. Size: {file_size} bytes")
        
        # Return CSV content with proper headers
        from fastapi.responses import Response
        return Response(
            content=csv_content,
            media_type='text/csv',
            headers={
                "Content-Disposition": f"attachment; filename={file_name}",
                "X-Run-ID": data.run_id,
                "X-File-Size": str(file_size)
            }
        )

    except Exception as e:
        error_traceback = traceback.format_exc()
        logger.error("❌ Error in download_csv_content: %s\nTraceback: %s", e, error_traceback)
        raise HTTPException(status_code=500, detail=f"CSV download failed: {str(e)}")

    finally:
        # Cleanup
        if driver:
            try:
                driver.quit()
                logger.info("🧹 WebDriver cleanup completed")
            except Exception as e:
                logger.warning("⚠️ Error during WebDriver cleanup: %s", e)
        
        # Clean up download directory
        try:
            for file in glob.glob(os.path.join(DOWNLOAD_DIR, "*")):
                os.remove(file)
            logger.info("🧹 Download directory cleanup completed")
        except Exception as e:
            logger.warning("⚠️ Error during directory cleanup: %s", e)

# ========== Cleanup Task for Old Downloads ==========

def cleanup_old_downloads(directory: str, max_age_hours: int = 1):
    """Clean up old downloaded files to prevent disk space issues"""
    if not os.path.exists(directory):
        return
    
    current_time = time.time()
    for item in os.listdir(directory):
        item_path = os.path.join(directory, item)
        if os.path.isfile(item_path):
            file_age_hours = (current_time - os.path.getctime(item_path)) / 3600
            if file_age_hours > max_age_hours:
                try:
                    os.remove(item_path)
                    logger.info(f"🧹 Cleaned up old file: {item}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete old file {item}: {e}")
        elif os.path.isdir(item_path):
            # Clean up old session directories
            dir_age_hours = (current_time - os.path.getctime(item_path)) / 3600
            if dir_age_hours > max_age_hours:
                try:
                    shutil.rmtree(item_path)
                    logger.info(f"🧹 Cleaned up old directory: {item}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not delete old directory {item}: {e}")

# ========== Health Check Endpoint ==========

@app.get("/health")
def health_check():
    return {"status": "healthy", "message": "FastAPI scraper is running"}

@app.get("/")
def root():
    return {
        "message": "Vayne.io Scraper API", 
        "endpoints": [
            "/run_scrape",
            "/download_csv (returns file)",
            "/download_csv_content (returns CSV with headers)",
            "/download_csv_direct (simplified direct download)",
            "/health"
        ]
    }
    return {
        "message": "Vayne.io Scraper API", 
        "endpoints": [
            "/run_scrape",
            "/download_csv (returns file)",
            "/download_csv_content (returns CSV with headers)",
            "/health"
        ]
    }

# ========== Startup Event ==========

@app.on_event("startup")
async def startup_event():
    """Clean up old downloads on startup"""
    DOWNLOAD_DIR = r"C:\developer\Vayne\selenium\downloads"
    cleanup_old_downloads(DOWNLOAD_DIR, max_age_hours=1)
    logger.info("🚀 FastAPI application started, old downloads cleaned")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)