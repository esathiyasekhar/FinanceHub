# Reminders by mail
<!-- endpoints: reminders_page -->
<!-- icon: bi-bell -->

Let the Hub mail you a reminder the day before a payment is due, and a weekly report of everything due in the next two weeks. Mails go out on time even while the Hub is locked.

## What you get

### The reminder the day before

The day before a payment is due, the Hub sends one mail, at the time you choose (09:00 by default). It lists everything due that day:

- credit card bills that are not paid yet;
- EMIs and loan repayments;
- regular payments, such as insurance premiums or subscriptions;
- money you borrowed from people, when its due date comes.

The mail gives each payment's amount, the minimum due for cards, and the total. If several payments fall on the same date, they come together in one mail.

### The weekly report

Once a week (Sunday at 08:00 by default), the Hub sends a report with:

- the total due in the next 7 days and in the 7 days after;
- anything **Overdue**;
- the lists for **Next 7 days** and **The week after**;
- refunds you are still waiting for. See [Failed payments and refunds](help:failed-payments-and-refunds).

If nothing is due, the report says so.

## Before you start

Reminders are sent from the Hub's own mailbox. Set it up first on **Settings › Mail inbox**. See [Mail inbox](help:mail-inbox#setting-up-the-hubs-mailbox).

The reminders are only as good as your data. Add your statements regularly, and keep your card due dates, EMIs and regular payments up to date. See [Budgets, recurring and alerts](help:budgets-recurring-and-alerts).

## Setting up reminders

Open **Settings › Reminders & reports by mail**. In the **Settings** box:

1. Tick **Send reminders and reports**.
2. Under **Send to**, enter one or more e-mail addresses, separated by commas, for example `you@example.com, family@example.com`.
3. Tick **Reminder the day before each due date, at** and choose a time.
4. Tick **Weekly report on** and choose a day and a time.
5. Choose whether to show amounts (see below).
6. Click **Save**.

If an address is not valid, the Hub leaves it out and tells you which one.

> **Tip:** Add a family member's address too, so that someone else also knows when large payments are due.

### Amounts on or off

**Show amounts in the mails** is ticked by default. Untick it to send only what is due and when. The amounts are then replaced by "see the Hub", and the totals are left out.

> **Good to know:** Even without amounts, the mails name the cards, loans and payments. Send them only to addresses you trust.

### Outgoing mail server

Normally you can leave **Outgoing mail server** alone. The Hub sends through the server that belongs to its mailbox; for Gmail that is `smtp.gmail.com` on port 465. Change it only if your mailbox provider tells you to.

## Test mail and preview

- **Send a test report now** sends this week's report to your addresses at once, with "test" in the subject. The button works once the mailbox is set up and at least one address is saved.
- The **Coming up** box lists the mails prepared for the next two weeks, with the date and time each one will be sent. Click **Preview** to see a mail exactly as it will look.
- **Preview this week's report** shows a report built from today's data.
- The **Sent** box lists the mails that went out, and marks those **(sent late)**.

## Mails go out while the Hub is locked

You don't have to keep the Hub unlocked for reminders. This is how it works:

1. Whenever the Hub is unlocked, it prepares the mails for the coming two weeks. It prepares them again whenever your data changes, every hour, and after midnight.
2. The prepared mails are kept in memory. On Windows they are also saved in the `data` folder inside your Finance Hub data folder, protected by your **Windows login**. Nobody can read that file on another computer or from another Windows account.
3. A small timer in the Hub checks every minute and sends each mail when its time comes, even while the Hub is locked and, on Windows, even after a restart.

> **Important:** The mails show your data as it was when they were prepared. A payment you made after that, or one that is not yet in an imported statement, still shows as due. Log in at least once a week so that the mails stay up to date and new ones are prepared.

## The Hub must be running

Mails can only go out while Finance Hub is running, with its icon near the clock.

- Turn on **Start with Windows**, so the Hub starts whenever you log in to Windows. See [Getting started](help:getting-started#start-with-windows).
- Keep the computer on, and not asleep, at the times you chose.
- If you quit the Hub, nothing is sent until you start it again.

## Late sending

If the computer was off at the planned time, the Hub sends the mail as soon as it runs again, but only while it is still useful:

| Mail | Sent late until |
|---|---|
| Reminder | 12 noon on the due date |
| Weekly report | the end of the same day |

After that the mail is skipped. If sending fails, for example because the internet is down, the Hub tries again every 15 minutes within the same window. Each mail is sent only once.

## Good to know

- The Hub keeps a small record of which mails went out: only the time and the kind of mail, never names or amounts.
- If you untick **Send reminders and reports**, the prepared mails are erased.
- The reminders follow everything you have, whatever the Viewing filter shows.
- On a computer that is not Windows, prepared mails are kept only in memory. After a restart, log in once so they are prepared again.
