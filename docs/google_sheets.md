# Google Sheets setup

The review sheets (see Sort review in `PROCESS.md`) are Google Sheets that the pipeline creates and fills in. They
are created by **your own Google account**: you own them, they sit in a folder in your Drive, and they stay there
whatever happens to the setup below. Set this up once per person (the secretary or lead running the pipeline);
it takes about 15 minutes and costs nothing.

## What you will end up with

- A Google Cloud project with a small OAuth "app" that only you use. It lets the dqi-sort code act as you, and it
  is allowed exactly one permission, `drive.file`: it can see and edit only files it created itself, nothing else
  in your Drive.
- Two files on your computer, outside every repository:
  - `~/.config/dqi-sort/oauth_client.json`: the app's client file, downloaded from the console
  - `~/.config/dqi-sort/token.json`: your saved sign-in, created on first use
- A Drive folder for the year's sheets, created by the code. Move or rename it freely; the code keeps access.

Never put either file in a repository, paste it into chat, or share it.

## Steps

Use a personal Google account (plain Gmail is fine). Sign in to the console with **the account that should own
the sheets** before you start.

1. **Create the project.** Go to <https://console.cloud.google.com>, open the project picker at the top, and click
   **New project**. Name it `dqi-sort`. Set **Location** to **No organization**, then **Create**. Make sure the
   new project is selected at the top of the page.
   - If your account has its own Cloud organization (the project picker lists one), new projects land inside it
     by default; choose **No organization** so the project stands alone.
2. **Enable two APIs.** Under **APIs & Services → Library**, search for and **Enable** the **Google Sheets API**,
   then the **Google Drive API**. (The "Drive SDK" is something else; you do not need it.)
3. **Set up sign-in.** In the left menu of APIs & Services, click **OAuth consent screen**; it opens the
   **Google Auth Platform**. Click **Get started** and fill in the short wizard:
   - App name `dqi-sort`; user support email: your address
   - Audience: **External**
   - Contact information: your address
   - Agree to the policy, then **Create**

   Leave everything else on the **Branding** page empty (logo, home page, privacy policy, domains): those are only
   needed to publish an app to the public, which we do not do.
4. **Add yourself as a test user.** In Google Auth Platform → **Audience**, under **Test users**, click
   **Add users**, add your own address, and **Save**. Do **not** click **Publish app**.
   - If Audience shows **User type: Internal**, the project is inside an organization (see step 1). Start again
     with **No organization**, or click **Make external**.
5. **Create the client.** In Google Auth Platform → **Clients**, click **Create client**. Application type
   **Desktop app**, name `dqi-sort sync`. Leave **Use this client for an AI-powered agent** unchecked (that is
   for MCP tools; ours is an ordinary program). Click **Create**, then **Download JSON** in the dialog. (If you
   closed it, click the client's name in the list and use the download icon.)
6. **Put the file in place.** In Terminal:

   ```
   mkdir -p ~/.config/dqi-sort
   mv ~/Downloads/client_secret_*.json ~/.config/dqi-sort/oauth_client.json
   chmod 700 ~/.config/dqi-sort && chmod 600 ~/.config/dqi-sort/oauth_client.json
   ```

7. **Connect and create the folder.** From the dqi-sort repository:

   ```
   pip install -r requirements.txt
   python -m dqi_sort.gsheets setup DATA_DIR --folder "DQI 2027 review"
   ```

   A browser tab opens. Choose your account. Google warns **"Google hasn't verified this app"**: that is expected
   for your own unpublished app. Click **Advanced → Go to dqi-sort (unsafe) → Continue**. The command then creates
   the folder, puts a test sheet in it, and records the folder in `DATA_DIR/config.yaml` (`sheets.folder_id`).
   Open the printed link to see it; delete the test sheet whenever you like.

## Making the review sheets

After every merge to the data repo (commit first; the sheets are stamped with the commit):

```
python -m dqi_sort.sheets sync DATA_DIR
```

It updates the shared sheet in place and makes a new sheet for each area whose sessions changed since its last
sheet (`--areas SCDEV,QEC` or `--all` to choose). Ollama must be running for the attendance estimates. The links
are printed and recorded in `DATA_DIR/sorting/sheets.csv`; commit that file. Share the Drive folder with the
reviewers: everyone as viewer, and each area's reviewers as editors of their own area sheet.

## Living with it

- **Weekly re-approval.** Because the app stays in "Testing" status, Google expires your sign-in after 7 days. The
  next command that touches the sheets opens the browser tab again; approve it the same way and it carries on.
  Publishing the app would remove this, but it requires a verified web domain, privacy policy and so on; not worth
  it for a tool one person uses for a few weeks.
- **Starting over.** Delete `~/.config/dqi-sort/token.json` and run any sheets command to sign in afresh. To revoke
  the app entirely: <https://myaccount.google.com/permissions> → dqi-sort → remove access.
- **Handing over.** The next secretary repeats these steps with their own account; nothing is transferred. To give
  them the existing sheets, share the Drive folder with them.
- **Cost.** None: no billing account is needed, and the pipeline stays far inside the free quotas.
