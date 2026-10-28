# Backups, upgrades and troubleshooting
<!-- endpoints: -->
<!-- icon: bi-life-preserver -->

Where Finance Hub keeps its program and your data, the automatic backups made before each new version, how to install a new version, where the log is, and what to do when something doesn't work.

## Where Finance Hub keeps things

Since version 1.7, the program and your data live in two separate folders. You chose both during setup:

| Folder | Usually | What is in it |
|---|---|---|
| **Program folder** | `C:\Program Files\Finance Hub` | The program, the Hub's own Python environment (`.venv`), and the file `financehub.json` |
| **Data folder** | `D:\Finance Hub`, or `C:\Finance Hub Data` on a PC without a D: drive | `data` (your encrypted databases), `users.json`, `uploads`, `logs` and `backups` |

The small file `financehub.json` in the program folder tells the Hub where your data folder is, and which port it uses. Setup writes it, for example:

```
{
 "data_dir": "D:\\Finance Hub",
 "port": 5000
}
```

- Uninstalling or upgrading never touches the data folder.
- A **portable copy** has no `financehub.json`: for example an older version, or a release zip unpacked by hand and set up with `install.bat`. Then the data stays inside the Finance Hub folder itself, as before 1.7.
- The person who maintains your PC can override the file with the Windows environment variables `FINANCEHUB_DATA` (the data folder) and `FINANCEHUB_PORT` (the port).

> **Tip:** To move your data to another drive, run the setup again, choose the new data folder, tick **Bring over the data of an existing Finance Hub folder** and choose your present data folder. The old folder is copied, not moved; delete it once everything works.

## Backups

There are two kinds of backup:

- **Your own backups**, in OneDrive, Google Drive or any folder, made automatically or whenever you like. They are explained in [Backup and restore](help:backup-and-restore). Set these up: they are the ones that protect you against a broken disk or a lost laptop.
- **Version backups**, made automatically before a new version first opens your data. They are explained here.

### Automatic version backups

The first time a new version of Finance Hub starts, it copies your encrypted data into the `backups` folder of your data folder, for example `D:\Finance Hub\backups`, before doing anything else. Each backup is a folder named after the date, the time and the new version, for example `2026-10-28_101500_before_1.7`. It holds:

- every user's encrypted database (the `.enc` files, and their spare `.enc.prev` copies);
- encrypted mail attachments waiting for review;
- `users.json`, which holds the locked keys;
- a short note saying which version the data came from.

The newest 10 backups are kept, and older ones are deleted. The **Running** card on **Settings › Users & security** shows how many backups there are and the date of the newest.

When you restore a backup on **Backup & restore**, the Hub also puts a safety copy of what you had into `backups\Finance Hub backups`.

The backups are still encrypted. They open with the passwords and recovery keys that were valid when the backup was made.

### Restoring a version backup by hand

1. Quit Finance Hub, with **Quit Finance Hub** in the tray menu or the power button in the top bar.
2. Open your data folder. To be safe, first copy the current `data` folder and `users.json` somewhere else.
3. Open the backup folder you want, inside `backups`.
4. Copy all its `.enc` and `.enc.prev` files, and any folders ending in `_files`, into the `data` folder, replacing the files there.
5. Copy its `users.json` into the data folder itself, replacing the one there.
6. Start Finance Hub and log in with the password that was valid when the backup was made.

