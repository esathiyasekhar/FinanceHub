# Users, security and statement passwords
<!-- endpoints: users_page, passwords_page -->
<!-- icon: bi-shield-lock -->

Manage who can use the Hub, change your password and recovery key, set the automatic lock, and look after the passwords that open your statements.

## Users & security

Open **Settings › Users & security**. The page has four parts: your name, the list of users, **Protection** and **Running**. Administrators also see **Unencrypted copies in the app folder**.

### Your name and your user ID

These are two different things:

- **Your name** is how the Hub greets you and what it shows at the bottom of the sidebar. You can change it at any time: type it and click **Save**. It is stored only inside your encrypted data.
- **Your user ID** is what you type to log in. It cannot be changed.

### Users and roles

Every user has their own encrypted data. Users never see each other's accounts, statements or settings. This suits a family where each person keeps their own money separately.

There are two kinds of access:

| Access | What they can do |
|---|---|
| **Administrator (can add / remove users)** | Everything a user can, plus add and remove users, change access, set the idle lock and remove unencrypted copies. |
| **User** | Use the Hub with their own data, change their own password and make a new recovery key. |

The first user, created at the first start, is an administrator. The Hub always keeps at least one administrator.

### Adding a user

Only an administrator can do this.

1. Below the list of users, fill in **Name**, **User ID (to log in)**, **Password** and **Again**.
2. Choose the **Access**: **User** or **Administrator**.
3. Click the add-user button.

The new user starts with empty data. The first time they log in, the Hub shows them their own recovery key. Ask them to store it safely.

> **Good to know:** Only one person can have the Hub open at a time. When another user logs in, the first user's data is saved and locked.

### Changing access or removing a user

- To change a user's access, an administrator picks the new value in the **Access** column. It is saved at once.
- To remove a user, an administrator clicks the bin button on that user's line and confirms. The user's encrypted data is erased for good. You cannot remove yourself.

### Changing your password

1. Click **Change password** on your own line.
2. Enter your **Current password**, then the **New password** twice.
3. Click **Change**.

Each user changes only their own password. If someone has forgotten theirs, they use their recovery key on the log-in page. See [Getting started](help:getting-started#if-you-forget-your-password).

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

- **Version**: for example Finance Hub 1.6.
- **Server**: normally the production server, running in the background.
- **Backups of your encrypted data**: how many backups there are, and the date of the newest. A backup is taken automatically the first time a new version starts. See [Backups, upgrades and troubleshooting](help:backups-upgrades-and-troubleshooting).
- **Start with Windows: on** or **off**: click the button to switch it. This button appears only when the Hub was started from its shortcut.

## Removing unencrypted copies

Administrators see the card **Unencrypted copies in the app folder**. It lists files in the Finance Hub folder that are not encrypted, such as databases from older versions, their backups, or uploaded statements left behind.

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
