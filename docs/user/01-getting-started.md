# Getting started
<!-- endpoints: setup#the-first-start, login#opening-locking-and-quitting, recovery_show#your-recovery-key, recover#if-you-forget-your-password, app_stopped#opening-locking-and-quitting, welcome_step#the-setup-wizard -->
<!-- icon: bi-rocket-takeoff -->

Install Python and Finance Hub on your Windows PC, create your user, keep your recovery key safe and let the setup wizard fit the Hub to you. After that the Hub runs quietly in the background and opens in your web browser.

## What you need

- A Windows 10 or Windows 11 PC. Finance Hub runs only on this computer, and your data stays on it.
- **Python 3.10 or newer**, from python.org. Install it first (see below).
- The Finance Hub setup, a file called for example `FinanceHub_1.7_Setup.zip`.
- An internet connection the first time, so that setup can download the packages the Hub needs.

## Step 1: install Python

Finance Hub is written in Python, so Python must be on your PC before you install the Hub.

1. Open python.org in your browser and download the newest Python for Windows.
2. Start the Python installer.
3. On its first page, tick **Add python.exe to PATH**. This is important.
4. Click **Install Now** and wait until it says the setup was successful.

> **Tip:** If you are not sure whether Python is already installed, just go on to step 2. The Finance Hub setup checks it for you and opens the Python download page if Python is missing or too old.

## Step 2: run the Finance Hub setup

1. Right-click `FinanceHub_1.7_Setup.zip` and choose **Extract All…**. You get a folder with a few files in it.
2. Open that folder and double-click **Setup.cmd**.
3. The **Finance Hub Setup** window opens. It has four pages. Click **Next >** to go from one to the next, and **< Back** to go back.

> **Good to know:** Some people receive the setup as one file, `FinanceHub_1.7_Setup.exe`. Double-click it: it unpacks itself and starts the same setup window. Python must be installed first in this case too.

If Python is missing or older than 3.10, `Setup.cmd` says so and opens the Python download page. Install Python as described in step 1, then double-click `Setup.cmd` again.

### Page 1: Welcome

The first page says which version you are installing and which Python version setup will use. If Finance Hub is already installed on this PC, it also says where, and that this installation will be upgraded while your data stays where it is.

### Page 2: Where to install

Here you choose two folders. Finance Hub keeps the program and your data apart:

| Folder | Suggested | What it holds |
|---|---|---|
| **Program folder** | `C:\Program Files\Finance Hub` | The program itself. Windows asks for permission once to install here. |
| **Data folder** | `D:\Finance Hub`, or `C:\Finance Hub Data` if your PC has no D: drive | Your encrypted data, the logs and the automatic backups. Uninstalling never removes it. |

You can change either folder with **Browse…**. The data folder must be a different folder from the program folder.

> **Tip:** Keeping the data on another drive (such as D:) means your data is untouched if Windows on C: ever has to be reinstalled. Keep the data folder on a drive that you back up.

