# Getting started
<!-- endpoints: setup#the-first-start, login#opening-locking-and-quitting, recovery_show#your-recovery-key, recover#if-you-forget-your-password, app_stopped#opening-locking-and-quitting -->
<!-- icon: bi-rocket-takeoff -->

Install Finance Hub on your Windows PC, create your user and keep your recovery key safe. After that the Hub runs quietly in the background and opens in your web browser.

## What you need

- A Windows PC. Finance Hub runs only on this computer, and your data stays on it.
- Python 3.10 or newer, from python.org. While installing Python, tick **Add python.exe to PATH**.
- An internet connection the first time, so that the installer can download the packages the Hub needs.

> **Tip:** Put the Finance Hub folder somewhere in your own user folder, for example `Documents\FinanceHub`. Avoid `Program Files`, because the Hub has to write its data and logs inside its own folder.

## Installing

1. Unpack the Finance Hub release (the `.zip` file) into the folder you chose.
2. Double-click `install.bat` in that folder.
3. Wait while it works. The first time this takes a few minutes.
4. When it says **Done**, the Hub starts and your browser opens on the first-start page.

What `install.bat` does for you:

- finds Python on your PC;
- creates the Hub's own Python environment, a folder called `.venv`;
- installs the packages listed in `requirements.txt` and records the exact versions in `requirements.lock`;
- creates two shortcuts called **Finance Hub**: one on the Desktop and one in the Start menu;
- starts the Hub.

You can run `install.bat` again at any time, for example to repair a broken installation. It never touches your data.

> **Good to know:** If Python is missing or too old, `install.bat` says so and stops. Install Python 3.10 or newer, then run `install.bat` again.

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

If the Hub finds unencrypted files from an older version in its folder (old databases, backups or uploaded statements), it lists them. The box **Securely erase the old unencrypted files** is ticked, so they are overwritten and deleted when you continue.

## Your recovery key

Right after the first start, the Hub shows your **recovery key** once. It looks like `ABCD-EFGH-JKLM-NPQR-STUV-WXYZ-2345`.

The recovery key is the only way to open your data if you forget your password. Nobody else can open it, and that includes the administrator.

1. Write the key on paper, or save it in a password manager.
2. Keep it away from this computer, for example with your important papers.
3. Tick **I have saved the recovery key somewhere safe**.
4. Click **Continue to the Hub**.
5. The Hub then asks **What do you use?** Tick the features you need (savings, cards, loans, business, investments …) and click **Continue**. You can change this later — see [Choosing what you use](help:choosing-features).

> **Important:** The key is not shown again. If you lose it, you can make a new one on **Users & security** while you are logged in. See [Users and security](help:settings-and-users#your-recovery-key).

## Running in the background

Finance Hub is a small program that runs in the background, without a window of its own. You use it in your web browser at the address `http://127.0.0.1:5000/`. Only this computer can open that address.

While the Hub runs, its icon sits in the notification area near the clock. Right-click it to see this menu:

| Menu item | What it does |
|---|---|
| **Open Finance Hub** | Opens the Hub in your browser. Clicking the icon does the same. |
| **Lock now** | Locks your data at once. You must log in again. |
| **Start with Windows** | Starts the Hub every time you log in to Windows. A tick shows that it is on. |
| **Open logs folder** | Opens the folder with the log file, useful when something goes wrong. |
| **Quit Finance Hub** | Saves and locks your data, then stops the Hub. |

> **Tip:** If you don't see the icon, click the small up-arrow near the clock. Windows often hides new icons there. You can drag the icon out so that it is always visible.

## Opening, locking and quitting

### Opening the Hub

- Double-click the **Finance Hub** shortcut on the Desktop or in the Start menu.
- If the Hub is already running, the shortcut simply opens a new browser tab. It never starts a second copy.
- You can also bookmark `http://127.0.0.1:5000/` in your browser.

Log in with your **User ID** and **Password**, then click **Unlock**. After three wrong attempts you have to wait a little before you can try again.

### Locking

Locking closes your data and keeps it encrypted. The Hub keeps running, so reminder mails can still go out. You lock the Hub:

- with the lock button in the top bar of any page;
- with **Lock now** in the tray menu;
- automatically after 30 minutes without use (an administrator can change this);
- every time the Hub stops or restarts.

> **Good to know:** Closing the browser tab does not lock the Hub. It locks itself later, when the idle time has passed. Lock it yourself when you step away.

### Quitting

To stop the Hub completely, use **Quit Finance Hub** in the tray menu, or the power button in the Hub's top bar. Your data is saved and locked first. The **Stopped** page then confirms that Finance Hub has stopped, and you can close the tab.

To start again, use the **Finance Hub** shortcut, or `run.bat` in the Finance Hub folder. `run.bat` also runs `install.bat` first if the Hub's Python environment is missing.

## Start with Windows

If you want the Hub to be ready whenever your PC is on, turn on **Start with Windows**:

- in the tray menu, click **Start with Windows** so that it shows a tick; or
- open **Settings › Users & security** and click the **Start with Windows** button in the **Running** card.

This needs no administrator rights. It only affects your own Windows account. When Windows starts, the Hub starts in the background without opening the browser.

> **Tip:** Turn this on if you use [Reminders by mail](help:reminders-by-mail). Reminders are sent only while the Hub is running.

## If you forget your password

1. On the log-in page, click **Forgot password? Use the recovery key**.
2. Enter your **User ID** and your **Recovery key**. Capital or small letters both work, and the dashes are optional.
3. Enter a **New password** twice.
4. Click **Reset password**, then log in with the new password.

## Questions

**Can I use the Hub from my phone?**
No. The Hub listens only on this computer, so other devices cannot reach it.

**Why must I log in again after a restart?**
Every start of the Hub begins locked. Your data is opened only after you type your password.

**Where is my data?**
In the `data` folder inside the Finance Hub folder, encrypted. See [Security and privacy](help:security-and-privacy).
