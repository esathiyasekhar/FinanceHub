# Investments
<!-- endpoints: inv_portfolio, inv_stock#the-stock-page, inv_trades#trades-by-broker, inv_import#importing-broker-files, inv_brokers_page#holdings-by-broker, asset_types_page#asset-types -->
<!-- icon: bi-graph-up-arrow -->

Import your contract notes and holdings files, and the Hub builds your share portfolio with cost, profit and a tranche plan. It then suggests what to buy, add, trim or sell next.

## Importing broker files

Open **Import broker files** under Investments in the sidebar. The Hub reads:
- **contract notes** (PDF) from Upstox and SBI Securities, plus Zerodha and other brokers through a general reader for the standard SEBI layout. These give trades with their charges;
- **tradebook and holdings exports** (CSV, XLSX or XLS), for example from Zerodha Console or Upstox;
- a **CDSL or NSDL CAS**, or your DP's holding statement. These give the holdings of each demat account (see [Demat check](help:demat-check)).

Margin statements, weekly ledgers and NSE / BSE balance letters are recognised, but have nothing to import.

To import files:
1. Under **1 · Add files**, choose one or more files.
2. If the PDFs have a password, type it in **PDF password (PAN) if needed**.
3. Click **Read**.
4. Under **2 · Check and import**, check each file. It shows the trades (new and already in the Hub), holdings, charges, and whether **totals reconcile**. Click **Show rows** to see every row.
5. Choose the **broker** for each file if it is not filled in.
6. Click **Import ticked files**.

Trades already in the Hub are skipped, and a file imported before is refused. A contract note whose totals do NOT reconcile is left unticked; check it first. In **Imported files**, the bin removes a file with the trades and holdings it added.

### The PAN password

Broker and depository PDFs usually open with your PAN. With **save it** ticked, the Hub keeps the password with your other [statement passwords](/passwords), and tries saved passwords on every file. If a file still needs a password, a box asks for it again. Type it and click **Open**.

## The portfolio

Open **Portfolio & plan**. The buttons at the top are **Import broker file**, **Trades**, **Add stock to plan** and **Refresh prices**.

- The broker buttons show one broker's holdings. The type buttons show one asset type.
- The tiles show **Current value**, **Unrealised P&L** with realised profit, your **Core / Satellite** split against its target, and the **Capital for % limits**.
- The table lists each stock with bucket, sector, type, quantity, average cost, price, value, P&L, weight, a row of tranche dots, and the **Next** step.

Cost is the weighted average of your buys, including charges. If a holdings file shows a different quantity, the row shows "file: …".

If you sold shares bought before your first imported file, a warning lists them. Add the opening holding on the Trades page so cost and profit are right.

**Refresh prices** fetches the latest prices when your PC supports it; if not, the Hub tells you, and prices come from your files or the price you type.

## The tranching plan

Each stock is bought in steps called tranches. The rules are in **Tranching rules (TF Journal)** at the bottom of the portfolio:

| Rule | Default |
|---|---|
| Planned equity capital (₹) | 0, which means use the current portfolio value |
| Tranches per stock (max) | 8 |
| Core stock limit (% of capital) | 8 |
| Satellite stock limit (% of capital) | 5 |
| Sector cap (% of capital) | 8 |
| Core share of portfolio (%) | 70 |
| Satellite share of portfolio (%) | 30 |
| Trim when over the limit by (% points) | 1 |

One tranche is the stock limit × capital ÷ number of tranches. For example, with ₹10,00,000 capital, a Core stock may hold up to ₹80,000, in eight tranches of ₹10,000. Change the figures and click **Save rules**.

### Suggestions

| Next step | Meaning |
|---|---|
| BUY | Start the stock with tranche 1 |
| ADD | Buy the next tranche |
| TRIM | The stock has grown above its limit; sell the excess |
| SELL | Exit plan; sell one tranche at a time |
| WAIT | Waiting for a price move or a number of days |
| BLOCKED | No room: sector cap or Core / Satellite share is full |
| SET | Set Core or Satellite, or a price, first |
| HOLD | Fully invested or paused |

**Suggested next steps** lists the BUY, ADD, TRIM and SELL suggestions. Choose a broker, or "any broker", and click **Accept**. The suggestion becomes an instruction.

### Instructions

**Instructions** lists what you have decided to do. An open instruction is marked done on its own when a matching trade is imported. Click the tick ("Mark done") to mark it done by hand, or the cross ("Cancel") to cancel it.

## The stock page

Click a stock's name. The page shows your holding, value, P&L and weight, and its **Asset type**.

**Tranche plan** shows the tranche ladder and the next step. Change **Qty** or **Limit price** if you like, choose the **Broker**, and click **Accept as instruction**.

Under **Plan for this stock** you can set:
- **Core / Satellite**;
- **Sector**;
- **Plan status**: Active — build up, Paused — no suggestions, Exit — sell in tranches, or Watch — not bought yet;
- **Next tranche when**: any time, after the price falls or rises by the **Step %** from your last buy, or after a number of **Days**;
- **Price now (₹)** and **Notes / thesis**.

Click **Save plan**. The stock's trades, holdings statements and instructions are listed below.

To plan a stock you do not own yet, click **Add stock to plan** on the portfolio. It starts on "watch" and gets a BUY suggestion.

## Trades by broker

Open **Trades**. Filter by broker, side, asset type, dates or stock, and choose **Grouped by broker** or **One list**. Each broker shows trades bought, sold and charges. **Report** gives Excel or PDF.

To add a trade or an opening holding:
1. Click **Add trade / opening holding**.
2. Choose the **Broker**, **Date**, **NSE symbol**, **Side**, **Qty** and **Price**. Give the **ISIN** too, so it joins the same stock from your contract notes.
3. Click **Add**.

For shares held before your first import, add one Buy at your average price. The bin deletes a trade.

## Holdings by broker

**Holdings by broker** shows what you hold through each broker: bought minus sold through that broker, valued at the latest price. Each broker shows value, P&L, realised profit, trades and charges. **By asset type** shows the mix. The top-bar **Report** menu gives trades and holdings as Excel or PDF.

## Asset types

Open **Asset types**. Each holding gets a type from its ISIN and name:

| Type | How it is found |
|---|---|
| Equity shares | ISIN INE… with security code 01 |
| Preference shares | Code 04 |
| Bonds & NCDs | Codes 07–13, or NCD / bond in the name |
| InvITs / REITs | Codes 23 / 25, or a known name |
| ETFs | ETF or BEES in the name |
| Mutual funds | ISIN INF… |
| Govt. securities | ISIN IN0…, or G-Sec / SDL / T-Bill |
| Sovereign Gold Bonds | SGB in the name |

To change a type, pick another in the list. The Hub keeps your choice. Choose **back to automatic** to undo it. When the Hub sees, for example, warrants or rights entitlements, it offers **Suggested new types** with an **Add** button. To make your own type, use **Add a type** with a name, words to recognise and a colour.

## Good to know

- The portfolio can feed the wealth planner. See [Planning tools](help:planning-tools).
- Capital gains for your ITR are on Reports. See [Reports and ITR](help:reports-and-itr).
