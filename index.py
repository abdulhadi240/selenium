import os
import time
import glob
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== CONFIG ==========
EMAIL = "tools@chitlangia.co"
PASSWORD = "1#Optimize"
N8N_FORM_URL = "https://leadassist.chitlangia.co/form/90056fae-4218-4b2a-a8eb-20a5fb539d35"  # ✅ Replace with your actual N8N form URL

# Set up download directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ========== FUNCTION: Wait for Download ==========
def wait_for_download(download_dir, timeout=60):
    """
    Waits for a non-temporary file to appear in the download directory.
    """
    print("⏳ Waiting for file download...")
    end_time = time.time() + timeout

    while time.time() < end_time:
        files = glob.glob(os.path.join(download_dir, "*"))

        valid_files = [
            f for f in files
            if not f.endswith(".crdownload") and not f.endswith(".tmp") and os.path.isfile(f)
        ]

        if valid_files:
            latest_file = max(valid_files, key=os.path.getctime)
            print("✅ Download complete:", latest_file)
            return os.path.abspath(latest_file)

        time.sleep(1)

    raise TimeoutError("⛔ Download did not complete in expected time.")

# ========== SETUP SELENIUM ==========
options = Options()
options.add_argument("--start-maximized")
prefs = {
    "download.default_directory": DOWNLOAD_DIR,
    "download.prompt_for_download": False,
    "directory_upgrade": True,
    "safebrowsing.enabled": True
}
options.add_experimental_option("prefs", prefs)

driver = webdriver.Chrome(service=Service(), options=options)
wait = WebDriverWait(driver, 50)

try:
    # ========== STEP 1: LOGIN TO VAYNE ==========
    driver.get("https://www.vayne.io/users/sign_in")
    wait.until(EC.presence_of_element_located((By.ID, "user_email")))

    driver.find_element(By.ID, "user_email").send_keys(EMAIL)
    driver.find_element(By.ID, "user_password").send_keys(PASSWORD + Keys.RETURN)

    time.sleep(3)  # Let login settle

    # ========== STEP 2: DOWNLOAD FILE ==========
    driver.get("https://www.vayne.io/orders/20617/download_export")

    # ========== STEP 3: WAIT FOR DOWNLOAD ==========
    downloaded_file = wait_for_download(DOWNLOAD_DIR)
    time.sleep(2)  # Additional buffer to ensure file handle is released

    # ========== STEP 4: UPLOAD TO N8N FORM ==========
    driver.get(N8N_FORM_URL)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))

    print("📁 Uploading file:", downloaded_file)
    file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
    file_input.send_keys(downloaded_file)

    # Wait for file to attach (N8N might show a progress bar)
    time.sleep(2)

    submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
    submit_button.click()

    print("✅ File uploaded to N8N form.")

    os.remove(downloaded_file)
    print("🗑️ File deleted:", downloaded_file)

except Exception as e:
    print("❌ Error:", e)

finally:
    time.sleep(5)
    driver.quit()
