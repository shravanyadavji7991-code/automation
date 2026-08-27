import os
import time
import base64
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# --- CONFIGURATION ---
SPREADSHEET_ID = "1ZfOplr27OrhG4vrXl7mwG-GbEgGPFBbhCOEALWspnsY"
WORKSHEET_NAME = "Sheet1"
DRIVE_FOLDER_ID = "1LM_b_mv1adjHCohMQL9Ykrpu-3vVFJ3j"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

def get_user_credentials():
    creds = None
    # Token file stores the user access tokens
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('client_secret.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

creds = get_user_credentials()
gc = gspread.authorize(creds)
drive_service = build('drive', 'v3', credentials=creds)

def upload_to_drive(file_path, file_name):
    file_metadata = {
        'name': file_name,
        'parents': [DRIVE_FOLDER_ID]
    }
    media = MediaFileUpload(file_path, mimetype='application/pdf')
    file = drive_service.files().create(
        body=file_metadata, 
        media_body=media, 
        fields='id, webViewLink'
    ).execute()
    file_id = file.get('id')

    # Grant "Anyone with link can view"
    permission = {'type': 'anyone', 'role': 'reader'}
    drive_service.permissions().create(
        fileId=file_id, 
        body=permission
    ).execute()

    return file.get('webViewLink')

def clean_url(raw_url):
    if not raw_url:
        return ""
    markdown_match = re.search(r'\((https?://[^\)]+)\)', raw_url)
    if markdown_match:
        return markdown_match.group(1).strip()
    url_match = re.search(r'https?://[^\s\]\)]+', raw_url)
    if url_match:
        return url_match.group(0).strip()
    cleaned = raw_url.replace('[', '').replace(']', '').replace('(', '').replace(')', '').strip()
    if cleaned and not cleaned.startswith(("http://", "https://")):
        cleaned = "https://" + cleaned
    return cleaned

def process_reports():
    sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(WORKSHEET_NAME)
    data = sheet.get_all_records()

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)

    for idx, row in enumerate(data, start=2):
        raw_url = str(row.get('Link', '')).strip()
        portal_url = clean_url(raw_url)
        user_id = str(row.get('SNo') or row.get('ID', '')).strip()
        password = str(row.get('Password', '')).strip()
        student_name = row.get('Name', f'Student_{idx}')

        print(f"\nProcessing Row {idx}: {student_name}")
        print(f"--> Cleaned URL: '{portal_url}'")

        if not portal_url:
            print(f"Skipping Row {idx}: Empty Link column.")
            continue

        try:
            print(f"--> Opening: {portal_url}")
            driver.get(portal_url)
            time.sleep(2)

            driver.find_element(By.ID, "username").send_keys("tomsmith")
            driver.find_element(By.ID, "password").send_keys(password)
            driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
            time.sleep(3)

            local_pdf_path = f"temp_{idx}.pdf"
            pdf_data = driver.execute_cdp_cmd("Page.printToPDF", {"printBackground": True})
            with open(local_pdf_path, "wb") as f:
                f.write(base64.b64decode(pdf_data['data']))

            pdf_custom_name = f"{user_id}_result_report.pdf"
            drive_link = upload_to_drive(local_pdf_path, pdf_custom_name)

            sheet.update_cell(idx, 5, drive_link)
            print(f"SUCCESS: Saved link to sheet -> {drive_link}")

            if os.path.exists(local_pdf_path):
                os.remove(local_pdf_path)

        except Exception as e:
            print(f"Error on row {idx}: {e}")

    driver.quit()

if __name__ == "__main__":
    process_reports()