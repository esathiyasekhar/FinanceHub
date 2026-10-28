# Security and privacy
<!-- endpoints: -->
<!-- icon: bi-lock -->

How Finance Hub protects your money data, in plain words, and the few things you should do yourself to keep it safe.

## Your data is encrypted

Everything you keep in the Hub lives in one database per user: accounts, transactions, categories, loans, statement passwords, the mail settings and even your name. On disk, that database exists only as an encrypted file in the `data` folder inside your Finance Hub data folder, with a random name ending in `.enc`.

### How the encryption works

- **AES-256.** The database is encrypted with AES-256-GCM, the same kind of encryption banks and governments use. It also detects tampering: if anyone changes even one byte of the file, the Hub refuses to open it.
- **Your own key.** Each user's database has its own random key. Users never see each other's data. The one exception is password reset by an administrator; see [Administrators can reset passwords](#administrators-can-reset-passwords).
- **Locked with your password.** That key is itself locked with a key made from your password. Making it takes 600,000 rounds of a standard method (PBKDF2-HMAC-SHA256), so someone who tries to guess your password has to do that work for every single guess.
- **Your password is never stored**, not even in scrambled form. The Hub only checks whether your password can unlock your key.
- **The recovery key** is a second way to unlock the same key. It is shown once, when it is made, and is not stored either.

The file `users.json` in the data folder holds only the user IDs, their access, dates, the locked keys and each user's backup settings (which folder, how often, when the last backup was made). It reveals nothing about your money. See [What users.json and a backup contain](help:backup-and-restore#what-usersjson-and-a-backup-contain).

### Open only while unlocked

When you log in, the Hub opens your database in the computer's memory. It never writes it to disk unencrypted. After every change, it saves the encrypted file again, and keeps the previous version as a spare in case the power fails while saving.

When you lock the Hub, quit it, or it locks itself after the idle time, the data is saved and closed, and the key is forgotten. A copy of the data folder, a stolen laptop or a backup drive therefore shows only encrypted files.

## Administrators can reset passwords

Since version 1.7, an administrator can give another user a temporary password, for example when that user has forgotten their password and lost their recovery key too. See [Users and security](help:settings-and-users#password-reset-by-an-administrator).

How it works, in short:

- Finance Hub has one extra lock for the whole installation, the **reset key**. Each user's data key is also stored locked with it.
- Only administrators hold the reset key, and each administrator's copy is itself locked with that administrator's own password.
- To reset a password, the administrator's reset key unlocks the user's data key, which is then locked again with the temporary password. The user must choose their own password at the next log-in.

The consequence: **an administrator could open any other user's data.** Resetting the password is the visible way; an administrator who knows how could also do it without resetting, so that the user would not notice. Every user sees a short note about this on **Users & security**.

- Give administrator access only to people whom every user of this Hub trusts with their data.
- Users who are not administrators cannot reset anyone's password and cannot open anyone else's data.
- If you are the only administrator and lose both your password and your recovery key, nobody can reset it for you.

## Only this computer can connect

The Hub's web server listens only on this computer (the address `127.0.0.1`). Other computers and phones on your Wi-Fi or office network cannot reach it, even if they know the address.

## Uploaded statements are erased

When you add a statement, your browser hands the file to the Hub, which keeps a temporary copy while you look at the preview.

- The preview itself is encrypted with your key.
- Once the statement is added, the temporary copy is overwritten with random data and deleted.
- Copies of previews you never added are erased the next time you log in, once they are a day old.
- Mail attachments are read and erased at once. Files that wait for your review are stored encrypted, and erased once handled.

> **Good to know:** On SSD drives, Windows may keep old copies of overwritten data in places no program can reach. Turning on BitLocker (see below) closes that gap.

The **Users & security** page lists any unencrypted copies left in the data folder, such as old databases from earlier versions, so that you can remove them. See [Removing unencrypted copies](help:settings-and-users#removing-unencrypted-copies).

## Mail protections

- The Hub uses a mailbox of its own, never your main one.
- Its app password is kept inside your encrypted data.
- A mail is opened only if its sender is on your list and passed the sender check (DMARC or DKIM). Look-alike mails are rejected without being opened.
- Mails from other senders are never downloaded.
- The Hub never opens links or clicks anything in a mail.

See [Mail inbox](help:mail-inbox#privacy).

### The reminder outbox

To send reminders while the Hub is locked, the Hub keeps the prepared mails, the addresses to send to and the mailbox's app password in a file in the `data` folder of your data folder. On Windows, this file is protected by your **Windows login**: it cannot be read on another computer or from another Windows account. The record of sent mails holds only times and the kind of mail, never names or amounts. See [Reminders by mail](help:reminders-by-mail#mails-go-out-while-the-hub-is-locked).

## Backups in the cloud

Backups made on **Settings › Backup & restore** are written into a folder on this PC; if it is your OneDrive or Google Drive folder, their app uploads the file. The Hub itself never connects to OneDrive or Google Drive.

- The backup holds your database exactly as it is on disk: encrypted with AES-256. The cloud company sees only scrambled data.
- It opens only with the password or recovery key you had when it was made.
- The file name shows your user ID and the date of the backup.

> **Important:** An old backup opens with the password of its time. If someone learned an old password of yours, delete the backups made while that password was valid.

See [Backup and restore](help:backup-and-restore#backups-stay-encrypted).

## Problem reports

**Settings › Report a problem** sends a report only when you click one of its send buttons, and you see the exact text first.

- It contains what you typed, and, if you leave them ticked, technical details (versions, counts, features) and recent error lines from the log.
- In the log lines, numbers of four or more digits, e-mail addresses, PAN numbers and folder paths are masked before you see them.
- Nothing is taken from your financial data except a few counts, and no files are attached.
- What you type yourself is sent as you typed it, so don't type account numbers or passwords.

See [Reporting a problem](help:reporting-a-problem#what-is-sent-and-what-is-never-sent).

## What is never stored

- Your log-in password and your recovery key.
- Passwords or statement contents in the log file `logs\hub.log` in your data folder.
- Any personal data in the program itself. Names, card numbers, account numbers and passwords are only ever in your encrypted data. Each release is checked for this before it is built.
- Mails from senders who are not on your list.

## What goes over the internet

- The Hub's pages load their layout, icons, fonts and charts from public websites (cdnjs.cloudflare.com and fonts.googleapis.com). Only these standard files are fetched. None of your data is sent.
- The mail inbox and the reminders talk to your mail provider, such as Gmail, over encrypted connections.
- Installing and upgrading download Python packages.
- The OneDrive or Google Drive app on your PC uploads your backups, if you keep them in its folder. They are encrypted.
- A problem report goes to the Finance Hub support address, only when you send it.

## What you should do yourself

The Hub's protection is only as strong as the password and the computer around it.

1. **Use a strong password.** At least 10 characters. A short sentence works well: long, and easy to remember. Don't reuse your Gmail or net banking password.
2. **Keep your recovery key safe.** On paper, with your important documents, or in a password manager. Without your password or the recovery key, only an administrator's password reset can bring your data back. If you are the only administrator, nobody can open it, and that includes you.
3. **Lock the Hub when you step away**, and keep the idle lock on.
4. **Protect your Windows account** with a password or PIN, and don't share it. Anyone who uses your Windows account while the Hub is unlocked can see your data.
5. **Turn on BitLocker** (Windows Pro) or **Device encryption** (many Windows Home laptops), from Windows Settings. It encrypts the whole disk, including any statement PDFs you keep yourself.
6. **Make backups away from this computer.** On **Settings › Backup & restore**, choose OneDrive, Google Drive or a USB drive and turn on automatic backups. They are encrypted, so this is safe. See [Backup and restore](help:backup-and-restore).
7. **Choose administrators carefully.** An administrator could open other users' data. See [Administrators can reset passwords](#administrators-can-reset-passwords).
8. **Don't keep plain statement PDFs lying around.** PDFs in your Downloads folder, or in a `statements` folder next to the Hub, are not encrypted by the Hub. Delete them once they are added, or keep them on an encrypted disk.
9. **Keep Windows and your browser up to date.**

## Questions

**Can the person who installed the Hub read my data?**
Installing the Hub gives nobody access. But every administrator of the Hub can reset your password, and so could open your data. Users who are not administrators cannot. See [Administrators can reset passwords](#administrators-can-reset-passwords).

**What if someone copies my data folder or a backup?**
They get encrypted files only. Without a password or recovery key that opens them, they cannot read them.

**What if I lose both my password and my recovery key?**
Ask an administrator to give you a temporary password. If there is no other administrator who can do that, the data cannot be opened by anyone. That is the price of real encryption, so keep the recovery key safe.
