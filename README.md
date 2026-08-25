# IOM Exam Results Watcher

Checks https://iom.edu.np/examination/exam-results/ automatically and sends
you a **free push notification** the moment a new result is posted.
100% free — runs on GitHub Actions (free tier) and notifies via
[ntfy.sh](https://ntfy.sh) (free, no account needed).

## Setup (takes about 5 minutes)

### 1. Create a free GitHub account
If you don't have one already: https://github.com/signup

### 2. Create a new repository
- Go to https://github.com/new
- Name it anything, e.g. `iom-results-watcher`
- Set it to **Private** (recommended) or Public, either works
- Click **Create repository**

### 3. Upload these files
Upload all files from this folder, keeping the same structure:
```
check_results.py
state.json
README.md
.github/workflows/check-results.yml
```
Easiest way: on the repo page, click **Add file → Upload files**, drag in
everything (make sure the `.github/workflows/check-results.yml` file ends up
in that exact folder path — GitHub's uploader preserves folder structure if
you drag the whole `iom-watcher` folder in, or you can create the file
manually via "Add file → Create new file" and paste the path in as the
filename).

### 4. Set up free notifications (ntfy.sh)
1. Pick a secret topic name only you know, e.g. `iom-results-a8x92k`
   (make it random so strangers can't guess it and see your notifications).
2. Install the **ntfy** app:
   - Android: [Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
   - iPhone: [App Store](https://apps.apple.com/us/app/ntfy/id1625396347)
   - Or just visit https://ntfy.sh/YOUR_TOPIC_NAME in a browser and click "Subscribe" — works without the app too, or use a desktop browser tab that stays open.
3. In the app, tap **+** and subscribe to your topic name.

### 5. Add the topic name as a GitHub secret
1. In your repo, go to **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `NTFY_TOPIC`
4. Value: the topic name you picked in step 4 (e.g. `iom-results-a8x92k`)
5. Click **Add secret**

### 6. Turn it on
- Go to the **Actions** tab in your repo
- Click **Check IOM Exam Results** on the left
- Click **Run workflow** to trigger the first run manually (this just
  initializes state — you won't get a notification for existing results)
- After that, it runs automatically every 30 minutes forever, for free

## Customizing

- **Check frequency**: edit the `cron` line in
  `.github/workflows/check-results.yml`. E.g. `*/15 * * * *` = every 15 min,
  `0 * * * *` = every hour. Don't go below every 5 minutes — GitHub throttles
  very frequent schedules.
- **Notification method**: the script uses ntfy.sh by default. If you'd
  rather get emails, let me know and I can swap in a free Gmail SMTP relay
  instead.

## How it works

1. Every 30 minutes, GitHub spins up a free temporary machine
2. It downloads the exam results page and extracts each result's title
3. It compares them to `state.json` (the last known list, stored in the repo)
4. If there's a new title, it sends a push notification to your phone via
   ntfy.sh with the result name and download link
5. It updates `state.json` and commits it back, so next run knows what's new
