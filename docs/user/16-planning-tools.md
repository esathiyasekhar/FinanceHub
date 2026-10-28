# Planning tools
<!-- endpoints: planner#the-wealth-planner, tools_page#card-and-loan-tools -->
<!-- icon: bi-compass -->

The wealth planner shows how a Core + Satellite portfolio can compound towards a goal, and checks your progress each year. The card and loan tools help you use your cards wisely and decide which loan to prepay.

## The wealth planner

Open **Wealth planner** under Plan in the sidebar. It works on two pots: **Core** (steady, larger share) and **Satellite** (higher growth, smaller share). Each grows at its own rate, with no rebalancing between them.

### Users and saving

The bar at the top shows the **User**. Each user has their own plan, goal and yearly records, so the whole family can plan here.

- **Save plan** saves this user's inputs and goal. "unsaved changes" reminds you to save.
- **New user** asks for a name, a target corpus, the number of years and the year the plan started.
- **Edit user & goal** changes those details.
- **Users** lists everyone. It also has **Export all users (JSON)** and **Import users (JSON)**. Import works with the desktop Compounding Calculator's files; the newer copy of each user wins.
- **Reset page** resets the tab you are on: the Core engine goes back to the standard plan, the goal to the saved goal, and unsaved year-end entries are discarded. **Print** prints the page.

### Core engine

Set the **Portfolio strategy**:
- **Core allocation**, the share that goes to Core;
- **Core CAGR** and **Satellite CAGR**;
- **Horizon**, in years.

Then fill in the contributions under **Self**, and under **Spouse** if you tick **Include spouse (same core / satellite pots)**:
- **Initial lump sum ₹** and **Monthly SIP ₹**;
- **Yearly step-up**, as a percentage or as a fixed ₹ amount added each year, and the **Last step-up in year**;
- **SIP runs for (years)**, plus months.

The results update as you type:
- the corpus at the end of the horizon, how much you invested, and how much compounding added;
- **Portfolio IRR** and **Blended CAGR**;
- **Money doubles every**;
- the Core and Satellite split and the **Growth path** chart (**Linear** or **Log**).

With a spouse included, a strip shows what the spouse's money adds and how much sooner the corpus is reached.

### Goal & schedule

1. Set the **Target corpus ₹**, or click a quick button such as **₹5 Cr** or **₹10 Cr**.
2. Set the **Deadline** in years from the start of the plan.
3. Try a different **Blended CAGR to assume**. **Back to my CAGR** resets it.

The tiles show when the goal is reached, the **Monthly SIP to hit it on time**, and the **CAGR needed with your SIP**. **What a different CAGR does** compares rates side by side; click a row to assume that rate. The **Doubling ladder** and the **Year-by-year schedule (60 years)** follow, with **CSV** and **Copy** buttons.

### Annual review

Plan year 1 is the financial year that starts in April of the year the plan began. Year 2 is the next financial year, and so on.

To record a year:
1. In **Year-end records**, find the year.
2. Type the **Actual invested**, **Core value** and **Satellite value** on 31 March, or click **Fill from Hub**.
3. Click **Save**.

**Fill from Hub** takes the year's buys minus sales from your imported trades. It values your holdings at the end of that year, or today for the current year, split by each stock's Core or Satellite setting. Stocks without that setting are left out, and a note names them. Set it on each stock's page (see [Investments](help:investments)). Always check the figures before you save.

The tiles then show where you stand: projected corpus, when the goal is reached, the return needed from here, and the SIP needed. The chart compares the original plan with your actual path. **Delete all records** clears this user's records.

### Youngster lab

This tab shows young people the cost of waiting. Set the **Age today**, the **Monthly investment ₹**, the step-up, when to stop, and the Core / Satellite mix and returns. It shows the corpus at 50, 60 and 70, how much **Waiting 3 years costs**, how fast money doubles, and a year-by-year table.

> **Good to know:** All figures are projections from the returns you assume, not promises. Markets do not grow in straight lines.

## Card and loan tools

Open **Card & loan tools** under Plan. The tiles show:
- **Card utilisation** across all cards. Keep it under 30%;
- **EMIs vs income**: your monthly EMIs against your average income of the last three months. Above 40% is beyond the comfort level;
- **Loans & EMIs outstanding**.

### Best card to use today

A purchase made today is billed on the card's next statement and paid by that bill's due date. The longer the gap, the longer your interest-free credit.

The list ranks your cards by **days free**. For each card it shows when today's purchase will be billed, when you must pay, and how much limit is free. A card is moved down and marked "utilisation high" or "no limit left" when it should not be used.

This needs each card's statement day. It comes from card statements, or you can type it on the card (see [Accounts and net worth](help:accounts-and-net-worth)).

**Utilisation by card** lists outstanding, limit, percentage used and the year's spending for each card. **Rewards** shows how each card earns, from the note you add to the card.

### Loan prepayment calculator

1. In **Start from a loan**, choose one of your loans, or type your own figures.
2. Check the **Outstanding (₹)**, **Interest rate (% p.a.)** and **EMI (₹ / month)**.
3. Type **Prepay now (₹)** and, if you like, **Extra every month (₹)**.
4. Under **Use the prepayment to**, choose **Shorten the loan** or **Lower the EMI**.

The results show the **Interest saved**, when the **Loan ends** (or the **New EMI**), the **Time saved**, and how much **Every ₹1 prepaid saves**. A chart compares the balance as now with the balance after prepaying. If the EMI does not even cover the monthly interest, the calculator says so.

The calculator uses the reducing-balance method with monthly rests. Ask your lender about prepayment charges. They are usually nil on floating-rate home loans.

### Which loan to prepay first

This list orders your running loans by interest rate, highest first. That order saves the most interest. For each loan it shows the outstanding amount, the EMI and an estimate of the interest still to pay.

## Good to know

- The tools use your accounts as they are. Add recent card and loan statements before you plan.
- Prepaying a home loan also changes the interest you can claim in your ITR. Check with your tax adviser.
