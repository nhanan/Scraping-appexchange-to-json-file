from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from tqdm import tqdm
import concurrent.futures
from threading import Lock
import os, sys, json, time

sys.stdout.reconfigure(encoding='utf-8')

# Setup
NULL = None
final_list = []
lock = Lock()
service = ChromeService(executable_path=ChromeDriverManager().install())
print("Launching browser and opening AppExchange...")
driver = webdriver.Chrome(service=service)
driver.maximize_window()
driver.get("https://appexchange.salesforce.com/consulting")

# Accept cookies
WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))
).click()

# Filter country
print("Applying United States filter...")
select = Select(driver.find_element(By.ID, 'select_country'))
select.select_by_visible_text("United States")
apply_button = WebDriverWait(driver, 10).until(
    EC.element_to_be_clickable((By.ID, 'appx_btn_filter_apply'))
)
driver.execute_script("arguments[0].click();", apply_button)
time.sleep(10)

# Calculate number of consultants
total_links = int(int(driver.find_element(By.ID, 'total-items-store').text) / 28)
print(f"Loading all consultants ({total_links} 'See More' clicks)...")

for i in range(total_links + 1):
    success = False
    for attempt in range(3):
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)

            # Check presence first
            if not driver.find_elements(By.ID, 'appx-load-more-button-id'):
                break

            see_more = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'appx-load-more-button-id'))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", see_more)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", see_more)
            time.sleep(2)
            success = True
            break
        except Exception as e:
            print(f"Attempt {attempt + 1} failed to click 'See More': {e}")
            time.sleep(2)
    if not success:
        print("❌ Failed to click 'See More' after 3 attempts. Moving on...")


links = driver.find_elements(By.CLASS_NAME, 'appx-tile-consultant')
links_list = [link.get_attribute('href') for link in links]
driver.quit()

print(f"Collected {len(links_list)} consultant links.")

# Load partial file if exists
if os.path.exists("appex_partial.json") and os.path.getsize("appex_partial.json") > 0:
    try:
        with open("appex_partial.json", "r", encoding="utf-8") as f:
            final_list = json.load(f)
            print(f"Loaded {len(final_list)} previously scraped entries from 'appex_partial.json'")
    except json.JSONDecodeError:
        print("⚠️ 'appex_partial.json' is corrupted or empty. Starting fresh.")
        final_list = []
else:
    print("No partial file found or file is empty. Starting fresh.")
    final_list = []


scraped_links = {entry['Partner'] for entry in final_list if 'Partner' in entry}
links_list = [link for link in links_list if link not in scraped_links]
print(f"Remaining links to scrape: {len(links_list)}")

def get_expertise(driver):
    salesforce_expertise = []
    industry_expertise = []

    def get_table(xpath_id, result_list):
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, f'//ul[@id="{xpath_id}"]'))
            )
            entries = driver.find_elements(By.XPATH, f'//ul[@id="{xpath_id}"]/li')
            for entry in entries:
                try:
                    expertise = entry.get_attribute("psa-title") or ""
                    level = entry.get_attribute("psa-level") or ""
                    button = entry.find_element(By.XPATH, './/h3/button')
                    driver.execute_script("arguments[0].click();", button)
                    time.sleep(0.5)
                    try:
                        specializations = entry.find_element(By.XPATH, './/ul').text.splitlines()
                    except:
                        specializations = []
                    for spec in specializations:
                        result_list.append({
                            "Expertise": expertise,
                            "Specialization": spec,
                            "Level": level
                        })
                except Exception as e:
                    continue  # move on to next entry
        except Exception as e:
            tqdm.write(f"⚠️ Skipping missing or unloaded table '{xpath_id}': {e}")
            return

    get_table("appx_accordion_products", salesforce_expertise)
    get_table("appx_accordion_industry", industry_expertise)
    return salesforce_expertise, industry_expertise

