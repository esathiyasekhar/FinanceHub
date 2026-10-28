# Reimbursements
<!-- endpoints: reimb_page -->
<!-- icon: bi-receipt-cutoff -->

When you pay for a client's or employer's travel, stay or other costs and they pay you back later, that money is neither your spending nor your income. The Reimbursements page keeps it apart from your fees and tracks what is still owed to you.

## Fees and reimbursements are different

Suppose XYZ Consulting pays you a monthly fee, and you also book a hotel and flights for their site visit, which they repay.

| Money | What it is | Where it goes |
|---|---|---|
| The monthly fee | Your income | Income › Salary & Remuneration › Employers & clients › Consultancy fees |
| Hotel and flights you paid | Expense to claim | Transfers › Reimbursable › XYZ Consulting › Expense to claim |
| The money they pay back | Pay-back of your claim | Transfers › Reimbursable › XYZ Consulting › Reimbursement received |

Because the expense and the pay-back are transfers, they do not swell your spending, your income, your budgets or your ITR summary.

## Before you start

The client or employer must be set up as a payer.

1. Open [People & entities](/people).
2. In **Books, companies & clients**, add the name, for example "XYZ Consulting", with **Kind** set to **Client / payer**.
3. Under **Names on statements**, add the names the bank prints for them.

If no payer exists, opening Reimbursements takes you to People & entities first. See [Books, people and entities](help:books-people-and-entities).

## Marking expenses to claim

1. Open [Transactions](/transactions) and find the expenses, for example by date or with the search box.
2. Tick each expense.
3. In the bar that appears, click **Claim from XYZ Consulting**.

Only money going out is marked. The rows move to Transfers › Reimbursable › XYZ Consulting › Expense to claim.

If you marked something by mistake, tick it and click **Not reimbursable**. It goes back to its automatic category.

## The Reimbursements page

Open **Reimbursements** under Money in the sidebar. With more than one payer, use the tabs at the top to switch between them.

The tiles show:
- **Still to be paid back**: what you claimed and have not received, plus what you have not claimed yet;
- **Not claimed yet**: expenses marked but not in a claim;
- **Received**: pay-backs applied to claims.

### Making a claim

**Expenses not yet in a claim** lists the expenses you marked, all ticked.

To make a claim:
1. Untick anything that does not belong in this claim.
2. Type a **Claim title**, for example "Site visit, October".
3. Set **Submitted on** to the date you sent the claim.
4. Click **Create claim**.

Each claim then appears as a card with its status, date, total, amount received and a progress bar. Its status starts as "submitted", becomes "part paid" when some money arrives, and "paid" when it is fully received.

On a claim card:
- the cross on an expense ("Take out of this claim") moves it back to **Expenses not yet in a claim**;
- the cross on a payment un-applies it;
- the bin deletes the claim. Its expenses go back to "not yet claimed".

### Recording the pay-back

**Payments from XYZ Consulting** lists credits whose narration carries the payer's name. Each one is either your fee or a pay-back.

For each credit:
- To apply it to a claim, choose the claim in the list and click **Pay-back**. The Hub picks the claim whose balance matches the amount, or the oldest open claim. A payment can cover part of a claim.
- If the money is a pay-back but you have not made the claim yet, click **Pay-back later**. It moves to Reimbursement received and waits until you apply it.
- If you marked a credit as a pay-back and it was really your fee, click **Fee**. It is no longer treated as a pay-back and goes back to your income, with its category chosen by the automatic rules again.

Credits you leave alone stay as your income, usually Consultancy fees.

> **Tip:** Create the claim before the money arrives. The Hub then suggests the right claim for each payment, and the whole amount of the credit is applied to it.

## Reports

The top-bar **Report** menu on this page gives **Excel** and **PDF** files for the selected payer. They contain:
- a summary of what is still to be paid back, not yet claimed, and received;
- every claim with its expenses, amount received and balance;
- the claimed expenses, plus those not yet claimed.

Attach the PDF to your claim mail, or keep it for your records.

## Good to know

- The Hub finds payments from a payer by the first word of the payer's names, so keep **Names on statements** up to date.
- Marked expenses count as hand edits, so payee rules will not move them.
- Your own company paying you back for its expenses belongs on the director's account, not here. See [Transfers and the director's account](help:transfers-and-directors-account).
