# Transfers and the director's account
<!-- endpoints: links_page, link_manual#linking-by-hand, director_page#the-directors-account -->
<!-- icon: bi-link-45deg -->

When money moves between your own accounts, the Hub pairs the two sides as a transfer, so it is not counted as income or spending. Movements between you and your company build the director's account.

## How transfers are found

Open **Transfers & links** under Money in the sidebar. Each time you open it, the Hub looks for new pairs among transactions that are not linked yet:

- a debit in one account and a credit in another for the same amount (within ₹1);
- the credit comes up to two days before or six days after the debit;
- the match is stronger when the narration names the other account, for example the card's bank, or the last digits of your account number.

Each transaction is used in one link only. A badge shows how many new suggestions were found.

## Kinds of link

Each link has a kind. The kind decides how both sides are categorised.

| Kind | Typical example |
|---|---|
| Card bill payment | HDFC Bank savings pays the SBI Card bill |
| Between own accounts | NEFT from your SBI account to your HDFC Bank account |
| Loan repayment | Savings account pays the home loan account |
| Money to broker | Savings account funds your Zerodha account |
| Money from broker | Upstox pays out to your bank |
| You → your company (capital / loan) | You put money into ABC Traders Pvt Ltd |
| Company → you (drawings / paid for you) | The company pays you or pays a bill for you |
| Company repays you (loan / expenses you paid) | The company returns money you lent it |
| Company → you (remuneration) | Director's salary from the company |

The Hub picks a kind from the two accounts. A company account paying a personal account is "Company → you". A personal account paying a company account is "You → your company". A payment into a card is a card bill payment. Check the kind before you confirm.

## Confirming and rejecting

The page has five tabs: **Suggested**, **Confirmed**, **Transfers without a link**, **Flows** and **Rejected**.

On **Suggested**, each row shows **Money out**, **Money in**, the amount, the **Kind** and **Why** it was suggested. Strong matches are ticked already.

To confirm links:
1. Change the **Kind** on any row that is wrong.
2. Click the tick on a row to confirm it alone, or tick several rows and click **Confirm ticked**.

To reject a suggestion, click the cross ("Not a transfer"). It moves to **Rejected** and is not suggested again.

When you confirm a link, both sides get the categories for that kind, and they count as hand edits. For example, both sides of a card bill payment go to Transfers › Card bill payments. Money to a broker goes to Investments › Market › Stocks & mutual funds.

To undo a confirmed link, click the cross on the **Confirmed** tab ("Undo link"). Both sides go back to automatic categories, and the link moves to **Rejected**. On **Rejected**, the cross ("Forget") deletes the link, so it may be suggested again.

> **Tip:** Add statements for all your accounts and cards. The more accounts the Hub has, the more pairs it can find.

## One-sided links

Sometimes only one side is in the Hub, for example a payment to a card whose statement you do not add. The Hub still suggests a link when:

- the narration names one of your cards or accounts;
- the money goes to or comes from a broker or a clearing corporation;
- a personal account receives money with your company's name;
- a company account pays you, or receives money from you, with your own name in the narration.

These rows show the other side by name with "statement not in the Hub". Confirm them in the same way. Your name variants come from Self on [People & entities](/people).

## Linking by hand

When the Hub has not found a link, make one yourself.

To link a transfer:
1. On [Transactions](/transactions), click the transaction. Or open the **Transfers without a link** tab, which lists transfers that have no other side yet.
2. Choose **More › Link to its other side (transfer)**, or click **Link** on the tab.
3. The **Link a transfer** page lists transactions in your other accounts with the same amount within 15 days. Choose the kind next to the right one and click **Link**.
4. If the other side is not in the Hub, use **Other side not in the Hub**. Type the account, broker or person, choose the **Kind**, and click **Link**.

A link made by hand is confirmed at once.

## Flows

The **Flows** tab adds up confirmed links by source and destination, for example "HDFC Bank savings → SBI Card". It shows where your money moved over time.

The top-bar **Report** menu on this page gives **Transfers — Excel** and **Transfers — PDF**. They contain the flows and every confirmed link.

## The director's account

If you own a company, open **Director’s account** under Money. It needs a company book on [People & entities](help:books-people-and-entities). Without one, the Hub sends you there first.

The page is a running account between the company and you, seen from the company's side:

- **Balance** reads "ABC Traders owes you" or "you owe ABC Traders";
- **You put in** is capital, loans and company expenses you paid;
- **You took out** is drawings, repayments and bills the company paid for you.

What counts:

| Entry | Effect on the balance |
|---|---|
| You → your company (capital / loan) | The company owes you more |
| Company expense paid from your personal account | The company owes you more |
| Company → you (drawings / paid for you) | The company owes you less |
| Company repays you | The company owes you less |
| Company → you (remuneration) | Listed, but no change |

A company expense paid personally is an expense transaction in a Personal account whose **Entity** is the company. Tag it on Transactions.

To see one period, choose **From** and **To** and click **Show**. An **Opening balance** line then shows the balance before the period. With more than one company, choose it under **Company**.

The **Report** menu gives the account as Excel or PDF, for your accountant.

> **Important:** Only confirmed links count. Keep the **Suggested** tab on Transfers & links clear so the director's account is complete.

## Good to know

- The Viewing filter applies to the lists on Transfers & links.
- Transfers are left out of income and expense totals in Breakdown, Insights, budgets and reports.
