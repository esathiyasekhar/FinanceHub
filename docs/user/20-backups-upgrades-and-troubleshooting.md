# Backups, upgrades and troubleshooting
<!-- endpoints: -->
<!-- icon: bi-life-preserver -->

How the Hub backs up your data, how to restore a backup and install a new version, where the log is, and what to do when something doesn't work.

## Backups

### Automatic backups

The first time a new version of Finance Hub starts, it copies your encrypted data into the `backups` folder before doing anything else. Each backup is a folder named after the date, the time and the new version, for example `2026-10-28_101500_before_1.6`. It holds:

- every user's encrypted database (the `.enc` files, and their spare `.enc.prev` copies);
- `users.json`, which holds the locked keys;
- a short note saying which version the data came from.

The newest 10 backups are kept, and older ones are deleted. The **Running** card on **Settings › Users & security** shows how many backups there are and the date of the newest.

The backups are still encrypted. They open with the passwords and recovery keys that were valid when the backup was made.

### Your own backups

Automatic backups sit on the same disk as the Hub, so a failed disk or lost laptop takes them too. Now and then, for example after each month close:

1. Quit Finance Hub.
2. Copy the `data` folder and the file `users.json` from the Finance Hub folder to a USB drive or to cloud storage.
3. Start the Hub again.

> **Important:** The files are encrypted, so they are safe to keep anywhere. But a backup opens only with the password or recovery key that was valid at the time.

### Restoring a backup by hand

1. Quit Finance Hub, with **Quit Finance Hub** in the tray menu or the power button in the top bar.
2. Open the Finance Hub folder. To be safe, first copy the current `data` folder and `users.json` somewhere else.
3. Open the backup folder you want, inside `backups` (or on your USB drive).
4. Copy all its `.enc` and `.enc.prev` files into the `data` folder, replacing the files there.
5. Copy its `users.json` into the Finance Hub folder itself, replacing the one there.
6. Start Finance Hub and log in with the password that was valid when the backup was made.

Always restore the `.enc` files and `users.json` together, from the same backup. Everything you did after that backup is lost.

## Upgrading to a new version

A new version comes as a release file called, for example, `FinanceHub_1.7.zip`. Your data, `users.json`, the backups and the logs are never touched by an upgrade.

### With the upgrade tool

1. Quit Finance Hub.
2. Open a Command Prompt in the Finance Hub folder. (In File Explorer, type `cmd` in the address bar and press Enter.)
3. Type the following, with the path to the release file, and press Enter:

```
.venv\Scripts\python.exe tools\upgrade.py "C:\Users\you\Downloads\FinanceHub_1.7.zip"
```

The tool checks that the release file is complete and not damaged, backs up your encrypted data, replaces the program files, removes files the new version no longer needs, and updates the Python packages. Then start the Hub from its shortcut.

### By unpacking the release

1. Quit Finance Hub.
2. Unpack the release file into the Finance Hub folder, and let it replace the existing files.
3. Run `install.bat`. It updates the packages, renews the shortcuts and starts the Hub.

> **Tip:** The first start of the new version backs up your data automatically, and you have to log in again.

### Version numbers

Every change to the Hub gets a new version number: 1.1, 1.2, and so on. You see the current version at the bottom of the sidebar and on the **Running** card. The file `CHANGELOG.md` in the Finance Hub folder lists what changed in each version.

## The log file

The Hub writes a log to `logs\hub.log` in the Finance Hub folder. It records starts and stops, mail checks, reminders sent and any errors. When it reaches 1 MB, it is renamed and a new one starts. The five newest old logs are kept.

It never contains passwords or statement contents. **Open logs folder** in the tray menu opens its folder.

## Common problems

### "Port 5000 is used by another program"

Another program already uses the Hub's address. Close it and start the Hub again. If that is not possible, the person who maintains your PC can set the Windows environment variable `FINANCEHUB_PORT` to another number, for example 5050. You then open the Hub at `http://127.0.0.1:5050/`.

### I forgot my password

On the log-in page, click **Forgot password? Use the recovery key**. See [Getting started](help:getting-started#if-you-forget-your-password). If the recovery key is lost too, the data cannot be opened. An administrator can remove the user and add them again, starting with empty data.

### "Too many wrong attempts"

After three wrong passwords, the Hub makes you wait before the next try, a little longer after each wrong one, up to five minutes. Wait, then try again carefully, and check Caps Lock.

### There is no tray icon

- Look under the small up-arrow near the clock; Windows often hides new icons there.
- If it is really missing, the Hub still runs. Open it with the shortcut, and quit it with the power button in the top bar.
- Run `install.bat` again to reinstall the package that draws the icon.

### The Hub does not open, or shows an error

- Start it with the **Finance Hub** shortcut, or with `run.bat` in its folder.
- If you see "Finance Hub could not start" or "Something went wrong", your data is safe; the details are at the end of `logs\hub.log`.
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

### "None of the saved passwords opens this PDF"

- Type the password in the box on the preview card, keep **save on Passwords page** ticked and click **Open**.
- Look for the bank's mail that came with the statement; it explains the password.
- Common patterns are letters of your name with your date of birth, a customer ID, or the last digits of the account. For CAS statements it is usually your PAN in capital letters.
- If the bank changed its password, update it on **Settings › Statement passwords**.

### The Hub locked itself

That is the idle lock, after 30 minutes without use by default. Log in again. Every restart of the Hub also locks it. See [Users and security](help:settings-and-users#the-idle-lock).
