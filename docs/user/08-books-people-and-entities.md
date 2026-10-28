# Books, people and entities
<!-- endpoints: people_page -->
<!-- icon: bi-people -->

Tell the Hub who you are, who your family members are, which companies you own and who pays you. It uses these names to sort transactions automatically and to keep your personal and company money apart.

## The People & entities page

Open **People & entities** under Settings in the sidebar. The page has three parts:

- **Your name (shown in the Hub)** at the top, with **Save**. This is only a display name.
- **People — who the money was spent by / for** on the left.
- **Books, companies & clients** on the right.

Everything you type here stays in your encrypted database.

## Personal and company books

A **book** is a set of accounts you keep separately. **Personal** is always there. If you run a company, add it as a book.

To add a company book:
1. In **Books, companies & clients**, type a short name in the last row, for example "ABC Traders".
2. Set **Kind** to **Book (company)**.
3. In **Names on statements**, type how the bank prints the company name, separated by commas. For example: "ABC TRADERS PRIVATE LIMITED, ABC TRADERS PVT LTD".
4. Click **Add**.

What a book does:

- When you add a statement whose account holder matches the book's names, the account goes into that book. Its transactions belong to the company. You can also set the **Book** on an account by hand (see [Accounts and net worth](help:accounts-and-net-worth)).
- Money from your company into a personal account becomes Income › Business Income › Own business › Transfers from business.
- Money from you to your company becomes Investments › Own business › Capital & loans to business › Transfers to business.
- Courier, electronic components, and software or cloud bills are booked to your first company book.
- Money moving between your company and you builds the director's account. See [Transfers and the director's account](help:transfers-and-directors-account).

## Payers: clients and employers

A **Client / payer** is someone who pays you, such as an employer or a client paying consultancy fees, for example "XYZ Consulting".

To add a payer:
1. Type the name in the last row of **Books, companies & clients**.
2. Set **Kind** to **Client / payer**.
3. Add the names printed in bank narrations under **Names on statements**.
4. Click **Add**.

Money received with a payer's name becomes Income › Salary & Remuneration › Employers & clients › Consultancy fees, named after the payer. A payer is also who you claim expenses from on the [Reimbursements](/reimbursements) page. See [Reimbursements](help:reimbursements).

**Other** keeps a name for tagging transactions, with no automatic rule.

> **Good to know:** The Txns number links to the Breakdown for that book or payer.

## Your own name variants

Banks print your name in many ways: "R KUMAR", "RAJESH KUMAR R", "KUMAR RAJESH". The Hub needs all of them to spot transfers between your own accounts, for example a NEFT from your SBI account to your HDFC Bank account.

To add your name variants:
1. In **People**, find the row **Self**.
2. In **Names on statements**, type every form of your name, separated by commas.
3. Click **Save** on that row.

Transactions that carry one of these names become Transfers › Own accounts › Between own accounts, so they are not counted as income or spending. In a company account, your name also helps the Hub suggest drawings and capital links.

> **Tip:** Use names of at least four letters. Short pieces such as "RK" are ignored, because they would match too many unrelated narrations.

## Family members

Add each family member who spends with an add-on card or to whom you send money.

To add a person:
1. In the last row of **People**, type the name, for example "Meena".
2. In **Names on statements**, type how statements print it, for example "MEENA R, R MEENA".
3. Click **Add**.

What happens next:
- Payments to that person become Expenses › Family & Personal › Transfers to family › Family members, tagged with that person.
- Card transactions made on an add-on card carry the cardholder's name. When the name matches, the transaction is tagged with that person.

**Names found on your statements** lists every cardholder name the Hub has seen and who it was tagged as. Use it to spot variants you have not added yet.

The Txns number links to that person's transactions.

## How this drives automatic classification

Every time you save a person, a book or a payer, the Hub re-sorts all transactions you have not edited by hand. It does the same each time you add statements.

The order of decisions is:
1. your payee rules (see [Transactions and categories](help:transactions-and-categories));
2. card bill payments, EMIs, bank charges and loan account entries;
3. the names on this page: yours, your family's, your books and your payers;
4. the built-in rules for merchants;
5. To review.

To change a name later, edit it in its row and click **Save**. Its transactions, rules and accounts are updated.

To remove one, click its bin button:
- a removed person's transactions show as Self;
- a removed book's transactions become Personal, and its accounts lose their book.

You cannot remove Self or Personal.

## The Viewing filter

The funnel button in the top bar is the Viewing filter. It normally reads **All**. Use it to see one part of your money at a time:

- **Everything**: all books and accounts;
- **Books**: Personal or one company (shown when you have more than one book);
- **Bank accounts**, **Credit cards**, **Loans**, **Deposits**, **Wallets** and **Assets**: a single account;
- **Brokers**: money moved to and from one broker, and its trades.

When the filter is on, a banner says "Showing only …" on every page. Click **Show everything ×** to switch it off.

The choice stays while you move between pages. Transactions, Breakdown, Accounts, Budgets, Loans with people and the top-bar **Report** menu all follow it. The **Personal** book shows everything not tagged to a company book.

> **Important:** The Personal and company views work only when accounts and transactions carry the right book. Add your companies here before adding their statements.

## Good to know

- A transaction's book appears as **Entity** on the Transactions page. You can change it for one row, for a whole payee, or for many rows at once.
- Nothing about you is written into the program. Your names, family and companies come only from this page.
