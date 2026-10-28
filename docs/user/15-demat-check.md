# Demat check
<!-- endpoints: demat_page -->
<!-- icon: bi-shield-check -->

Your shares are held at a depository, CDSL or NSDL, not at your broker. The Demat check compares what the depository says you hold with what your broker's trades say you should hold, so you can catch missing contract notes, bonus shares and errors early.

## Depositories are not brokers

- **CDSL** and **NSDL** are the depositories. They hold your securities in demat accounts.
- Your **broker**, for example Zerodha or Upstox, only buys and sells for you. It is usually also the **DP** (depository participant) that opened your demat account.

So every broker normally has one demat account behind it. A demat account is identified by:

| Depository | Account number |
|---|---|
| CDSL | 16-digit BO ID (8-digit DP ID + 8-digit client ID) |
| NSDL | DP ID ("IN" + 6 digits) + 8-digit client ID |

The Hub shows only the last four digits on screen, for example "•••• 1234".

## Demat accounts and linking them to brokers

Open **Demat check (CDSL / NSDL)** under Investments in the sidebar.

Demat accounts are created for you when you import a CAS. To add one by hand:
1. Click **Add demat account**.
2. Choose the **Depository**.
3. Type the **DP (usually the broker)** name and choose the **Linked broker**.
4. Type the **BO ID (CDSL, 16 digits)**, or the **DP ID** and **client ID (8 digits)**.
5. Add the **Holder(s)** and any **Notes**, then click **Save**.

The Hub links a demat account to its broker from the DP name, or from the demat number you typed on the broker under Accounts › Brokers & demat. If it cannot tell, choose the broker in the **broker** list on the account's header. The pencil edits an account. The bin removes it with its statement holdings. Your trades are not touched.

## Importing a CAS or the DP's holding statement

Get the depository statement:
- the **CAS** (Consolidated Account Statement) from CDSL or NSDL, which lists every demat account in your PAN; or
- the holding statement from your DP.

To import it:
1. Open [Import broker files](/investments/import) and add the PDF. It usually opens with your PAN.
2. Check the preview. It shows each demat account found, with its number of holdings and its broker.
3. If no account number was read, choose the demat account in the list.
4. Click **Import ticked files**.

If you import both the NSDL and the CDSL CAS for the same date, the holdings are not counted twice. See [Investments](help:investments) for more on importing.

> **Tip:** Import a CAS every month, soon after it arrives by e-mail. Then compare it with the contract notes for the same month.

## What the check compares

For each security in a demat account, the Hub compares:
- **Demat**: the quantity in the latest depository statement;
- **Broker trades**: what you bought minus what you sold through the linked broker, counting trades settled by the statement date;
- **Settling**: trades done but not yet settled on the statement date;
- **Broker stmt**: the broker's own holdings file, if you imported one.

**Difference** is Demat minus Broker trades. **Demat value** uses the price in the statement.

### T+1 settlement

Shares bought on a trading day reach your demat account on the next working day. This is called T+1. The Hub skips Saturdays and Sundays when it works this out. It does not know exchange holidays, so a trade made just before a holiday may show as still settling.

Trades after the statement date are not counted. The note says how many there were.

## The meaning of each status

| Status | Meaning | What to do |
|---|---|---|
| matches | The demat agrees with the broker trades. A note may say "+N still settling" or "includes trades of the statement day". | Nothing |
| not in broker trades | The demat holds it, but no trades through the broker | Bought elsewhere, IPO, rights or transfer-in, or contract notes not imported yet |
| missing in demat | The trades say you hold it; the demat has none | Sold or moved out (sale not imported?), pledged, or held in another demat |
| quantity differs | Both have it, in different quantities | Buys or sales not imported, or a bonus or split |
| broker statement differs | Trades and demat agree, but the broker's holdings file does not | Check the broker's file date |
| no broker linked | Nothing to compare with | Link the demat account to its broker |

### Bonus and split hints

When the demat holds an exact multiple of the traded quantity, the hint names the likely reason. For example: "demat holds 2× — looks like a bonus 1:1 or split 1:2; add the extra shares on the Trades page as a buy at price 0". Other ratios cover bonus 2:1, bonus 1:2, and splits 1:4, 1:5 and 1:10. If the demat holds a fraction instead, the hint suggests a consolidation or sales not imported.

To record a bonus or split, add the extra shares as a **Buy** at price **0** on [Trades](/investments/trades), dated on the bonus or split date. The quantities then match, and your average cost per share comes down as it should. See [Investments](help:investments).

## Account-wise and broker-wise views

The tiles show the **Demat holdings value**, how many holdings are **Matching**, how many **Differ / to check**, and how many accounts are **Not linked to a broker**.

- **By demat account** shows one card per demat account. The header shows the depository, DP, masked number, holder and statement date. Below are the counts ("match", "to check", "differ", "not compared"), the demat value, the value of the differences, and the table. Rows that differ come first.
- **By broker** adds together all demat accounts linked to each broker. It is useful when one broker has more than one demat account. If the statements have different dates, it warns "different statement dates". It also tells you when a broker has no linked demat account or no depository statement yet.

Click a security's name to open its stock page.

## The report

The top-bar **Report** menu on this page gives **Excel** and **PDF** files with three parts:
- **Summary**: each demat account with its broker, date, number of securities, matches, checks, differences, value and value of differences;
- **By demat account**: every row with all quantities, status and note;
- **By broker**: the same, grouped by broker.

Keep it with your records, or send it to your broker when you raise a query.

## Good to know

- When the top-bar Viewing filter is set to a broker, only that broker's demat accounts are checked.
- The check uses only the latest statement of each demat account.
