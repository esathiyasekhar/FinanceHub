# Reporting a problem
<!-- endpoints: support_page -->
<!-- icon: bi-bug -->

Tell the Finance Hub team when something doesn't work or a statement is read wrongly. You see exactly what will be sent before anything leaves your PC, and your statements, transactions and passwords are never included.

## Opening the page

There are three ways to open **Report a problem**:

- **Settings › Report a problem** in the sidebar, or [Report a problem](/support);
- the **Report a problem** button on the Help page, next to **User manual (PDF)**;
- the **Report this problem** button on the **Something went wrong** page (see [Error references](#error-references)).

Reports go to the Finance Hub support address, **amirthamilserve@gmail.com**. The page shows this address at the top.

## Filling in the form

| Field | What to write |
|---|---|
| **Short summary** | One line, for example "Credit card statement shows no transactions". Needed before you can send. |
| **Where in the Hub** | The page, for example "Add Statements". |
| **How bad** | **Small annoyance**, **Something does not work** or **I cannot use the Hub**. |
| **What happened** | What you saw, including any message the Hub showed. |
| **Steps to make it happen again** | What you clicked, in order: 1. …, 2. … |
| **What you expected** | What should have happened instead. |
| **Your e-mail for a reply (optional)** | Where the answer should go. If the Hub mailbox is set up, its address is filled in; change it to the address you read. |

Below the form are two ticks, both on to begin with:

- **Include technical details (version, Windows / Python version, features, counts)**
- **Include recent error lines from the log (numbers, e-mails and paths masked)**

They help to find the cause quickly. Untick either one if you prefer not to send it.

## What is sent, and what is never sent

### Always

- Everything you typed in the form — with numbers of 4 or more digits, e-mail addresses, PANs and file paths masked, just like in the log lines.
- The date and time of the report, and the version of Finance Hub in the subject line.

> **Important:** Long numbers, e-mail addresses and PANs in what you type are masked automatically, but names are not. Never type passwords or your recovery key, and leave out names you would rather not share.

### With "Include technical details"

- the versions of Finance Hub and its Statement Reader;
- the versions of Windows and Python;
- whether Finance Hub is installed (program and data folders apart) or a portable folder;
- which web server runs the Hub;
- which features are turned off;
- how many accounts, transactions and statements you have: the counts only, never their contents;
- whether the mail inbox is set up, and whether it reads automatically.

### With "Include recent error lines from the log"

Up to 60 recent warning and error lines from the Hub's log, with the error details that belong to them. Before they are shown or sent, the Hub masks:

- every number of four or more digits (also with commas, such as 12,34,567), so account numbers, card numbers and amounts disappear;
- e-mail addresses;
- PAN numbers;
- folder paths, such as your Windows user folder. File names stay, without the folder.

The log itself never contains passwords or statement contents.

### Never

- anything else from your encrypted data: no statements, transactions, balances or account details, only the counts above;
- passwords: not your log-in password, statement passwords, recovery key or the Hub mailbox's app password;
- files: not your database, `users.json`, your backups or the log file itself. The report is plain text.

## The preview

The right half of the page, **What will be sent**, shows the exact text of the report. After you change the form or the ticks, click **Update preview** to see the new text.

Read it before you send. If a line shows something you would rather keep to yourself, untick the box that added it, or change what you typed.

## Three ways to send

| Button | What it does |
|---|---|
| **Send report** | Sends the report straight from the Hub, through the Hub's own mailbox, to the support address. A reply goes to the address in **Your e-mail for a reply**. When it worked, the Hub says **Thank you — your report was sent** and opens the Help page. |
| **Open in my mail program** | Opens a new mail in your usual mail program, already addressed to the support address, with the subject and text filled in. Check it and click Send there. |
| **Save as a file** | Saves the report as `FinanceHub_problem_report.txt`. Attach it to a mail to amirthamilserve@gmail.com from any mail account. |

- **Send report** needs the Hub mailbox (**Settings › Mail inbox**, see [Mail inbox](help:mail-inbox)). Without it the button is greyed out; use one of the other two.
- If sending fails, the Hub says **Could not send** with the reason. Use **Open in my mail program** or **Save as a file** instead.
- **Open in my mail program** shortens a long report to about 1,800 characters, because mail programs accept only so much this way. For a long report, use **Save as a file** and attach the file.

## Error references

When something unexpected goes wrong, the Hub shows a page **Something went wrong** instead of the page you wanted. Your saved data is safe and stays encrypted.

The page shows an **Error reference**: eight letters and numbers, for example `3FA9C21B`. The same reference is written in the log, right after the details of the error.

1. Click **Report this problem** on that page.
2. The report form opens with the error reference filled in. The recent error lines then end with the error that has this reference.
3. Add a summary and what you were doing, then send the report.

> **Tip:** Mention the error reference if you write to support in another way. It lets the team find exactly that error in the details you sent.

## Questions

**Will I get an answer?**
If you filled in **Your e-mail for a reply**, the answer goes there.

**Can I see the log myself?**
Yes. Right-click the tray icon and choose **Open logs folder**; the file is `hub.log`. See [Backups, upgrades and troubleshooting](help:backups-upgrades-and-troubleshooting#the-log-file).
