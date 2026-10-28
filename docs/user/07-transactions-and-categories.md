# Transactions and categories
<!-- endpoints: transactions, breakdown#breakdown, categories#managing-categories, rules_page#payee-rules -->
<!-- icon: bi-list-ul -->

Every transaction from your statements gets a name, a category, a book and a person. This chapter shows how to find transactions, correct them, and teach the Hub to get them right next time.

## The category tree

Categories have four levels: **Type › Head › Sub-head › Item**. For example, Expenses › Transport › Car › Fuel.

There are four Types:

| Type | Meaning |
|---|---|
| Income | Salary, fees, interest, dividends, refunds |
| Expenses | What you spend |
| Transfers | Card bill payments, moves between your own accounts, loan principal, ATM cash |
| Investments | Deposits, shares and mutual funds, money put into your business |

Transfers are kept out of income and expense totals, so a card bill paid from your bank is not counted twice.

The Hub sorts each transaction in this order:
1. your payee rules;
2. your own names, family, companies and clients from [People & entities](help:books-people-and-entities);
3. built-in rules for common Indian merchants, banks and charges;
4. if nothing matches, **To review**.

A transaction you edited by hand is never changed by rules again.

## Finding transactions

Open **Transactions** under Money in the sidebar. The line at the top shows how many transactions match, with money out and money in.

The quick buttons choose a period: this financial year, last year, **All time** or one of the last few months. The filters are:

- **From** and **To** dates;
- **Category (includes everything under it)**: pick a Head to see all its Sub-heads and Items;
- **Account**, **Entity** and **Person**;
- **In / out**;
- **Search (name, description, notes, amount)**, for example "swiggy" or "1500";
- **Show**, to see one Type only;
- **Only "To review"**.

Click **Apply**. **Clear** removes all filters. **CSV** downloads the list you see, and **Breakdown** opens the same filters as totals.

Tags on a row tell you more. **edited** means you changed it by hand. **rule** means a payee rule set it. **to review** means it still needs a category.

## Editing a transaction

Click a row to open **Rename & categorise**. The top shows the date, account, amount and the bank's own description.

1. **Name (how it shows everywhere)**: type a clear name, for example "Petrol – City Fuels".
2. **Category — Type › Head › Sub-head › Item**: pick the right heading. To make a new heading one level below it, type it in **…or add a new item under it**.
3. **Entity**: the book this belongs to, for example Personal or "ABC Traders Pvt Ltd".
4. **Person**: who the money was spent by or for.
5. **Notes (this transaction)**: anything you want to remember.
6. Under **Apply this to…**, choose one option, then click **Save**.

### Only this one, or all from this payee

- **Only this transaction** changes this row alone. Rules will never change it again.
- **All from this payee — past and future imports** saves a payee rule. It updates every matching transaction now, and every future import follows it.

For a rule, choose how to match:
- **Payee name is exactly** the cleaned payee name; or
- **Description contains** a piece of text you type (3 letters or more).

The dialog shows how many transactions match so far. You can also tick:
- **Also set the person for all of them**;
- **Also change matching ones I edited by hand**.

Notes are saved on this transaction only.

> **Tip:** Use "Description contains" for a UPI ID or a shop name that appears in many forms, for example "XYZ CONSULTING".

### Undo my edits

**Undo my edits** appears for a transaction you edited by hand. It removes your name and category and gives the row back to the rules. Your notes stay.

### The More menu

- **Link to its other side (transfer)**: see [Transfers and the director's account](help:transfers-and-directors-account).
- **Record as a loan with a person**: see [Loans with people](help:loans-with-people).
- **Expecting a refund for this**: see [Failed payments and refunds](help:failed-payments-and-refunds).

## Bulk actions

Tick the boxes on the left of several rows, or the box in the header for the whole page. A bar appears with **Set category**, **Set entity** and **Set person**. Choose what to change, leave the rest as "— keep —", and click **Apply to selected**. These count as hand edits.

If you have a client or employer set up as a payer, the bar also shows **Claim from …** and **Not reimbursable**. See [Reimbursements](help:reimbursements).

## To review

Transactions no rule could place go to Expenses › Uncategorised › To review (money out) or Income › Other Income › To review (money in). The **… to review** button on Transactions lists all of them. The Breakdown, Alerts and Reports pages also remind you.

> **Good to know:** A credit on a credit card that no rule recognises is treated as a merchant refund, not "To review".

## Breakdown

Open **Breakdown** under Money. It shows where money comes from and where it goes, for the period and filters you choose. The filters are **Entity**, **Person**, **Account** and **Show**.

- The tiles show **Income**, **Expenses**, **Saved** and **Invested**.
- The table shows Type › Head › Sub-head › Item. The **Type**, **Head**, **Sub-head** and **Item** buttons open the tree to that depth, and the arrows open one branch. Each line shows the number of transactions, **Out**, **In**, **Net** and its **Share**. Click a name to see its transactions.
- **By entity**, **By person** and **By account** show income, expenses and investments for each.
- **Month by month** shows one Type by Head, Sub-head or Item across months.

Net expenses are money out minus refunds. Net income is money in minus reversals.

**Export to Excel** saves the same figures with sheets for the breakdown, monthly expenses and income, entities and people, and every transaction.

## Managing categories

Open **Categories** under Settings. Hover over a row to see its buttons:

- **+ Head**, **+ Sub-head** or **+ Item** adds a heading under it;
- the pencil renames it;
- the arrows move it under another heading;
- the bin deletes it.

When you delete a heading, the Hub asks where its transactions and rules should go. You cannot rename or delete the four Types. A move that would make more than four levels is refused. The numbers show the transactions and rules for each heading. Click a name to see its transactions.

## Payee rules

Open **Payee rules** under Settings. Each rule shows when it applies ("payee is" or "contains"), the name shown, category, entity, person, and how many transactions it matches.

- The pencil opens the rule for editing. **Save** re-applies all rules.
- The bin deletes the rule. Its transactions go back to automatic categories.
- **Re-apply all rules** runs every rule again over your transactions. Hand-edited ones are kept, unless you tick **also reset my one-off edits**.

When two rules match, the one with the longer match text wins.

## Good to know

- The top-bar Viewing filter applies here too. A banner shows when it is on.
- Rules run every time you add statements, so you correct a payee only once.
