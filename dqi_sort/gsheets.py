"""Google Drive and Sheets access for the review sheets (see docs/google_sheets.md).

    python -m dqi_sort.gsheets setup DATA_DIR [--folder "DQI 2027"]

Signs in as the person running it (an OAuth "Desktop app" client in their own Google Cloud project), creates the
Drive folder that will hold the year's review sheets, puts a small test sheet in it, and records the folder in the
data repo's config.yaml (`sheets.folder_id`). Run it once per year, or again to check that sign-in still works.

Files, outside every repo:
    ~/.config/dqi-sort/oauth_client.json   the OAuth client, downloaded from the Google Cloud console
    ~/.config/dqi-sort/token.json          the saved sign-in; deleting it forces a fresh sign-in

The only permission requested is drive.file: the code can see and edit only files it created itself (and any
folder it created, wherever you later move it), nothing else in your Drive. While the Cloud app is in "Testing"
status, Google expires the sign-in after 7 days; the next run then opens a browser tab to approve again.
"""
import argparse, os, sys

CONFIG_DIR = os.path.expanduser('~/.config/dqi-sort')
CLIENT = os.path.join(CONFIG_DIR, 'oauth_client.json')
TOKEN = os.path.join(CONFIG_DIR, 'token.json')
SCOPES = ['https://www.googleapis.com/auth/drive.file']
FOLDER_MIME = 'application/vnd.google-apps.folder'
SHEET_MIME = 'application/vnd.google-apps.spreadsheet'


def credentials():
    """Saved sign-in, refreshed or renewed in the browser as needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES) if os.path.exists(TOKEN) else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:                      # expired (e.g. the 7-day limit in Testing status) or revoked
            creds = None
    if not creds or not creds.valid:
        if not os.path.exists(CLIENT):
            sys.exit(f'No OAuth client at {CLIENT}; see docs/google_sheets.md')
        print('Opening a browser tab to sign in to Google (approve once; see docs/google_sheets.md)')
        creds = InstalledAppFlow.from_client_secrets_file(CLIENT, SCOPES).run_local_server(port=0, open_browser=True)
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(TOKEN, 'w') as f:
        f.write(creds.to_json())
    os.chmod(TOKEN, 0o600)
    return creds


def services():
    from googleapiclient.discovery import build
    creds = credentials()
    return build('drive', 'v3', credentials=creds, cache_discovery=False), build('sheets', 'v4', credentials=creds, cache_discovery=False)


def create_sheet(drive, title, folder_id):
    """A new, empty Google Sheet in the folder; returns its file ID."""
    f = drive.files().create(body={'name': title, 'mimeType': SHEET_MIME, 'parents': [folder_id]}, fields='id').execute()
    return f['id']


def url(file_id, kind='spreadsheets'):
    return f'https://docs.google.com/{kind}/d/{file_id}/edit' if kind == 'spreadsheets' else f'https://drive.google.com/drive/folders/{file_id}'


def setup(data_dir, folder_name):
    import yaml
    cfg_path = os.path.join(data_dir, 'config.yaml')
    with open(cfg_path, encoding='utf-8') as f:
        text = f.read()
    cfg = yaml.safe_load(text) or {}
    drive, sheets = services()
    folder_id = (cfg.get('sheets') or {}).get('folder_id')
    if folder_id:
        drive.files().get(fileId=folder_id, fields='id,name').execute()      # still reachable?
        print('Folder already set up:', url(folder_id, 'folder'))
    else:
        folder_id = drive.files().create(body={'name': folder_name, 'mimeType': FOLDER_MIME}, fields='id').execute()['id']
        with open(cfg_path, 'a', encoding='utf-8') as f:
            f.write(f'\n# Review sheets (dqi_sort.gsheets): Drive folder created by `gsheets setup`; move it anywhere in Drive.\n'
                    f'sheets: {{folder_id: "{folder_id}", folder_name: "{folder_name}"}}\n')
        print('Created folder:', url(folder_id, 'folder'))
    test = create_sheet(drive, 'dqi-sort connection test (safe to delete)', folder_id)
    sheets.spreadsheets().values().update(spreadsheetId=test, range='A1:B2', valueInputOption='RAW',
                                          body={'values': [['dqi-sort', 'connection test'], ['status', 'ok']]}).execute()
    print('Test sheet:', url(test))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['setup'])
    ap.add_argument('data_dir')
    ap.add_argument('--folder', default='DQI review sheets')
    a = ap.parse_args()
    setup(a.data_dir, a.folder)


if __name__ == '__main__':
    main()