def get_data_with_progress(link_idx_pair, pbar, total_len):
    idx, link = link_idx_pair
    start_time = time.time()

    print(f"\n[{idx + 1}/{total_len}] Scraping: {link}")

    # Create a new service per thread to avoid session issues
    local_service = ChromeService(executable_path=ChromeDriverManager().install())
    local_driver = webdriver.Chrome(service=local_service)
    local_driver.maximize_window()
    local_driver.get(link)

    try:
        WebDriverWait(local_driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'onetrust-accept-btn-handler'))
        ).click()
    except:
        pass

    dic1 = {}

    try:
        dic1['Partner'] = local_driver.find_element(By.ID, 'consulting-header-bar-title-id').text
    except:
        dic1['Partner'] = NULL

    try:
        WebDriverWait(local_driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "appx-extended-detail-subsection"))
        )
    except:
        tqdm.write(f"⚠️ Overview section not found on {link}")

    try:
        about_infos = local_driver.find_elements(By.CLASS_NAME, 'appx-extended-detail-subsection-label-description')
        for item in about_infos:
            try:
                label_elem = item.find_element(By.CLASS_NAME, "appx-extended-detail-subsection-label")
                value_elem = item.find_element(By.CLASS_NAME, "appx-extended-detail-subsection-description")
            except:
                continue

            label = label_elem.text.strip()
            if label == "Headquarters":
                dic1['Headquarters'] = value_elem.text.strip()
            elif label == "Website":
                try:
                    dic1['Website'] = value_elem.find_element(By.TAG_NAME, "a").get_attribute("href")
                except:
                    dic1['Website'] = value_elem.text.strip()
            elif label == "Email":
                try:
                    dic1['Email'] = value_elem.find_element(By.TAG_NAME, "a").get_attribute("href").replace("mailto:", "")
                except:
                    dic1['Email'] = value_elem.text.strip()
    except Exception as e:
        tqdm.write(f"⚠️ Failed to get full company details: {e}")
        dic1['Headquarters'] = dic1.get('Headquarters', NULL)
        dic1['Website'] = dic1.get('Website', NULL)
        dic1['Email'] = dic1.get('Email', NULL)

    try:
        about_section = local_driver.find_element(By.XPATH, '//span[@class="appx-tooltip-text"]/span[@class="appx-multi-line-to-fix appx-multi-line-fixed"]')
        dic1['About'] = about_section.get_attribute("innerText").replace('\u200b', '').strip()
    except:
        dic1['About'] = NULL

    try:
        labels = local_driver.find_elements(By.CLASS_NAME, "appx-summary-bar_facts-label")
        values = local_driver.find_elements(By.CLASS_NAME, "appx-summary-bar_facts-value")
        for i in range(len(labels)):
            label = labels[i].text.strip()
            value = values[i].text.strip()
            if label == "Projects Completed":
                dic1['Projects Completed'] = value
            elif label == "Certified Experts":
                dic1['Certified Experts'] = value
            elif label == "Founded":
                dic1['Founded'] = value
    except:
        dic1['Projects Completed'] = NULL
        dic1['Certified Experts'] = NULL
        dic1['Founded'] = NULL

    # Click the Expertise tab
    for attempt in range(3):
        try:
            try:
                expertise_tab = WebDriverWait(local_driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//a[@title="Expertise"]'))
                )
            except:
                expertise_tab = WebDriverWait(local_driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '(//a[@class="slds-tabs_default__link"])[2]'))
                )
            local_driver.execute_script("arguments[0].click();", expertise_tab)
            time.sleep(5)

            salesforce_exp, industry_exp = get_expertise(local_driver)
            dic1["salesforce_expertises"] = salesforce_exp
            dic1["industry_expertises"] = industry_exp
            break
        except Exception as e:
            if attempt == 2:
                tqdm.write(f"⚠️ Failed to load expertise for {link} after 3 attempts: {e}")
                dic1["salesforce_expertises"] = NULL
                dic1["industry_expertises"] = NULL
            else:
                time.sleep(2)

    with lock:
        final_list.append(dic1)

    local_driver.quit()

    try:
        with open('appex_partial.json', 'w', encoding='utf-8') as f:
            json.dump(final_list, f, indent=2)
    except Exception as e:
        tqdm.write(f"⚠️ Failed to write partial file: {e}")

    duration = time.time() - start_time
    pbar.set_postfix({"Last time (s)": f"{duration:.1f}"})
    pbar.update(1)

# Thread-safe progress bar execution
with tqdm(total=len(links_list), desc="Scraping Consultants") as pbar:
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(get_data_with_progress, (i, link), pbar, len(links_list))
                   for i, link in enumerate(links_list)]
        concurrent.futures.wait(futures)

# Save data
print("Saving results to 'appex.json'...")
with open('appex.json', 'w', encoding="utf-8") as f:
    json.dump(final_list, f, indent=2)

print("✅ Done. All data scraped and saved.")
