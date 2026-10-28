# Backup and restore
<!-- endpoints: backup_page, setup_restore#moving-to-a-new-computer -->
<!-- icon: bi-cloud-arrow-up -->

Keep an encrypted copy of your data in OneDrive, Google Drive or any folder, automatically or whenever you like, and bring it back after a mistake, a broken disk or a move to a new computer.

## What a backup is

A backup is one file, for example `FinanceHub_ravi_2026-10-28_101500.fhb`: your user ID, then the date and time it was made. It holds everything in your Hub: accounts, transactions, categories, rules, loans, investments, settings, statement passwords and mail attachments waiting for your review.

- The file stays **encrypted**. It opens only with your password or your recovery key, so it is safe to keep in the cloud or on a USB drive.
- Each user backs up their own data, with their own settings. Nobody makes backups of another user's data.
- The Hub never sends the backup anywhere itself. It writes the file into a folder on this PC; if that folder belongs to OneDrive or Google Drive, their app on your PC uploads it.

Open **Settings › Backup & restore** ([Backup & restore](/backup)). You can also choose the folder in the last step of the setup wizard.

## Choosing where

Under **Where and how often**, the Hub lists the cloud folders it finds on this PC:

| Shown as | Where the Hub looks |
|---|---|
| **OneDrive**, **OneDrive (personal)**, **OneDrive (work / school)** | the OneDrive folders that Windows knows about, and `OneDrive` in your user folder |
| **Google Drive (G:)** (or another letter) | the `My Drive` folder of Google Drive for desktop, for example `G:\My Drive` |
| **Google Drive** | a `Google Drive` or `My Drive` folder in your user folder |
| **Dropbox** | a `Dropbox` folder in your user folder |

1. Pick one of them, or choose **Another folder** and type its path, for example `E:\Backups` for a USB drive.
2. Choose **Automatic backup** (see below) and how many backups to **Keep the newest** (10 to begin with).
3. Click **Save**.

The Hub keeps the backups in a subfolder called `Finance Hub backups` inside the folder you chose. The page shows the full path under the **Save** button.

> **Tip:** A backup on the same disk as the Hub doesn't help if that disk fails or the laptop is lost. Choose OneDrive, Google Drive or a USB drive that you keep somewhere else.

### Getting OneDrive or Google Drive on your PC

If the page says **No OneDrive or Google Drive folder was found on this PC**, install one of their apps and sign in:

- **OneDrive** comes with Windows 10 and 11. Open **OneDrive** from the Start menu and sign in with your Microsoft account. Its folder, `OneDrive`, appears in your user folder.
- **Google Drive for desktop** is a free app from Google. Download it from Google's website, install it and sign in with your Google account. Your Drive then appears as a new drive in File Explorer, usually `G:`, with a `My Drive` folder in it.

Then open **Backup & restore** again; the new folder is listed.

> **Good to know:** The backup reaches the cloud only when the OneDrive or Google Drive app is running and signed in. Check its icon near the clock now and then.

## Automatic backups

| Automatic backup | What happens |
|---|---|
| **Only when I click Back up now** | No automatic backups. |
| **Every day** | A backup about once a day. |
| **Every week** | A backup about once a week. |