Always restore the `.enc` files and `users.json` together, from the same backup. Everything any user did after that backup is lost. To bring back only your own data, use [Backup and restore](help:backup-and-restore#restoring-your-data) instead.

## Upgrading to a new version

A new version comes as a new setup, for example `FinanceHub_1.8_Setup.zip`.

1. Quit Finance Hub.
2. Extract the new setup and double-click **Setup.cmd**, as for the first installation (see [Getting started](help:getting-started#step-2-run-the-finance-hub-setup)).
3. The **Welcome** page says that an earlier installation was found and will be upgraded. Page 2 already shows your program folder and data folder; keep them.
4. Click through to **Install**, and **Finish** when it is done.

Setup checks that the new release is complete, replaces the program files, removes files the new version no longer needs and installs the packages the new version needs. Your data folder is not touched. The first start of the new version backs up your data automatically, and you have to log in again.

> **Good to know:** Coming from a version before 1.7, which kept everything in one folder? See [Upgrading from an older Finance Hub folder](help:getting-started#upgrading-from-an-older-finance-hub-folder).

### Upgrading a portable copy

A portable copy (see above) can still be upgraded the old way:

1. Quit Finance Hub.
2. Open a Command Prompt in the Finance Hub folder. (In File Explorer, type `cmd` in the address bar and press Enter.)
3. Type the following, with the path to the new release file (the `FinanceHub_<version>.zip` inside the setup), and press Enter:

```
.venv\Scripts\python.exe tools\upgrade.py "C:\Users\you\Downloads\FinanceHub_1.8.zip"
```

The tool checks that the release file is complete and not damaged, backs up your encrypted data, replaces the program files, removes files the new version no longer needs, and updates the Python packages. Then start the Hub from its shortcut. You can also unpack the release into the folder, replacing the files, and run `install.bat`.

### Version numbers

Every change to the Hub gets a new version number: 1.6, 1.7, and so on. You see the current version at the bottom of the sidebar and on the **Running** card. The file `CHANGELOG.md` in the program folder lists what changed in each version.

## The log file

The Hub writes a log to `logs\hub.log` in your data folder, for example `D:\Finance Hub\logs\hub.log`. It records starts and stops, mail checks, reminders sent and any errors. When it reaches 1 MB, it is renamed and a new one starts. The five newest old logs are kept.

It never contains passwords or statement contents. **Open logs folder** in the tray menu opens its folder.

## Common problems

### Something doesn't work as it should

Use **Settings › Report a problem**. It collects the details that help to find the cause, shows you the exact text, and sends it to support. See [Reporting a problem](help:reporting-a-problem).

### Setup says Python is missing, or the setup window does not appear

- Install Python 3.10 or newer from python.org with **Add python.exe to PATH** ticked, then run `Setup.cmd` again. See [Getting started](help:getting-started#step-1-install-python).
- The setup window needs the part of Python called "tcl/tk", which the python.org installer includes unless it was switched off. Run the Python installer again with its standard options.
- Or open a Command Prompt in the setup folder and type `Setup.cmd /silent`. This installs into the suggested folders, with a Desktop shortcut, and starts the Hub, without the setup window.

### "Port 5000 is used by another program"

Another program already uses the Hub's address. Close it and start the Hub again. If that is not possible, the person who maintains your PC can give the Hub another port, for example 5050: either change `"port"` in `financehub.json` in the program folder (running setup again sets it back to 5000), or set the Windows environment variable `FINANCEHUB_PORT`. You then open the Hub at `http://127.0.0.1:5050/`.

### I forgot my password

On the log-in page, click **Forgot password? Use the recovery key**. See [Getting started](help:getting-started#if-you-forget-your-password). If the recovery key is lost too, ask an administrator to give you a temporary password; see [Users and security](help:settings-and-users#password-reset-by-an-administrator). If there is no administrator who can do that, the data cannot be opened. An administrator can then remove the user and add them again, starting with empty data, or with your last backup.

### "Too many wrong attempts"

After three wrong passwords, the Hub makes you wait before the next try, a little longer after each wrong one, up to five minutes. Wait, then try again carefully, and check Caps Lock.

### There is no tray icon

- Look under the small up-arrow near the clock; Windows often hides new icons there.
- If it is really missing, the Hub still runs. Open it with the shortcut, and quit it with the power button in the top bar.
- Run the setup again; it reinstalls the package that draws the icon.

### The Hub does not open, or shows an error

- Start it with the **Finance Hub** shortcut in the Start menu.
- If you see "Finance Hub could not start", your data is safe; the details are at the end of `logs\hub.log` in your data folder.
- If you see "Something went wrong", your data is safe too. Click **Report this problem** on that page; the report includes the error reference. See [Reporting a problem](help:reporting-a-problem#error-references).
- If pages look plain, without colours or icons, check your internet connection. The page layout is loaded from the internet.

### The mail inbox doesn't connect

The message "the mailbox refused the address / app password" means Gmail did not accept the details.

- Check the **Hub mailbox address** for typing mistakes.
- Make sure 2-Step Verification is still on for that Gmail account, then create a new app password and paste it again.
- Check that IMAP is on in that Gmail account's settings.
- Click **Test connection** after each change.

See [Mail inbox](help:mail-inbox).

### Reminders are not sent

Check these, in order:

1. **Settings › Reminders & reports by mail**: **Send reminders and reports** is ticked, there is at least one address, and the **Coming up** list shows mails.
2. **Send a test report now** works. If not, fix the mail inbox first.
3. The Hub was running at the planned time, and the computer was on and not asleep. Turn on **Start with Windows**.
4. You have logged in during the last week, so the mails were prepared.

See [Reminders by mail](help:reminders-by-mail).

### Automatic backups are not made

- **Settings › Backup & restore** shows the reason in red next to **Last backup**, for example a USB drive that was not plugged in.
- A backup is made only when your data changed since the last one, and only while the Hub is running.

See [Backup and restore](help:backup-and-restore#automatic-backups).

### "None of the saved passwords opens this PDF"

- Type the password in the box on the preview card, keep **save on Passwords page** ticked and click **Open**.
- Look for the bank's mail that came with the statement; it explains the password.
- Common patterns are letters of your name with your date of birth, a customer ID, or the last digits of the account. For CAS statements it is usually your PAN in capital letters.
- If the bank changed its password, update it on **Settings › Statement passwords**.

### The Hub locked itself

That is the idle lock, after 30 minutes without use by default. Log in again. Every restart of the Hub also locks it. See [Users and security](help:settings-and-users#the-idle-lock).
