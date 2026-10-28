# Mail inbox
<!-- endpoints: mail_page -->
<!-- icon: bi-envelope -->

Give the Hub its own Gmail address and let your bank, card and broker statements arrive there. The Hub reads them with your saved passwords, adds the ones that pass every check, and keeps the rest waiting for you.

## How it works

1. Your bank sends a statement to your usual mailbox, as it does today.
2. A filter in your mailbox forwards statement mails to the Hub's own mailbox.
3. While the Hub is open, it reads that mailbox every 15 minutes, or when you click **Check now**.
4. Mails from senders on your list are checked and their attachments are read with the same readers as **Add Statements**.
5. Statements that pass every check are added automatically. The others wait under **Waiting for you**.

It reads bank and card statements, broker contract notes and CDSL / NSDL statements (PDF, CSV or Excel).

## Setting up the Hub's mailbox

You do this once. Open **Settings › Mail inbox**.

### 1. Create a Gmail address only for the Hub

Create a new Gmail account, with an address such as `yourname.statements@gmail.com`. Don't use your main mailbox.

### 2. Turn on 2-Step Verification and make an app password

1. Sign in to the new Gmail account.
2. Open **Google Account › Security** and turn on **2-Step Verification**.
3. Open **App passwords** and create one, for example named "Finance Hub".
4. Gmail shows a password of 16 letters, once. Copy it.

Make sure IMAP is on: **Gmail settings › Forwarding and POP/IMAP**.

> **Important:** The app password lets a program read this one mailbox. Never use your normal Gmail password here, and never give the app password to anyone else.

### 3. Enter the details in the Hub

Under **Mailbox settings**:

1. **Hub mailbox address**: the new Gmail address.
2. **App password**: paste the 16 letters. Spaces don't matter.
3. Leave **IMAP server** (`imap.gmail.com`), **Port** (993) and **Folder** (INBOX) as they are.
4. Tick **Check automatically while the Hub is open**.
5. Leave **Import automatically when every check passes** ticked if you want statements added without asking.
6. Click **Save**, then **Test connection**. You should see "Connected to the mailbox".

Other settings you can change:

| Setting | What it means |
|---|---|
| **Label for handled mails** | The Gmail label the Hub puts on mails it has handled. Default: FinanceHub. |
| **Check every (minutes)** | How often the Hub looks for new mail. 5 to 1440; default 15. |
| **First check looks back (days)** | How far back the very first check reads. Default 60 days. |

### 4. Forward statement mails from your own mailbox

1. In **your own** Gmail, open **Settings › Forwarding and POP/IMAP** and add the Hub's address as a forwarding address.
2. Gmail sends a confirmation code to the Hub's mailbox. Sign in there, open that mail and confirm.
3. Back in your own Gmail, create a filter that forwards only statement mails. Build it from the domains in your sender list, for example `from:(hdfcbank.net OR sbicard.com) has:attachment`.
4. Choose **Forward it to** the Hub's address.

## The sender list

**Senders to read** lists the domains the Hub trusts, one per line. It starts with common Indian banks, card issuers, brokers, depositories and registrars. A domain also covers its sub-domains, so `bank.in` covers every regulated bank's `.bank.in` address.

- Mails from domains on the list are opened and read.
- Mails from any other sender are only listed under **Other senders**. They are never downloaded.
- If a genuine sender is missing, click **Read this sender** next to its mail. Its mails are read on the next check.

### My forwarding addresses

Put your own address under **My forwarding addresses** only if you will also forward mails by hand. Such mails are read, but they always wait for you: after a hand forward, the Hub cannot confirm who really sent the original. Forwarding by filter keeps the original sender, so those mails are verified.

## The sender check

Fake mails often pretend to come from a bank. Before opening a mail, the Hub asks your mail server's own verdict:

- the mail must pass **DMARC** for the sender's domain, or carry a **DKIM** signature from that domain;
- with Gmail, only the check that Google's own server added is trusted.

A mail that fails is marked **Failed sender check** and is never opened. Treat it as suspicious in your own mailbox too.

## What is added automatically, and what waits

A statement is added automatically only when every one of these is true:

- **Import automatically when every check passes** is ticked;
- the sender passed the sender check (not forwarded by hand);
- if the file is protected, one of your saved passwords opens it;
- the balances reconcile;
- the account is already in the Hub;
- it is not a duplicate and it has something new.

For contract notes, the broker must be known and the totals must reconcile. For CDSL / NSDL statements, a demat account must be found.

Anything else waits, with the reason, for example "none of the saved passwords opens it", "new account — confirm it once" or "balances do not reconcile".

## The tabs

| Tab | What it shows |
|---|---|
| **Statements** | Every statement mail and what happened to it. |
| **Waiting for you** | Files that need your decision. |
| **Alerts** | Mails without an attachment, kept for later. |
| **Other senders** | Mails from senders not on your list, and mails that failed the sender check. |

## Review, Retry and Dismiss

Each file under **Waiting for you** has three buttons:

- **Review**: opens the usual preview. A bank or card statement opens on **Add Statements**; a contract note or CDSL / NSDL statement opens the broker import preview. Check it and add it as usual. See [Adding statements](help:adding-statements).
- **Retry** (the circular arrows): reads the file again. Use it after you save a missing password or add the missing account. Retry adds the file if every check now passes.
- **Dismiss** (the cross): you don't need this file. The Hub erases its stored copy.

**Clear history** at the bottom of the **Statements** and **Other senders** tabs empties the list of handled and ignored mails. Waiting files and alerts are kept.

## Alerts kept for later

Mails without an attachment, such as debit, credit, UPI and card alerts, are kept under **Alerts**, encrypted. Click the text button next to an alert to read it. A later version of the Hub will turn these into provisional entries that the monthly statement then confirms.

## Privacy

- The Hub never clicks anything in a mail and never opens links.
- Mails stay **unread** in the mailbox. Handled mails get the **FinanceHub** label.
- Mails from senders not on your list are never downloaded; the Hub reads only the sender, subject and date.
- The app password is stored only inside your encrypted data and is never shown again.
- Files waiting for you, and alert texts, are stored encrypted with your key. They are erased once you add, dismiss or clear them.

## Good to know

- Automatic checks run only while the Hub is unlocked and open in a browser tab. A tab hidden behind other tabs, or a minimised window, does not check. **Check now** always works.
- The Hub reads up to 30 statement mails per check. If more are waiting, it says so and reads them on the next check.
- The same mailbox sends your [Reminders by mail](help:reminders-by-mail).