- Automatic backups are made in the background, also while the Hub is locked. Your data file is already encrypted, so the Hub doesn't need your password for this.
- A backup is made only if your data has changed since the last one.
- Only the newest backups are kept, as many as you set in **Keep the newest**. Older ones of yours in that folder are deleted.
- The Hub must be running. Turn on **Start with Windows** (see [Getting started](help:getting-started#start-with-windows)).

At the top of the page you see **Last backup** with its date and time. If a backup failed, for example because the USB drive was not plugged in, the reason is shown in red next to it.

## Back up now and Download

- **Back up now** makes a backup at once in your chosen folder. The button works once you have chosen a folder and clicked **Save**.
- **Download a backup file** saves a backup through your browser, normally into your `Downloads` folder. Keep it where you like. Downloaded files are not counted in **Keep the newest**, so delete old ones yourself.

> **Tip:** Click **Back up now** before big changes, such as **Reset & Reload from Folder** on Add Statements or deleting many transactions.

## Restoring your data

Restoring replaces your present data with the data in a backup. Everything you did after that backup was made is replaced.

### From your backup folder

The card **Your backups** lists the backups of your user in the chosen folder, newest first, with the date, the version of Finance Hub that made it and its size.

1. Find the backup you want.
2. Normally leave the password box (**only for a backup from another installation**) empty (see [Which password a backup needs](#which-password-a-backup-needs)).
3. Click **Restore** and confirm.

### From a file

Use **Restore from a file** for a downloaded backup, a backup on a USB drive, or a backup made under an earlier user ID:

1. Click the file box and choose the `.fhb` file.
2. Normally leave the password box empty (see below).
3. Click **Restore** and confirm.

### Which password a backup needs

- Your own backups open with the key you are logged in with, even if you have changed your password since. You can leave the password box empty.
- A backup that does not open that way needs the password you had when it was made, or the recovery key you had then. That happens, for example, on a new computer where you were added again as a new user. If the Hub says **that password (or recovery key) does not open this backup**, type the password of that time.
- After restoring, you keep logging in with your **present** password, and your present recovery key keeps working.

### What happens when you restore

1. The Hub checks that the backup file is complete and undamaged. A damaged file is refused and nothing changes.
2. It saves what you have now as a safety backup, in the folder `backups\before-restore\Finance Hub backups` inside your data folder (the newest 10 are kept).
3. It replaces your data with the backup and opens it. You stay logged in.

The message tells you the date of the backup, the version that made it, and the name of the safety backup. If you restored the wrong one, restore the safety backup the same way, with **Restore from a file**.

## Moving to a new computer

1. Make a fresh backup on the old computer: **Back up now**, or **Download a backup file** and copy it to a USB drive.
2. On the new computer, install Python and Finance Hub as described in [Getting started](help:getting-started).
3. When the first-start page **First start · create your user** opens, don't create a user. Click **Restore from a backup** at the bottom.
4. Choose the backup file (`.fhb`): from the OneDrive or Google Drive folder on the new PC, a USB drive or a download.
5. Type the **Password (or recovery key)** you had when the backup was made, and click **Restore**.
6. Log in with that user ID and password.

You become the administrator of the new Hub. Then:

- Choose your backup folder again on **Backup & restore**. Backup settings stay with each computer and are not part of the backup.
- If others in your family use the Hub, add them on **Users & security**. Give each of them the same user ID they had before. Each of them then logs in and restores their own backup with **Restore from a file** and the password of their backup. (A backup can only be restored into the account it came from, or into an account with the same user ID.)

> **Good to know:** **Restore from a backup** is offered only while the new Hub has no users yet. Once a user exists, restore from **Settings › Backup & restore** instead.

> **Tip:** To move every user at once, copy the whole old data folder (for example `D:\Finance Hub`) to a USB drive. On the new PC, tick **Bring over the data of an existing Finance Hub folder** in setup and choose that copy. Reminder mails are prepared again after you log in.

## Backups stay encrypted

- A backup holds your database exactly as the Hub keeps it on disk: encrypted with AES-256. OneDrive, Google Drive or anyone who finds the file sees only scrambled data.
- Outside your own Hub account, it opens only with the password or recovery key you had when it was made. Keep in mind that an administrator who can reset your password could also open your backups; see [Security and privacy](help:security-and-privacy#administrators-can-reset-passwords).
- The file name shows your user ID and the date. Nothing else in it is readable.

> **Important:** An old backup still opens with the password you had back then. If you change your password because someone else learned it, delete your older backups, or keep them where that person can't reach them.

## What users.json and a backup contain

The Hub keeps a small file called `users.json` in your data folder, next to the `data` folder. It is not encrypted, so it holds nothing about your money:

| In users.json | In a backup file (.fhb) |
|---|---|
| Each user ID, their access (administrator or user), and when they were created and last logged in | A short list of contents: the Finance Hub version, the date, your user ID and checksums of the files |
| The locked keys: your data key, locked with your password and with your recovery key | Your own entry from users.json: your locked keys, your access and the date you were created |
| A copy of each user's data key locked for administrator reset, and the administrators' reset key | Your encrypted database |
| Your backup settings: folder, how often, how many to keep, the time of the last backup and any error | Your encrypted mail attachments waiting for review |
| Whether you must choose a new password, and the idle-lock time | |

A backup does **not** contain other users' data, the copy of your key for administrator reset, your backup settings, the logs, or reminder mails waiting to go out.

## Questions

**Can I open a .fhb file myself?**
It is a zip file, but everything that matters inside it is encrypted. Only Finance Hub can restore it, with your password or recovery key.

**Are my statement PDFs in the backup?**
No. The Hub doesn't keep your statement files after adding them. The transactions they contained are in the backup.

**Can an administrator back up or restore my data?**
No. Everyone backs up and restores only their own data, while logged in as themselves.

**How big is a backup?**
The list **Your backups** shows the size of each one. It grows with the number of transactions you keep.
