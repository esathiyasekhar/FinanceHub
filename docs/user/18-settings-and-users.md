# Users, security and statement passwords
<!-- endpoints: users_page, passwords_page, change_password#password-reset-by-an-administrator -->
<!-- icon: bi-shield-lock -->

Manage who can use the Hub, change your password, user ID and recovery key, reset another user's password as an administrator, set the automatic lock, and look after the passwords that open your statements.

## Users & security

Open **Settings › Users & security** ([Users & security](/users)). The page has four parts: your name, the list of users, **Protection** and **Running**. Administrators also see **Unencrypted copies in the app folder**.

### Your name and your user ID

These are two different things:

- **Your name** is how the Hub greets you and what it shows at the bottom of the sidebar. You can change it at any time: type it and click **Save**. It is stored only inside your encrypted data.
- **Your user ID** is what you type to log in. You can change it too, with your password. See [Changing your user ID](#changing-your-user-id).

### Users and roles

Every user has their own encrypted data. Users never see each other's accounts, statements or settings. This suits a family where each person keeps their own money separately.

There are two kinds of access:

| Access | What they can do |
|---|---|
| **Administrator (can add / remove users)** | Everything a user can, plus add and remove users, change access, reset another user's password or user ID, set the idle lock and remove unencrypted copies. |
| **User** | Use the Hub with their own data, change their own password and user ID, and make a new recovery key. |

The first user, created at the first start, is an administrator. The Hub always keeps at least one administrator.

### Adding a user

Only an administrator can do this.

1. Below the list of users, fill in **Name**, **User ID (to log in)**, **Password** and **Again**.
2. Choose the **Access**: **User** or **Administrator**.
3. Click the add-user button.

The new user starts with empty data. The first time they log in, the Hub shows them their own recovery key and then the setup wizard (see [Getting started](help:getting-started#the-setup-wizard)). Ask them to store the key safely.

> **Good to know:** Only one person can have the Hub open at a time. When another user logs in, the first user's data is saved and locked.

### Changing access or removing a user

- To change a user's access, an administrator picks the new value in the **Access** column. It is saved at once.
- To remove a user, an administrator clicks the bin button on that user's line and confirms. The user's encrypted data is erased for good. You cannot remove yourself.

### Changing your password

1. Click **Change password** on your own line.
2. Enter your **Current password**, then the **New password** twice.
3. Click **Change**.

The Hub checks your current password and saves the new one. You stay logged in, and your recovery key keeps working.

Each user changes only their own password this way. If someone has forgotten theirs, they use their recovery key on the log-in page (see [Getting started](help:getting-started#if-you-forget-your-password)), or an administrator resets it (see below).

### Changing your user ID

1. Click **Change user ID** on your own line.
2. Type the **New user ID**: 3 to 40 letters or numbers; dots, dashes and underscores are allowed. It must not belong to another user.
3. Type **Your password**.
4. Click **Change user ID**.

The Hub confirms "Your user ID is now …". Use the new ID the next time you log in. Your data, your name, your password, your recovery key and your backup settings stay as they are; only what you type to log in changes.

> **Good to know:** The list **Your backups** on [Backup and restore](help:backup-and-restore) shows only backups made under your present user ID. Backups made before the change can still be restored with **Restore from a file**.

## Password reset by an administrator

If a user has forgotten their password and lost their recovery key, an administrator can give them a temporary password. An administrator can also change another user's user ID this way.

### What the administrator does

1. Open **Settings › Users & security**.
2. Click **Reset…** on that user's line.
3. To change their user ID as well, type the **New user ID (optional)**. Otherwise leave it empty.
4. Type a **Temporary password** twice (**Temporary password** and **Again**). The usual password rules apply.
5. Click **Set**.
6. Tell the user the temporary password (and the new user ID, if you changed it), in person or by phone.

You cannot reset your own password this way; use **Change password** with your current password, or your recovery key.

### What the user sees

1. They log in with the temporary password (and the new user ID, if it changed).
2. The Hub shows **Choose your password** before anything else.
3. They type the **Temporary password**, then their own **New password** twice, and click **Save my password**.

From then on only they know their password. Their data, recovery key and settings are unchanged.

### When reset is available

Instead of **Reset…**, a user's line may say **reset after their next log-in**. Reset works only after that user has logged in once with Finance Hub 1.7 or newer, because that log-in stores the copy of their key that a reset needs. Users added with 1.7 or newer can be reset at once.

Every administrator can reset passwords. After an upgrade to 1.7, the first administrator who logs in turns password reset on. Other administrators get the ability when they next log in, or when an administrator who already has it opens **Users & security**. Someone who is made an administrator gets it straight away.

### What this means for privacy

Below the list of users, every user sees: **Administrators can reset another user's password (and so could open that user's data); everyone else's data stays private to them.**

That is the price of being able to help someone who has lost both their password and their recovery key: whoever is an administrator could give themselves access to another user's data. Give administrator access only to people every user trusts. See [Security and privacy](help:security-and-privacy#administrators-can-reset-passwords).

## Your recovery key

The **Protection** card shows when your recovery key was set. If you have lost it, or think someone else has seen it:

1. Click **New recovery key** and confirm.
2. The Hub shows the new key once. Write it down and store it safely.
3. Tick the box and click **Continue to the Hub**.

> **Important:** The old recovery key stops working at once. Only the new one can reset your password.

The **Protection** card also shows that your data is an encrypted file, encrypted with AES-256-GCM, and that the Hub is open to this computer only. See [Security and privacy](help:security-and-privacy).

## The idle lock

The Hub locks itself after 30 minutes without use. An administrator can change this under **Lock after (minutes idle, 0 = never)** and click **Save**. The setting applies to every user.

> **Tip:** Keep the idle lock on. 10 to 30 minutes is a good choice. 0 means the Hub never locks by itself, which is not safe if others use this computer.

Background mail checks don't count as use, so they don't keep the Hub unlocked.

## The Running card

The **Running** card tells you how the Hub is running:

- **Version**: for example Finance Hub 1.7.
- **Server**: normally the production server, running in the background.
- **Backups of your encrypted data**: how many version backups there are in the `backups` folder of your data folder, and the date of the newest. A backup is taken automatically the first time a new version starts. See [Backups, upgrades and troubleshooting](help:backups-upgrades-and-troubleshooting). Your own copies in OneDrive, Google Drive or another folder are on [Backup and restore](help:backup-and-restore).
- **Start with Windows: on** or **off**: an administrator clicks the button to switch it. This button appears only when the Hub was started from its shortcut. Anyone can also switch it in the tray menu.

## Removing unencrypted copies

Administrators see the card **Unencrypted copies in the app folder**. It lists files in the Finance Hub data folder that are not encrypted, such as databases from older versions, their backups, or uploaded statements left behind.

1. Tick the files to remove. All are ticked to begin with.
2. Click **Overwrite & delete ticked** and confirm.

The files are overwritten and then deleted. When the card says **None — only encrypted data is here**, a copy of the folder reveals nothing.

## Statement passwords

Open **Settings › Statement passwords**. This page lists the passwords that open your protected PDF statements. They are kept only inside your encrypted data.

### How passwords get here

You don't type them on this page. When **Add Statements** meets a PDF that none of the saved passwords opens, it asks you for the password. Leave **save on Passwords page** ticked, and the password is saved here, labelled with the bank and the name of the statement.

From then on, every new statement, from **Add Statements** or the [Mail inbox](help:mail-inbox), is tried with all your saved passwords. You never need to say which one belongs to which bank.

### Viewing or changing a password

1. Click a password's name to open it.
2. Click the eye button to show or hide the **Current Password**.
3. To change it, type the **New Password** and click **Save**.

Change a saved password when your bank starts using a new one.

> **Tip:** After changing a password, add the statement that failed again on **Add Statements**. Avoid **Reset & Reload from Folder** for this: it deletes all your transactions and your changes to them.

## Good to know

- Your name, your statement passwords and the Hub mailbox's app password are stored only inside your encrypted data.
- A password, once saved, is never written into the program files or the log.
- If several statements use the same password, it is enough to save it once.
