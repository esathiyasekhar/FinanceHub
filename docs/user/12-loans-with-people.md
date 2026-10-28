# Loans with people
<!-- endpoints: pl_page -->
<!-- icon: bi-person-lines-fill -->

Hand loans to friends and relatives are easy to forget. Record each one with how the money moved, and the Hub keeps track of what is still owed, matches the bank entries, and warns you when a loan is overdue.

## The page at a glance

Open **Loans with people** under Money in the sidebar. The tiles at the top show:
- **You have lent**: money still to come back to you;
- **You have borrowed**: money you still have to repay;
- **Net**: whether others owe you, or you owe others.

Your loans are listed on the left. **Record a loan** is on the right, with **People & their bank details** below it.

If the top-bar Viewing filter is set to one book, only that book's loans are shown.

## Recording a loan

1. Under **Record a loan**, set **Direction** to **I lent** or **I borrowed**.
2. Choose the **Book**: Personal, or your company if the company lent the money.
3. Type the **Person**. Names you used before are offered as you type.
4. Enter the **Amount** and the **Date**.
5. Choose the **Mode**: Cash, UPI, NEFT, IMPS, RTGS, Cheque, Bank transfer (other), Card or Other.
6. Under **Our account**, choose the account the money left from, or "— cash —".
7. If agreed, set **Repay by** and **Interest % p.a.**, and note the **Purpose**.
8. If you paid by transfer, fill in **Their bank details**: **Bank**, **Account no.**, **IFSC**, **UPI id**, **Phone** and **UTR / ref**.
9. Click **Save**.

> **Tip:** Keep the UTR number or UPI reference from your banking app. It proves the payment if there is ever a dispute.

### Starting from a bank entry

If the money already shows in a statement, start from the transaction itself.

1. Open [Transactions](/transactions) and click the entry.
2. Click **More**, then **Record as a loan with a person**.

The form opens with "From bank entry" at the top, and the amount, date, account and direction filled in. Add the person and the other details, then click **Save**. The bank entry is linked to the loan straight away.

## Recording what happens next

Each loan card shows "Lent to" or "Borrowed from", the person, the amount still outstanding out of the total given, the purpose and the interest rate. It also lists every movement.

To add a movement:
1. On the loan's card, choose the **Entry**:
   - **Repaid**: money paid back;
   - **Gave more** (or **Borrowed more**): a further amount;
   - **Interest**: interest paid or received;
   - **Waive / write off**: an amount you forgive or that will never come back.
2. Enter the **Amount**, **Date** and **Mode**, and the **Our account** it went to or came from.
3. For a bank transfer, add **Their account no.**, **IFSC** and the **UTR / UPI ref.**
4. Click **Add**.

The outstanding amount is what was given, less what was repaid and waived. Interest is shown separately and does not reduce it.

When a loan is fully repaid, the Hub closes it and says it is "fully settled". You can also click **Mark settled** at any time, or **Re-open** a settled loan. The cross on a movement removes it. The bin at the bottom of a card deletes the loan and all its movements.

## Matching bank entries

A movement made by UPI, NEFT, IMPS, RTGS or cheque should have a matching entry in your bank statement.

To match a movement:
1. Click **find bank entry** next to it.
2. The Hub lists bank or wallet entries in the same book with the same amount, within a week, and with money moving the right way.
3. Click **This one** next to the right entry.

A matched movement shows the link symbol and the account name. If nothing is found, add the statement first (see [Adding statements](help:adding-statements)).

Matching also gives the bank entry the right category, so a loan is not counted as spending or income:

| Movement | You lent | You borrowed |
|---|---|---|
| Money given or received | Transfers › Loans with people › Lent › Money lent | Transfers › Loans with people › Borrowed › Money borrowed |
| Repayment | Transfers › Loans with people › Lent › Repaid to you | Transfers › Loans with people › Borrowed › Repaid by you |
| Interest | Income › Investment Income › Interest › Interest from people | Expenses › Loans & EMI › Interest › Interest to people |

When you remove a matched movement or delete the loan, the bank entry goes back to its automatic category.

## Due dates and overdue loans

If you set **Repay by**, the card shows "due" with the date. Once the date has passed with money still outstanding, it shows "overdue since" with the date. Talk to the person, then record a repayment, or waive what will not come back.

> **Good to know:** The **Repay by** date, interest rate and purpose are fixed when you record the loan, so fill them in carefully. Interest is not calculated for you. Record each interest payment as an **Interest** entry when it happens.

## People and their bank details

**People & their bank details** keeps one entry per person. It is created when you first record a loan with them. Details you give later fill gaps but do not overwrite what is already there.

To update a person's details:
1. Click their name to open the entry.
2. Change **Name**, **Phone**, **Bank**, **Account no.**, **IFSC**, **UPI id** or **Notes**.
3. Click **Save**.

Renaming a person here renames them on their loans too.

## Reports

The top-bar **Report** menu gives **Excel** and **PDF** files. They list every loan, with book, person, direction, start and due dates, amount, repaid, outstanding and status. They also list every movement, with mode, accounts, IFSC or UPI ID, and reference.

## Good to know

- A company lending to its director belongs on the director's account, not here. See [Transfers and the director's account](help:transfers-and-directors-account).
- Money lent can also be shown in net worth. Add it as an asset of type "Money lent (receivable)" on Accounts. See [Accounts and net worth](help:accounts-and-net-worth).
