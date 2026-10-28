# Adding statements
<!-- endpoints: import_page -->
<!-- icon: bi-cloud-arrow-up -->

Bring your bank and credit card statements into the Hub on the **Add Statements** page. You always see a preview first, with a balance check, and nothing is saved until you click **Add**.

## What you can add

Open **Add Statements** from the top of the sidebar. It accepts:

- **PDF** statements from any bank or card, including password-protected ones;
- **CSV**, **XLSX** and **XLS** files that some banks let you download from net banking.

> **Good to know:** Broker contract notes and CDSL / NSDL statements (CAS) go to **Import broker files** instead. See [Investments](help:investments).

### The readers

The Hub has a dedicated reader for each bank it knows, listed in the box **Read by Statement Reader** on the right:

| Bank | Statements |
|---|---|
| HDFC Bank | Credit cards; savings account; SmartEMI letter |
| State Bank of India | Savings, current and loan accounts; consolidated statement; net banking and YONO Business statements |
| SBI Card | Credit cards |
| Axis Bank | Credit card; savings account; EMI conversion letter |
| ICICI Bank | Credit cards |
| Standard Chartered | Credit cards |
| South Indian Bank | SIB One credit card |
| Bank of Baroda | Combined statement (savings and loans) |
| Central Bank of India | Savings account (net banking PDF) |

A statement from any other bank is read by a **generic reader**. Its preview says "No dedicated reader for this bank / card yet". Check its rows carefully. It is ticked for adding only if its balances reconcile.

## Adding statements, step by step

1. Drag your files onto the box **Drop statement files here, or click to choose**, or click the box and pick them.
2. Check the list of files. Use **×** to remove one, or **Clear** to start again.
3. Click **Read & preview**. The Hub reads every file and shows a preview card for each one.
4. Look at each card (see below). Tick the ones you want and untick the others.
5. Click **Add … selected**.

**3 · Added** then shows what was added from each file.

## Saved statement passwords

Most bank PDFs are protected with a password. The Hub tries every password saved on the **Statement passwords** page, so you usually don't have to type anything.

If none of them works, the card shows a lock and a password box:

1. Type the PDF's password.
2. Leave **save on Passwords page** ticked, so it is tried automatically next time.
3. Click **Open**.

> **Tip:** The bank's mail that came with the statement usually explains the password. It is often a mix of letters from your name and your date of birth, a customer ID or the last digits of the account. For CAS statements it is usually your PAN in capital letters.

See [Statement passwords](help:settings-and-users#statement-passwords) to view or change saved passwords.

## Reading the preview

Each preview card shows what the Hub found, before anything is saved.

- **Title**: the statement's name, the bank, the reader used and the saved password that opened it.
- **Key figures**: **Period**, **Closing balance** (for a card, **Total due** and **Due date**), **Opening**, **Rows in file**, **New for Hub** and **Debits / Credits**.
- **Accounts**: which Hub account the rows go to, and how it was matched.
- **EMIs & loans**: loans the statement mentions (see below).
- **Show … rows**: the full list of transactions with date, description, amount, category and account.

### The balance check

Statements with printed balances are checked:

- for a bank account: opening balance plus credits minus debits must equal the closing balance;
- for a card: previous balance minus payments plus purchases must equal the total due.

The badge tells you the result:

| Badge | Meaning |
|---|---|
| **Balances reconcile ✓** | Every rupee is accounted for. Safe to add. |
| **Balances do NOT reconcile** | Some rows were missed or misread. The card is not ticked. Look at the rows before you decide. |
| **No balance check** | The file has no printed balances, as with most CSV and Excel files. Check the totals yourself. |

## Duplicates

You can safely add the same statement twice, or statements that overlap. The Hub never adds a transaction twice.

- **Same file again**: the card shows **Already imported** with the date, and it cannot be ticked.
- **Same statement, downloaded again**: a statement for the same accounts and the same period counts as already imported, even if the file is different.
- **Overlapping rows**: a row with the same account, date, amount and direction as one already in the Hub is greyed out with the note "already in Hub". Only the new rows are added.

A card that has nothing new is not ticked.

## New accounts

The Hub matches each statement to one of your accounts by:

1. the last four digits of the card or account number;
2. distinctive words in the card's name;
3. or the only account you have of that bank and type.

If nothing matches, the preview says **new account will be created**. When you add the statement, the Hub creates the account and names it after the card or the bank, with the last four digits, for example "SBI Savings 1234". If the account holder is one of your companies, for example "ABC Traders Pvt Ltd", the account goes into that company's book.

> **Tip:** To avoid a duplicate account, add the account on the **Accounts** page first with its last four digits, or rename the new one afterwards. See [Accounts and net worth](help:accounts-and-net-worth).

## Loans found in statements

Card statements and loan statements often list EMIs and loans. The preview shows each one with a tag:

- **new loan**: it will be added to your loans and EMIs;
- **update**: the Hub will update it, for example "EMIs paid 5 → 6" or the outstanding amount;
- **no change**: nothing new.

An older statement never overwrites figures from a newer one. EMI letters (such as a SmartEMI letter) only set up the loan; their instalment schedule is not added as transactions.

You find these loans under **Accounts › EMIs** and **Accounts › Loans**.

## The statements you have added

The box **Statements added** on the right lists your recent statements, newest first. Each line shows the balance check (**OK**, **MISMATCH** or **n/a**), the period, and how many of the file's rows were added.

To remove a statement, click its **×** button and confirm. The Hub deletes the statement and the transactions it added. You can then add the file again.

> **Important:** Removing a statement does not remove accounts or loans it created. Remove those on the **Accounts** page if you no longer need them.

### Danger Zone

The red box at the bottom right holds three tools for starting over. Use them with care:

- **Reset & Reload from Folder**: deletes all transactions and the statement history, then adds every file found in the `statements` folders: one in your Finance Hub data folder, in the program folder or next to it. The folders it found are listed under the button.
- **Clear this year's data**: deletes all transactions of the financial year you choose, so its statements can be added again.
- **Delete All Transactions**: deletes every transaction and the statement history. Accounts, EMIs, loans and passwords are kept.

All three also remove the categories and notes you set on those transactions.

## Good to know

- Statements that arrive in the [Mail inbox](help:mail-inbox) and need a look open on this page when you click **Review**.
- The uploaded copy of a statement is overwritten and deleted once it is added. Copies of previews you never added are erased the next time you log in, once they are a day old.