Below the folders is the box **Bring over the data of an existing Finance Hub folder (an older version)**. Leave it empty for a new installation. If you used an older version of Finance Hub before, see [Upgrading from an older Finance Hub folder](#upgrading-from-an-older-finance-hub-folder).

### Page 3: Options

| Option | Ticked to begin with? |
|---|---|
| **Put a Finance Hub shortcut on the Desktop** | Yes |
| **Start Finance Hub when I log in to Windows (runs in the background)** | No |
| **Start Finance Hub when setup finishes** | Yes |

The page also shows a summary of the folders you chose. The button now says **Install**. Click it.

### Page 4: Installing

Setup shows what it is doing, line by line. When the program folder is in `Program Files`, Windows shows a question like "Do you want to allow this app to make changes to your device?". Click **Yes**. Setup asks only once, for the part of the installation that needs it.

When the last line says **Done.** and the button says **Finish**, click it. If you ticked **Start Finance Hub when setup finishes**, the Hub starts and your browser opens on the first-start page.

> **Important:** If you click **No** on the Windows question, setup cannot write to the program folder and stops with **Setup did not finish**. Click **Close**, run `Setup.cmd` again and click **Yes** this time, or choose a program folder in your own user folder.

### What setup does for you

- checks that the Finance Hub release inside the setup is complete and not damaged, and refuses a damaged download;
- copies the program into the program folder (when upgrading, it also removes program files that the new version no longer needs);
- creates the data folder, remembers where it is, and makes sure your Windows account may write to it;
- brings over the data of an older Finance Hub folder, if you asked for it;
- creates the Hub's own Python environment (a folder called `.venv`) and installs the packages the Hub needs. The first time this takes a few minutes;
- adds **Finance Hub** to **Settings › Apps** in Windows, so that you can uninstall it there;
- creates a **Finance Hub** shortcut in the Start menu, and on the Desktop if you ticked it;
- turns **Start with Windows** on or off, as you chose, and starts the Hub.

If Finance Hub is running while you install, setup stops and asks you to quit it first: right-click the tray icon and choose **Quit Finance Hub**, then click **Install** again.

## Upgrading from an older Finance Hub folder

Versions before 1.7 kept the program and the data together in one folder, for example `Documents\FinanceHub`. Setup can copy your data from there into the new data folder:

1. Quit the old Finance Hub: right-click its tray icon and choose **Quit Finance Hub**.
2. Run `Setup.cmd` as described above.
3. On page 2, tick **Bring over the data of an existing Finance Hub folder**, click **Browse…** next to it and choose your old Finance Hub folder: the one that contains the file `users.json`.
4. Finish the setup as usual.

Setup copies your users, your encrypted data, reminder mails waiting to go out, mail attachments waiting for your review and the old automatic backups. The old folder is copied, not moved: it is left exactly as it was.

Then log in with the same user ID and password as before. Nothing else changes for you. You don't see the first-start page or the setup wizard again, because your user already exists.

> **Good to know:** If the new data folder already has users, setup does not copy anything and says so in its log. Your existing data is never overwritten.

Once you have checked that everything is there, you can delete the old folder. It still holds an encrypted copy of your data, so don't leave it on a computer you give away.

> **Tip:** Setup turns **Start with Windows** on or off as you choose on page 3. If the old version started with Windows, tick that option again.

## The first start

The first-start page is called **First start · create your user**. You fill in four things:

| Field | What to enter |
|---|---|
| **Your name** | The name the Hub greets you with. It is stored only inside your encrypted data. |
| **User ID** | What you type to log in. At least 3 letters or numbers; dots, dashes and underscores are allowed. |
| **Password** | At least 10 characters, with at least three of: small letters, capital letters, numbers, symbols or spaces. |
| **Type it again** | The same password once more. |

A short sentence that you can remember easily makes a good password, for example "Mango season starts in April 2026".

Click **Create my encrypted Hub**. The Hub creates your own encrypted database. You become the first user and the administrator.

If the Hub finds unencrypted files from an older version in its data folder (old databases or uploaded statements), it lists them. The box **Securely erase the old unencrypted files** is ticked, so they are overwritten and deleted when you continue.

> **Tip:** Moving from another computer? Don't create a new user. Click **Restore from a backup** at the bottom of the first-start page instead. See [Backup and restore](help:backup-and-restore#moving-to-a-new-computer).

## Your recovery key

Right after the first start, the Hub shows your **recovery key** once. It looks like `ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345`.

The recovery key opens your data if you forget your password. Keep it as safe as the password itself.

1. Write the key on paper, or save it in a password manager.
2. Keep it away from this computer, for example with your important papers.
3. Tick **I have saved the recovery key somewhere safe**.
4. Click **Continue to the Hub**. The setup wizard starts.

> **Important:** The key is not shown again. If you lose it, you can make a new one on **Users & security** while you are logged in. See [Users and security](help:settings-and-users#your-recovery-key).

## The setup wizard

The first time you continue to the Hub, a short wizard called **Setting up your Hub** fits the Hub to you. Its five steps are shown at the top of the page; click one to jump to it.

On every step you can click **Save and continue**, or **Skip this step**. Everything you choose here can be changed later in **Settings**.

1. **About you.** Your name, as the Hub greets you. If you run your own company, type its name, for example "ABC Traders Pvt Ltd", and how that name appears on bank statements, separated by commas, for example "ABC TRADERS, ABC TRADERS PRIVATE LIMITED". The company then gets a separate book, so its money is kept apart from your personal money. See [Books, people and entities](help:books-people-and-entities).
2. **Mail** (optional). The address of a mailbox used only by the Hub, and its app password (spaces are removed for you). For an Outlook or Hotmail address leave the password empty and finish with **Sign in with Microsoft** on **Settings › Mail inbox**; more mailboxes can be added there too. Tick **Read the mailbox automatically while the Hub is open** to let the Hub fetch statements that arrive by mail. Type one or more addresses under **Send payment reminders and the weekly dues report to**, and keep **Send a reminder the day before payments are due, and a report every Sunday morning** ticked to turn reminders on. See [Mail inbox](help:mail-inbox) and [Reminders by mail](help:reminders-by-mail).
3. **Features.** **What do you use?** Tick the parts of the Hub you need. See [Choosing what you use](help:choosing-features).
4. **Accounts.** A list of the kinds of account you use, each with how many you have and an **Add** button. **Add** opens the add-account form in a new tab. Bank accounts and credit cards are also created for you when you add their statements.
5. **Backup.** Where to keep an encrypted copy of your data: the OneDrive or Google Drive folder on this PC, if the Hub finds one, or **Another folder**, and how often (**Every week** to begin with). See [Backup and restore](help:backup-and-restore).

On the last step, click **Finish and add my first statements** to go straight to [Add Statements](/import), or **Finish** to go to Home.

The wizard is shown only once. To open it again later, press **Ctrl+K** and search for "Setup wizard", or open [the setup wizard](/welcome) directly.

## Running in the background

Finance Hub is a small program that runs in the background, without a window of its own. You use it in your web browser at the address `http://127.0.0.1:5000/`. Only this computer can open that address.

While the Hub runs, its icon sits in the notification area near the clock. Right-click it to see this menu:

| Menu item | What it does |
|---|---|
| **Open Finance Hub** | Opens the Hub in your browser. Clicking the icon does the same. |
| **Lock now** | Locks your data at once. You must log in again. |
| **Start with Windows** | Starts the Hub every time you log in to Windows. A tick shows that it is on. |
| **Open logs folder** | Opens the `logs` folder inside your data folder, useful when something goes wrong. |
| **Quit Finance Hub** | Saves and locks your data, then stops the Hub. |

> **Tip:** If you don't see the icon, click the small up-arrow near the clock. Windows often hides new icons there. You can drag the icon out so that it is always visible.

## Opening, locking and quitting

### Opening the Hub

- Click the **Finance Hub** shortcut in the Start menu or on the Desktop.
- If the Hub is already running, the shortcut simply opens a new browser tab. It never starts a second copy.
- You can also bookmark `http://127.0.0.1:5000/` in your browser.

Log in with your **User ID** and **Password**, then click **Unlock**. After three wrong attempts you have to wait a little before you can try again.

### Locking

Locking closes your data and keeps it encrypted. The Hub keeps running, so reminder mails and automatic backups can still go out. You lock the Hub:

- with the lock button in the top bar of any page;
- with **Lock now** in the tray menu;
- automatically after 30 minutes without use (an administrator can change this);
- every time the Hub stops or restarts.

> **Good to know:** Closing the browser tab does not lock the Hub. It locks itself later, when the idle time has passed. Lock it yourself when you step away.

### Quitting

To stop the Hub completely, use **Quit Finance Hub** in the tray menu, or the power button in the Hub's top bar. Your data is saved and locked first. The **Stopped** page then confirms that Finance Hub has stopped, and you can close the tab.

To start again, use the **Finance Hub** shortcut.

## Start with Windows

If you want the Hub to be ready whenever your PC is on, turn on **Start with Windows**. There are three ways:

- tick **Start Finance Hub when I log in to Windows** on page 3 of the setup;
- in the tray menu, click **Start with Windows** so that it shows a tick;
- as an administrator, open **Settings › Users & security** and click the **Start with Windows** button in the **Running** card.

This needs no administrator rights in Windows. It only affects your own Windows account. When Windows starts, the Hub starts in the background without opening the browser.

> **Tip:** Turn this on if you use [Reminders by mail](help:reminders-by-mail) or automatic [backups](help:backup-and-restore). Both happen only while the Hub is running.

## Uninstalling

1. Quit Finance Hub (tray icon › **Quit Finance Hub**).
2. Open Windows **Settings › Apps** (on Windows 10: **Apps & features**), find **Finance Hub** and click **Uninstall**.
3. Confirm the question **Remove Finance Hub from …? Your data … is kept.** Windows may ask for permission again.

Uninstalling removes the program folder, the shortcuts and **Start with Windows**. It never removes your data folder. If you install Finance Hub again later with the same data folder, everything is back as it was.

If you really want to remove your data too, make a [backup](help:backup-and-restore) first if you might need it again, then delete the data folder yourself.

> **Good to know:** You can also uninstall by opening a Command Prompt in the setup folder and typing `Setup.cmd /uninstall`.

## If you forget your password

1. On the log-in page, click **Forgot password? Use the recovery key**.
2. Enter your **User ID** and your **Recovery key**. Capital or small letters both work, and the dashes are optional.
3. Enter a **New password** twice.
4. Click **Reset password**, then log in with the new password.

Lost the recovery key too? An administrator can give you a temporary password. See [Users and security](help:settings-and-users#password-reset-by-an-administrator).

## Questions

**Can I use the Hub from my phone?**
No. The Hub listens only on this computer, so other devices cannot reach it.

**Why must I log in again after a restart?**
Every start of the Hub begins locked. Your data is opened only after you type your password.

**Where is my data?**
In your data folder, `D:\Finance Hub` unless you chose another one during setup, encrypted. See [Backups, upgrades and troubleshooting](help:backups-upgrades-and-troubleshooting#where-finance-hub-keeps-things) and [Security and privacy](help:security-and-privacy).
