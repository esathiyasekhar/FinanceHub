# Accounts and net worth
<!-- endpoints: accounts, account_detail, loans, networth_page#net-worth, dues_page#the-dues-calendar -->
<!-- icon: bi-wallet2 -->

Every bank account, card, loan, EMI, deposit, broker, wallet and asset you own lives on the Accounts page. From these the Hub works out your net worth and a calendar of what is due.

## Accounts by kind

Open **Accounts** in the sidebar. The tiles at the top show **Net worth**, **Assets**, **Liabilities** and **Monthly EMIs**. Below them, the tabs split your accounts by kind. The sidebar has a shortcut for each tab.

| Kind | What goes here | Counted as |
|---|---|---|
| Bank accounts | Savings, current, salary, NRE / NRO, overdraft | Asset (balance) |
| Credit cards | Credit, business and charge cards | Liability (outstanding) |
| Loans | Home, personal, gold, vehicle, education and other loans | Liability (outstanding) |
| EMIs | EMIs on a card, consumer durable EMIs, EMI letters | Liability (what is left to pay) |
| Deposits & schemes | FD, RD, PPF, EPF, NPS, Sukanya Samriddhi, bonds / SGB, MF folios | Asset (value) |
| Brokers & demat | Stock brokers and mutual fund platforms | Asset (holdings value) |
| Wallets & cash | Cash in hand, UPI wallets, prepaid, forex and gift cards | Asset (balance) |
| Other assets | Property, gold, vehicle, money you have lent | Asset (value) |

The **All** tab shows the first six accounts of each kind with an **Open** link. The year button next to the tabs (for example **FY 25-26**) chooses the year for the money in and out figures on each card.

A card for a credit card shows the outstanding, the limit, the utilisation, the last bill and its status: **Paid**, **Due**, **Part paid**, **Overdue** or **Not seen**. "Not seen" means the due date has passed, but the Hub has no later statement yet to show the payment.

> **Good to know:** Balances come from your latest statement or from a figure you typed, whichever is newer. An "old" tag means the last figure is more than 40 days old.

## Adding accounts by hand

Bank accounts, cards and loans are created for you when you add their statements (see [Adding statements](help:adding-statements)). Add the rest by hand.

To add an account:
1. Click **Add** and pick the kind, or click the dashed **Add …** tile on a tab.
2. Fill in the form. The fields change with the kind. For example, a card asks for **Credit limit (₹)**, **Statement (billing) day** and **Payment due day**. A deposit asks for **Amount invested (₹)**, **Interest rate (% p.a.)** and **Matures on**.
3. Choose the **Book** if the account belongs to your company, for example "ABC Traders Pvt Ltd". See [Books, people and entities](help:books-people-and-entities).
4. For banks, deposits, wallets and assets you can type a **Current balance (₹)** and its **As on** date.
5. Click **Add**.

For a loan, you can also give the EMI, **Total EMIs**, **EMIs paid**, **First EMI date** and **Outstanding now (₹)**. Tick **Bullet repayment** for a loan repaid in one go at the end, such as a gold loan. If the deposit's maturity amount is blank, the Hub estimates it with quarterly compounding and marks it "est.".

To change an account, click the pencil on its card and then **Save changes**. Renaming an account also renames it on its transactions, loans and statements. Moving it to another book moves its transactions too, except those you edited by hand.

### Updating a balance

Deposits, PPF, gold and property have no monthly statement. To update one, click **Update** on its card. For a card or loan without a statement, click **Outstanding**. Type the figure and the date, then click **Save balance**.

### EMIs

On the **EMIs** tab, click **EMI paid** each month if no statement updates the EMI for you. When all EMIs are paid, the card shows **Paid off**. EMIs read from card statements show "Updated from statements".

## The account detail page

Click an account's name or **Details** to open its page. The buttons at the top are:

- **Update balance** (or **Update outstanding**) and **Edit details**;
- **All transactions**, which opens Transactions for this account only;
- **Add statement**, which opens Add Statements;
- **Close account** (or **Re-open**).

The page shows a chart of the balance or outstanding over time, money in and out by month, and the latest 25 transactions. On the right you see card, loan or deposit details, the **Balance history**, the **Statements** read for this account and your notes. You can delete a balance you typed with its bin button. Balances from statements stay.

For a loan or a card with EMIs, **What if I prepay?** opens the prepayment calculator. See [Planning tools](help:planning-tools).

## Closing accounts

When you close a bank account or surrender a card, keep it in the Hub for its history.

To close an account:
1. Open its detail page.
2. Click **Close account** and confirm.

A closed account stays in your transactions and reports. It no longer counts in totals or net worth, and it leaves the top-bar Viewing filter. Find it again under the **Closed** tab on Accounts, where **Re-open** brings it back.

> **Important:** The bin button to delete an account appears only when it has no transactions. An account with transactions can only be closed.

## Net worth

Open **Net worth** in the sidebar, or click the Net worth tile on [Accounts](/accounts).

- **Net worth today** is assets minus liabilities, with the change since your first snapshot.
- **Assets** is what you own. **Liabilities** shows your debt-to-asset ratio.
- **History** charts net worth, assets and liabilities over time.
- **What you own** shows the mix of your assets.
- Below, every kind is listed with its accounts and their figures.

A snapshot is saved automatically each day you open Home, Accounts or Net worth. Click **Record now** to save one at any time.

> **Tip:** Before you look at net worth, choose **Everything** in the top-bar Viewing filter. Then all your books are counted.

## The dues calendar

Open **Dues calendar** under Home in the sidebar. It shows one month at a time. Use the arrows to move and **Today** to come back.

The calendar shows:
- card bills, from the last statement, or "expected" from the due day;
- loan EMIs and bullet repayments;
- EMIs on cards, shown for reference only, because they are part of the card bill;
- recurring payments you confirmed (see [Budgets, recurring and alerts](help:budgets-recurring-and-alerts));
- deposits that mature.

Click an entry to open its account.

On the right, **Next 30 days** adds up what you must pay from bank accounts and compares it with your bank balances. It says either "Short by ₹…" or "₹… spare". **Upcoming** lists each due item with its status and, for cards, the minimum due.

## Good to know

- The Hub takes the statement and due days of a card from its statements. Type them on the card only if they are missing.
- The money in and out on account cards follows the year button. Balances always show the latest figure.
- Payment reminders and the weekly report by e-mail use the same dues. See [Reminders by mail](help:reminders-by-mail).
