# Failed payments and refunds
<!-- endpoints: refunds_page -->
<!-- icon: bi-arrow-counterclockwise -->

A UPI payment that fails and comes back, or an order you return, should not count as spending. The Hub pairs failed payments with their reversals and refunds with their purchases. It also tracks money you are still waiting to get back.

## The Failed & refunds page

Open **Failed & refunds** under Money in the sidebar. Each time you open it, the Hub looks through the last 400 days for new matches.

The tiles at the top show:
- **Waiting to get back**: the amount, the number of purchases, and how many are overdue;
- **To confirm**: suggestions waiting for you;
- **Refunds received**: refunds you confirmed;
- **Failed & reversed**: pairs kept out of your totals.

The tabs are **To confirm**, **Awaiting refund**, **Confirmed & closed** and **Not matches**.

## How failed-and-reversed pairs are found

A pair is suggested when:
- money goes out of an account and the same amount comes back to the same account;
- the money comes back on the same day or up to 10 days later;
- the credit says it is a reversal (words such as REV, REVERSAL, FAILED, RETURN, DECLINED or CHARGEBACK), or both sides carry the same 12-digit UPI or IMPS reference number.

**Why / status** explains each match, for example "same reference number, 1 day later".

When you confirm a pair, both sides go to Transfers › Failed & reversed › Failed payments › Reversed by bank. Neither side then counts as spending or income.

## Refunds matched to purchases

A refund is matched to the purchase it pays back. The Hub looks for:
- a credit that says REFUND, RFND, REVERSAL, CHARGEBACK, MERCHANT CREDIT, RETURN CREDIT or CANCELLATION, and shares merchant words with a purchase, such as AMAZON or MAKEMYTRIP;
- or a credit with the same reference number as the purchase;
- or a credit that fits a purchase you are waiting on.

The refund must come within 120 days after the purchase and must not be more than the purchase. A refund in the same account is preferred. Part refunds are allowed. The reason then says, for example, "part: 1,200 of 1,500".

When you confirm a refund, the credit moves into the purchase's category. If a ₹2,000 order in Shopping is refunded, your Shopping spending goes down by ₹2,000.

## Confirming and rejecting suggestions

On the **To confirm** tab:
1. Check **Money out** and **Money back**.
2. Click the tick to confirm, or the cross ("Not a match") to reject.

A rejected pair moves to **Not matches** and is not suggested again.

> **Good to know:** Before you confirm, a card refund usually sits in Income › Refunds & Rewards › Refunds. Confirming moves it to the purchase's category, so it no longer counts as income.

## Awaiting refund

Mark a purchase you expect to get back: a returned order, a cancelled booking, or a failed payment the bank has not reversed.

To mark a purchase:
1. Open [Transactions](/transactions) and click the purchase.
2. Click **More**, then **Expecting a refund for this**.
3. The dialog confirms "Added to Awaiting refund".

This item appears only for money going out.

The Hub also finds debits that say FAILED, DECLINED or UNSUCCESSFUL and were not reversed within three days. It suggests them on **To confirm** as "Awaiting refund". Click the tick ("Yes, I am waiting for this") to start tracking.

On the **Awaiting refund** tab, each purchase shows the amount expected and "waiting N days". After 15 days it says "follow up", and the tile counts it as overdue. That is the time to call the merchant or the bank.

When a matching credit arrives in a statement, the Hub suggests it on **To confirm**. Confirming it settles the waiting item.

### Match by hand

If the refund came with a different description, match it yourself.

To match a refund:
1. On **Awaiting refund**, click **Match** on the purchase.
2. A list shows credits after the purchase date, with credits in the same account first.
3. Pick the right credit and click **Match**.

The refund then moves into the purchase's category, just as when you confirm a suggestion.

### Close

If no refund is coming, for example the merchant refused, click the cross ("Stop waiting (no refund coming)"). The purchase stops being tracked and moves to the **Confirmed & closed** tab, marked *closed*. It still counts as spending in its category. If the money turns up after all, click the undo arrow there to wait for it again.

## Undo

On the **Confirmed & closed** tab, the undo button puts the categories back to what they were before you confirmed.

- An undone pair or refund moves to **Not matches**.
- An undone refund for an awaited purchase goes back to **Awaiting refund**.

## Effect on totals and categories

| What you confirm | Money out | Money back | Effect |
|---|---|---|---|
| Failed & reversed | Transfers › Failed & reversed | Transfers › Failed & reversed | Neither counts as spending or income |
| Refund | Stays in its category | Moves to the purchase's category | That category's spending goes down |

Breakdown, budgets, Insights and reports all use these categories. A refunded purchase therefore no longer makes a budget look overspent.

Confirmed rows count as hand edits, so payee rules do not change them later.

## In the weekly report mail

If you receive the weekly report by e-mail, it has a section **Refunds you are waiting for**. It lists each awaited purchase with the date you paid and how many days you have been waiting. See [Reminders by mail](help:reminders-by-mail).

## Good to know

- The Hub never changes anything until you confirm.
- Add statements regularly. A refund can only be matched once its credit is in the Hub.
