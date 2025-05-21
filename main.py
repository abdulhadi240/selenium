from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import os, time, glob, shutil

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
    n8n_form_url: str
    run_id: str  # added

# ========== Download Helper ==========

def wait_for_download(download_dir, timeout=60):
    print("⏳ Waiting for file download and release...")
    end_time = time.time() + timeout

    while time.time() < end_time:
        files = glob.glob(os.path.join(download_dir, "*"))
        valid_files = [
            f for f in files
            if not f.endswith(".crdownload") and not f.endswith(".tmp") and os.path.isfile(f)
        ]

        if valid_files:
            latest_file = max(valid_files, key=os.path.getctime)
            try:
                size1 = os.path.getsize(latest_file)
                time.sleep(2)
                size2 = os.path.getsize(latest_file)
                if size1 == size2:
                    with open(latest_file, "rb"):
                        print("✅ File is stable and unlocked:", latest_file)
                        return os.path.abspath(latest_file)
            except (PermissionError, OSError):
                pass

        time.sleep(1)

    raise TimeoutError("⛔ File did not fully download or unlock in time.")

# ========== Endpoint 1: Scrape ==========

@app.post("/run_scrape/")
def run_scrape(data: ScrapeRequest):
    try:
        options = Options()
        options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--start-maximized")
        driver = webdriver.Chrome(service=Service(), options=options)
        wait = WebDriverWait(driver, 50)

        driver.get("https://www.vayne.io/users/sign_in")
        wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        driver.find_element(By.ID, "user_email").send_keys(data.email)
        driver.find_element(By.ID, "user_password").send_keys(data.password + Keys.RETURN)

        driver.get("https://www.vayne.io/linkedin_authentication/edit")
        token_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text']")))
        token_input.clear()
        token_input.send_keys(data.auth_token)
        update_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[normalize-space(text())='Update']")))
        driver.execute_script("arguments[0].click();", update_button)

        driver.get("https://www.vayne.io/url_checks/new")
        url_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "textarea[name='url_check[url]']")))
        url_input.clear()
        url_input.send_keys(data.linkedin_url)
        check_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@data-action='order-creation#checkUrl']")))
        driver.execute_script("arguments[0].click();", check_button)
        time.sleep(10)

        # Set the number of leads in the input field
        limit_input = wait.until(EC.presence_of_element_located((By.ID, "order_limit")))
        limit_input.clear()
        limit_input.send_keys(data.number)
        print("🔢 Number of leads set to:", data.number)

        # Optional: small wait to ensure the input is registered before clicking 'Create Order'
        time.sleep(10)

        create_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and @value='Create Order']")))
        driver.execute_script("arguments[0].click();", create_button)
        time.sleep(15)

        driver.get("https://www.vayne.io/orders")
        orders_container = wait.until(EC.presence_of_element_located((By.ID, "orders")))
        latest_order_div = orders_container.find_element(By.CSS_SELECTOR, "div.col-span-1")
        latest_order_id = latest_order_div.get_attribute("id")
        order_id = latest_order_id.split("_")[-1]
        csv_url = f"https://www.vayne.io/orders/{order_id}/download_export"

        driver.quit()
        return {
            "status": "success",
            "order_id": order_id,
            "csv_url": csv_url
        }

    except Exception as e:
        driver.quit()
        raise HTTPException(status_code=500, detail=str(e))

# ========== Endpoint 2: Upload ==========

@app.post("/upload_to_n8n/")
def upload_to_n8n(data: UploadRequest):
    BASE_DIR = os.getcwd()
    DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
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
        driver.get("https://www.vayne.io/users/sign_in")
        wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        driver.find_element(By.ID, "user_email").send_keys(data.email)
        driver.find_element(By.ID, "user_password").send_keys(data.password + Keys.RETURN)
        time.sleep(13)

        driver.get(data.download_link)
        downloaded_file = wait_for_download(DOWNLOAD_DIR)
        time.sleep(150)

        tmp_copy_path = os.path.join(DOWNLOAD_DIR, f"copy_{os.path.basename(downloaded_file)}")
        shutil.copy2(downloaded_file, tmp_copy_path)

        safe_path = os.path.normpath(tmp_copy_path)
        print("📁 Using safe path:", repr(safe_path))

        time.sleep(50)
        driver.get(data.n8n_form_url)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
        file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")

        # Show file input if hidden
        driver.execute_script("arguments[0].style.display = 'block';", file_input)
        time.sleep(50)

        # Upload file
        file_input.send_keys(safe_path)
        print("📁 Uploading file:", safe_path)
        time.sleep(50)

        # Fill Run ID
        run_id_input = driver.find_element(By.CSS_SELECTOR, "input[name='field-1']")
        run_id_input.clear()
        run_id_input.send_keys(data.run_id)
        print("🔢 Run ID added:", data.run_id)
        time.sleep(50)

        # Submit form
        submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
        submit_button.click()
        print("✅ File and Run ID submitted.")
        time.sleep(150)

        return {
            "status": "success",
            "message": "File and Run ID submitted successfully to N8N form."
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

    finally:
        driver.quit()
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
