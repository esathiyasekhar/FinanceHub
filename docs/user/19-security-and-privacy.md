# Security and privacy
<!-- endpoints: -->
<!-- icon: bi-lock -->

How Finance Hub protects your money data, in plain words, and the few things you should do yourself to keep it safe.

## Your data is encrypted

Everything you keep in the Hub lives in one database per user: accounts, transactions, categories, loans, statement passwords, the mail settings and even your name. On disk, that database exists only as an encrypted file in the `data` folder, with a random name ending in `.enc`.

### How the encryption works

- **AES-256.** The database is encrypted with AES-256-GCM, the same kind of encryption banks and governments use. It also detects tampering: if anyone changes even one byte of the file, the Hub refuses to open it.
- **Your own key.** Each user's database has its own random key. Users never see each other's data, and an administrator cannot open another user's data either.
- **Locked with your password.** That key is itself locked with a key made from your password. Making it takes 600,000 rounds of a standard method (PBKDF2-HMAC-SHA256), so someone who tries to guess your password has to do that work for every single guess.
- **Your password is never stored**, not even in scrambled form. The Hub only checks whether your password can unlock your key.
- **The recovery key** is a second way to unlock the same key. It is shown once, when it is made, and is not stored either.

The file `users.json` in the Finance Hub folder holds only the user IDs, their access, dates and the locked keys. It reveals nothing about your money.

### Open only while unlocked

When you log in, the Hub opens your database in the computer's memory. It never writes it to disk unencrypted. After every change, it saves the encrypted file again, and keeps the previous version as a spare in case the power fails while saving.

When you lock the Hub, quit it, or it locks itself after the idle time, the data is saved and closed, and the key is forgotten. A copy of the Finance Hub folder, a stolen laptop or a backup drive therefore shows only encrypted files.

## Only this computer can connect

The Hub's web server listens only on this computer (the address `127.0.0.1`). Other computers and phones on your Wi-Fi or office network cannot reach it, even if they know the address.

## Uploaded statements are erased

When you add a statement, your browser hands the file to the Hub, which keeps a temporary copy while you look at the preview.

- The preview itself is encrypted with your key.
- Once the statement is added, the temporary copy is overwritten with random data and deleted.
- Copies of previews you never added are erased the next time you log in, once they are a day old.
- Mail attachments are read and erased at once. Files that wait for your review are stored encrypted, and erased once handled.

> **Good to know:** On SSD drives, Windows may keep old copies of overwritten data in places no program can reach. Turning on BitLocker (see below) closes that gap.

The **Users & security** page lists any unencrypted copies left in the folder, such as old databases from earlier versions, so that you can remove them. See [Removing unencrypted copies](help:settings-and-users#removing-unencrypted-copies).

## Mail protections

- The Hub uses a mailbox of its own, never your main one.
- Its app password is kept inside your encrypted data.
- A mail is opened only if its sender is on your list and passed the sender check (DMARC or DKIM). Look-alike mails are rejected without being opened.
- Mails from other senders are never downloaded.
- The Hub never opens links or clicks anything in a mail.

See [Mail inbox](help:mail-inbox#privacy).

### The reminder outbox

To send reminders while the Hub is locked, the Hub keeps the prepared mails, the addresses to send to and the mailbox's app password in a file in the `data` folder. On Windows, this file is protected by your **Windows login**: it cannot be read on another computer or from another Windows account. The record of sent mails holds only times and the kind of mail, never names or amounts. See [Reminders by mail](help:reminders-by-mail#mails-go-out-while-the-hub-is-locked).

## What is never stored

- Your log-in password and your recovery key.
- Passwords or statement contents in the log file `logs\hub.log`.
- Any personal data in the program itself. Names, card numbers, account numbers and passwords are only ever in your encrypted data. Each release is checked for this before it is built.
- Mails from senders who are not on your list.

## What goes over the internet

- The Hub's pages load their layout, icons, fonts and charts from public websites (cdnjs.cloudflare.com and fonts.googleapis.com). Only these standard files are fetched. None of your data is sent.
- The mail inbox and the reminders talk to your mail provider, such as Gmail, over encrypted connections.
- Installing and upgrading download Python packages.

## What you should do yourself

The Hub's protection is only as strong as the password and the computer around it.

1. **Use a strong password.** At least 10 characters. A short sentence works well: long, and easy to remember. Don't reuse your Gmail or net banking password.
2. **Keep your recovery key safe.** On paper, with your important documents, or in a password manager. Without your password or the recovery key, nobody can open your data, and that includes you.
3. **Lock the Hub when you step away**, and keep the idle lock on.
4. **Protect your Windows account** with a password or PIN, and don't share it. Anyone who uses your Windows account while the Hub is unlocked can see your data.
5. **Turn on BitLocker** (Windows Pro) or **Device encryption** (many Windows Home laptops), from Windows Settings. It encrypts the whole disk, including any statement PDFs you keep yourself.
6. **Make backups away from this computer.** Copy the `data` folder and `users.json` to a USB drive or cloud storage now and then. They are encrypted, so this is safe. See [Backups, upgrades and troubleshooting](help:backups-upgrades-and-troubleshooting#backups).
7. **Don't keep plain statement PDFs lying around.** PDFs in your Downloads folder, or in a `statements` folder next to the Hub, are not encrypted by the Hub. Delete them once they are added, or keep them on an encrypted disk.
8. **Keep Windows and your browser up to date.**

## Questions

**Can the person who installed the Hub read my data?**
No. Only your password or your recovery key can open it. An administrator can remove your user, which erases your data, but cannot read it.

**What if someone copies my Finance Hub folder?**
They get encrypted files only. Without your password or recovery key they cannot open them.

**What if I lose both my password and my recovery key?**
Then the data cannot be opened by anyone. That is the price of real encryption, so keep the recovery key safe.
