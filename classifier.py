"""Finance Hub — 4-level classification: Type → Head → Sub-head → Item.

  Type      Income · Expenses · Transfers · Investments
  Head      e.g. Expenses › Transport
  Sub-head  e.g. Expenses › Transport › Car
  Item      e.g. Expenses › Transport › Car › Fuel

Transfers (card bill payments, own-account moves, loan principal, ATM cash) are kept
out of income and expense totals, so nothing is counted twice.

Order of decisions for one transaction:
  1. the user's own rules (Rules page — created when renaming "all from this payee")
  2. rules from your profile (your name variants, family, your companies, clients) — People & entities page
  3. the built-in rules below (common Indian merchants, banks and charges)
  4. Expenses › Uncategorised › To review   /   Income › Other Income › To review
A transaction edited by hand (manual = 1) is never changed by rules again.
"""
import re
import sqlite3

# ── Default tree ─────────────────────────────────────────────────────────────
TREE = [
    ('Income', 'income', {
        'Salary & Remuneration': {'Employers & clients': ['Salary', 'Consultancy fees', 'Reimbursements']},
        'Business Income': {'Own business': ['Transfers from business', 'Reimbursements', 'Director remuneration'],
                            'Customers': ['Sales & service receipts']},
        'Pension & Government': {'Pension': ['Pension credit'], 'Other government': ['Government credit']},
        'Investment Income': {'Dividends': ['Equity dividends'], 'Interest': ['Savings interest', 'FD / RD interest'],
                              'Capital gains': ['Shares & mutual funds']},
        'Refunds & Rewards': {'Refunds': ['Merchant refunds'],
                              'Rewards & cashback': ['Cashback', 'Fuel surcharge waiver', 'Reward redemption']},
        'Receipts from People': {'Family': ['Family transfers'], 'Individuals': ['Person-to-person']},
        'Other Income': {'Miscellaneous': ['Other', 'To review']},
    }),
    ('Expenses', 'expense', {
        'Household': {'Groceries': ['Supermarket', 'Online grocery', 'Vegetables & fruits', 'Milk & dairy'],
                      'Home maintenance': ['Plumbing & electrical', 'Repairs & services', 'Hardware & tools'],
                      'Appliances & furniture': ['Appliances', 'Furniture']},
        'Food & Dining': {'Food delivery': ['Delivery apps'], 'Restaurants': ['Dine-in'],
                          'Snacks & beverages': ['Tea, coffee & snacks', 'Sweets & bakery'],
                          'Canteen': ['Office / hospital canteen']},
        'Transport': {'Car': ['Fuel', 'Service & repairs', 'Parking & toll'],
                      'Public transport': ['Train', 'Metro', 'Bus'], 'Cab & auto': ['Cab / auto']},
        'Travel': {'Flights': ['Air tickets'], 'Hotels & stay': ['Hotels'], 'Travel bookings': ['Booking sites']},
        'Health': {'Hospital': ['Hospital bills'], 'Pharmacy': ['Medicines & supplements'],
                   'Doctor & diagnostics': ['Consultation & tests']},
        'Insurance': {'Life insurance': ['Life premium'], 'Health insurance': ['Health premium'],
                      'Government schemes': ['PMSBY / PMJJBY']},
        'Bills & Utilities': {'Mobile & internet': ['Mobile / data'], 'Electricity & water': ['Electricity'],
                              'Subscriptions': ['OTT & entertainment', 'Software & apps'],
                              'Other bills': ['Bill payment (unspecified)']},
        'Shopping': {'Online marketplace': ['Amazon / Flipkart / others'], 'Electronics': ['Gadgets & mobiles'],
                     'Clothing & footwear': ['Clothing'], 'Personal care': ['Salon & beauty'],
                     'Canteen stores (CSD)': ['CSD purchases'], 'Stores': ['General stores']},
        'Education': {'Fees': ['Tuition / college'], 'Books & courses': ['Courses']},
        'Family & Personal': {'Transfers to family': ['Family members', 'Pocket money (FamApp)'],
                              'Payments to people': ['Individuals (UPI)'], 'Foreign remittance': ['Outward remittance'],
                              'Gifts & donations': ['Gifts', 'Donations']},
        'Loans & EMI': {'Interest': ['Home loan interest', 'Other loan interest', 'Card EMI interest'],
                        'Fees': ['Processing fees']},
        'Bank & Card Charges': {'Taxes on charges': ['GST'], 'Forex charges': ['Markup & conversion fees'],
                                'Card & bank fees': ['Annual / issuance fees', 'SMS & other charges',
                                                     'Late fees & penalties']},
        'Taxes': {'Income tax': ['Advance / self-assessment'], 'Property & local taxes': ['Property tax']},
        'Business Expenses': {'Shipping & courier': ['Courier'], 'Materials & components': ['Components'],
                              'Equipment': ['Tools & machines'], 'Software & cloud': ['Subscriptions']},
        'Uncategorised': {'To review': ['To review']},
    }),
    ('Transfers', 'transfer', {
        'Card bill payments': {'Paid to cards': ['From bank account'], 'Received on cards': ['Card payment received']},
        'Own accounts': {'Between own accounts': ['Self transfer', 'Wallet top-up', 'Cash deposit']},
        'Loan repayments': {'Principal': ['Home loan', 'Other loans', 'Card EMI principal'],
                            'Disbursements': ['Loan disbursal']},
        'Card EMI conversions': {'Purchase converted to EMI': ['EMI conversion credit']},
        'Cash withdrawal': {'ATM': ['ATM withdrawal']},
    }),
    ('Investments', 'investment', {
        'Deposits': {'FD / RD': ['Deposit']},
        'Market': {'Stocks & mutual funds': ['Broker']},
        'Own business': {'Capital & loans to business': ['Transfers to business']},
        'Home & assets': {'Solar & home improvement': ['Solar plant']},
    }),
]
KINDS = {t: k for t, k, _ in TREE}

DEFAULT_ENTITIES = ['Personal']
DEFAULT_PEOPLE = [('Self', 'Primary')]     # your name variants are added by you (People & entities) — none in the code

# ── Built-in rules ───────────────────────────────────────────────────────────
# (regex on 'DESCRIPTION NARRATION' upper-cased, path, conditions/extras)
#   type:  'debit' / 'credit'      acct: 'credit_card' / 'savings' / 'loan'
#   entity / person / name: values set on the transaction
X = 'Expenses'
RULES = [
    # --- Transfers: card bill payments ------------------------------------------------
    (r'PAYMENT RECEIVED|NEFT PAYMENT|PAID VIA|CREDIT CARD PAYMENT|BBPS PAYMENT|MB/IB PAYMENT|AUTOPAY|'
     r'PAYMENT THANK|NETBANKING PAYMENT|^PAYMENT$|NEFT CREDIT CARD',
     ('Transfers', 'Card bill payments', 'Received on cards', 'Card payment received'),
     {'type': 'credit', 'acct': 'credit_card', 'name': 'Card payment received'}),
    (r'BILLPAY DR-HDFC|HDFCCS|HDFC1S|INB ONE CARD|ONE CARD FPL|CREDIT CARD|CC PAYMENT|CARD BILL|SBI CARD|'
     r'ICICI CARD|AXIS CARD|SBICARD|\d{6}X+\d{4}',
     ('Transfers', 'Card bill payments', 'Paid to cards', 'From bank account'),
     {'type': 'debit', 'acct': 'savings', 'name': 'Credit card bill payment'}),
    # --- Card EMIs: conversion credit, principal (transfer), interest (expense) -----------
    (r'AGGREGATOR\W*EMI|OFFUS CREDIT|EMI CONVERSION',
     ('Transfers', 'Card EMI conversions', 'Purchase converted to EMI', 'EMI conversion credit'),
     {'type': 'credit', 'name': 'Purchase converted to EMI'}),
    (r'EMI INTEREST|OFFUS EMI,INT|INTEREST AMOUNT AMORTIZATION|INTEREST ON EMI',
     (X, 'Loans & EMI', 'Interest', 'Card EMI interest'), {'name': 'Card EMI interest'}),
    (r'EMI PRINCIPAL|OFFUS EMI,PRIN|PRINCIPAL AMOUNT AMORTIZATION|^FP EMI|MONTHLY INSTALMENT|EMI \d{1,2}/\d{1,2}',
     ('Transfers', 'Loan repayments', 'Principal', 'Card EMI principal'), {'type': 'debit', 'name': 'Card EMI principal'}),
    (r'PROCNG FEE|PROCESSING FEE', (X, 'Loans & EMI', 'Fees', 'Processing fees'), {'name': 'EMI processing fee'}),
    # --- Bank & card charges (before ATM / generic words) ---------------------------------
    (r'\bIGST\b|\bCGST\b|\bSGST\b|GST @|GST DB|^GST$|TAX ON ', (X, 'Bank & Card Charges', 'Taxes on charges', 'GST'),
     {'name': 'GST on charges'}),
    (r'FOREX|FORGN CURR|MARKUP|\bDCC\b|FOREIGN CURRENCY TRANSACTION FEE|RATE\.DIFF',
     (X, 'Bank & Card Charges', 'Forex charges', 'Markup & conversion fees'), {'name': 'Forex markup / fee'}),
    (r'ANNUAL FEE|RENEWAL FEE|JOINING FEE|ISSUANCE CHARGES|MCC ISSUE|CARD FEE',
     (X, 'Bank & Card Charges', 'Card & bank fees', 'Annual / issuance fees'), {}),
    (r'LATE PAY|\bLPC\b|OVERLIMIT|OVER-LIMIT|FINANCE CHARGE|PENAL',
     (X, 'Bank & Card Charges', 'Card & bank fees', 'Late fees & penalties'), {}),
    (r'SMS|CHARGES?\b|\bCHGS\b|COMMISSION|^SERVICE$|^RENEWAL\b|MAINT|DECLINE CHARGE|HANDLING|REDEMPTION FEE|E MANDATE|CONVENIENCE FEE',
     (X, 'Bank & Card Charges', 'Card & bank fees', 'SMS & other charges'), {}),
    # --- Loan accounts -----------------------------------------------------------------
    (r'INTEREST', (X, 'Loans & EMI', 'Interest', 'Home loan interest'),
     {'acct': 'loan', 'type': 'debit', 'acct_name': 'HOME', 'name': 'Home loan interest'}),
    (r'INTEREST|INT\.COLL', (X, 'Loans & EMI', 'Interest', 'Other loan interest'),
     {'acct': 'loan', 'type': 'debit', 'name': 'Loan interest'}),
    (r'.', ('Transfers', 'Loan repayments', 'Principal', 'Home loan'),
     {'acct': 'loan', 'type': 'credit', 'acct_name': 'HOME', 'name': 'Home loan repayment'}),
    (r'.', ('Transfers', 'Loan repayments', 'Principal', 'Other loans'),
     {'acct': 'loan', 'type': 'credit', 'name': 'Loan repayment'}),
    (r'.', ('Transfers', 'Loan repayments', 'Disbursements', 'Loan disbursal'),
     {'acct': 'loan', 'type': 'debit', 'name': 'Loan disbursal / debit'}),
    (r'DIRECT DR|LOAN REPAYMENT|/M/LOAN', ('Transfers', 'Loan repayments', 'Principal', 'Other loans'),
     {'type': 'debit', 'name': 'Loan EMI (to loan account)'}),
    # --- Income ------------------------------------------------------------------------
    (r'PRINCIPAL CONTR|CGDA|PCDA|RBIS0CGDA|PENSION', ('Income', 'Pension & Government', 'Pension', 'Pension credit'),
     {'type': 'credit', 'name': 'Pension'}),
    (r'INTEREST CREDIT|CREDIT INTEREST|INT\.PD|INT PD|SB INT|INTEREST PAID',
     ('Income', 'Investment Income', 'Interest', 'Savings interest'), {'type': 'credit', 'name': 'Savings interest'}),
    (r'\bDIV\b|DIVIDEND|FIN\.?DIV|FINL DIV|ACHCR|ACH CR|NACH\d', ('Income', 'Investment Income', 'Dividends', 'Equity dividends'),
     {'type': 'credit', 'name': '__dividend__'}),
    (r'FUEL SURCHARGE WAIVER|SURCHARGE WAIVER|FUEL SURCHARGES?$', ('Income', 'Refunds & Rewards', 'Rewards & cashback', 'Fuel surcharge waiver'),
     {'type': 'credit', 'name': 'Fuel surcharge waiver'}),
    (r'CASHBACK|CASH BACK|PAID WITH POINTS|REWARD', ('Income', 'Refunds & Rewards', 'Rewards & cashback', 'Cashback'),
     {'type': 'credit'}),
    # --- Own accounts / cash ----------------------------------------------------------
    (r'DEPOSIT OR INVESTMENT|^SBIY\d|TFR (FROM|TO)\b|SELF TRANSFER',
     ('Transfers', 'Own accounts', 'Between own accounts', 'Self transfer'), {'name': 'Own account transfer'}),
    (r'BY CASH|CASH DEP', ('Transfers', 'Own accounts', 'Between own accounts', 'Cash deposit'), {'type': 'credit', 'name': 'Cash deposit'}),
    (r'DUE TO CLOSURE|ACCOUNT CLOSURE|CLOSURE PROCEEDS', ('Transfers', 'Own accounts', 'Between own accounts', 'Self transfer'),
     {'name': 'Account closure proceeds'}),
    (r'WALLET LOAD|WALLET TOP', ('Transfers', 'Own accounts', 'Between own accounts', 'Wallet top-up'), {'type': 'debit'}),
    (r'ATM CASH|CASH WITHDRAWAL|\bATW\b|\bNWD\b|CWDR|ATM WDL', ('Transfers', 'Cash withdrawal', 'ATM', 'ATM withdrawal'),
     {'type': 'debit'}),
    # --- Investments -------------------------------------------------------------------
    (r'RKSV|UPSTOX|ZERODHA|GROWW|ANGEL ONE|ICICIDIRECT|INDIAN CLEARING|NSE CLEARING|MUTUAL FUND|BSE STAR|\bSIP\b',
     ('Investments', 'Market', 'Stocks & mutual funds', 'Broker'), {}),
    (r'ROOFTOP SOLAR|SOLAR SQUARE|SOLARSQUARE', ('Investments', 'Home & assets', 'Solar & home improvement', 'Solar plant'), {}),
    (r'FIXED DEPOSIT|\bFD\b|RECURRING DEP|\bRD\b', ('Investments', 'Deposits', 'FD / RD', 'Deposit'), {'type': 'debit'}),
    # --- Business expenses (booked to your company when you have one — People & entities) ---------
    (r'FEDEX|\bDHL\b|BLUEDART|BLUE DART|DTDC|COURIER|SHIPROCKET|DELHIVERY|INDIA POST',
     (X, 'Business Expenses', 'Shipping & courier', 'Courier'), {'entity': '__company__'}),
    (r'ALIBABA|ALIEXPRESS|ROBU|MOUSER|DIGIKEY|ELEMENT14|RS COMPONENTS|LCSC|JLCPCB|PCBWAY',
     (X, 'Business Expenses', 'Materials & components', 'Components'), {'entity': '__company__'}),
    (r'3D PRINT', (X, 'Business Expenses', 'Equipment', 'Tools & machines'), {'entity': '__company__'}),
    (r'ANTHROPIC|CLAUDE|OPENAI|GITHUB|AMAZON WEB SERVICES|\bAWS\b|DIGITALOCEAN|GODADDY|HOSTINGER',
     (X, 'Business Expenses', 'Software & cloud', 'Subscriptions'), {'entity': '__company__'}),
    # --- Food & dining (before 'HOTEL' — in Tamil Nadu a 'hotel' is often a restaurant) --
    (r'SODEXO', (X, 'Food & Dining', 'Canteen', 'Office / hospital canteen'), {}),
    (r'SWIGGY INSTAMART|INSTAMART', (X, 'Household', 'Groceries', 'Online grocery'), {}),
    (r'SWIGGY|ZOMATO|WOLT|BOLT FOOD|DOMINO|PIZZA|EATSURE', (X, 'Food & Dining', 'Food delivery', 'Delivery apps'), {}),
    (r'BAKERY|BEKARY|SWEETS|MITHAI|MURUKKU|FARSAN|IBACO|DUNKIN|BASKIN|ICE CREAM|CAKE',
     (X, 'Food & Dining', 'Snacks & beverages', 'Sweets & bakery'), {}),
    (r"CAFE|COFFEE|\bTEA\b|CHAI|JUICE|SNACK|TIFFIN|STARBUCKS|CCD\b|CAFECCINO",
     (X, 'Food & Dining', 'Snacks & beverages', 'Tea, coffee & snacks'), {}),
    (r'RESTAURANT|RESTA\b|BHAVAN|BARBEQUE|BIRYANI|KITCHEN|DHABA|MESS\b|MCDONALD|KFC|BURGER|BAR AND|DINING|FOOD',
     (X, 'Food & Dining', 'Restaurants', 'Dine-in'), {}),
    # --- Household ---------------------------------------------------------------------
    (r'BIGBASKET|INNOVATIVE ?RETAIL|ZEPTO|BLINKIT|DMART|JIOMART|AMAZON PAY IN GROCERY|FLIPKART GROCERY|GROCERY',
     (X, 'Household', 'Groceries', 'Online grocery'), {}),
    (r'VEGETABLE|FRUIT', (X, 'Household', 'Groceries', 'Vegetables & fruits'), {}),
    (r'\bMILK\b|AAVIN|DAIRY|HERITAGE', (X, 'Household', 'Groceries', 'Milk & dairy'), {}),
    (r'CARREFOUR|FOODMART|SUPERMARKET|RELIANCE (FRESH|SMART|RETAIL)|SPENCER|MORE RETAIL|TRADERS|PROVISION',
     (X, 'Household', 'Groceries', 'Supermarket'), {}),
    (r'PLUMB|SANITARY|ELECTRICAL|ELECTRICALS', (X, 'Household', 'Home maintenance', 'Plumbing & electrical'), {}),
    (r'URBANCLAP|URBAN COMPANY', (X, 'Household', 'Home maintenance', 'Repairs & services'), {}),
    (r'HARDWARE|PAINTS|TOOLS', (X, 'Household', 'Home maintenance', 'Hardware & tools'), {}),
    (r'DYSON|KENT RO|WHIRLPOOL|LG ELECTRONICS', (X, 'Household', 'Appliances & furniture', 'Appliances'), {}),
    (r'IKEA|PEPPERFRY|URBAN LADDER|HOME CENTRE|FURNITURE', (X, 'Household', 'Appliances & furniture', 'Furniture'), {}),
    # --- Transport ---------------------------------------------------------------------
    (r'IRCTC|INDIAN RAILWAY|RAILWAY|\bIIL\b', (X, 'Transport', 'Public transport', 'Train'), {}),
    (r'CMRL|METRO', (X, 'Transport', 'Public transport', 'Metro'), {}),
    (r'\bUBER\b|\bOLA\b|RAPIDO|NAMMA YATRI|BOLT\b(?! FOOD)|YANDEX', (X, 'Transport', 'Cab & auto', 'Cab / auto'), {}),
    (r'MARUTI|SERVICE MASTERS|CAR SERVICE|TYRE|MOTORS|AUTOMOBILE', (X, 'Transport', 'Car', 'Service & repairs'), {}),
    (r'FASTAG|TOLL|PARKING', (X, 'Transport', 'Car', 'Parking & toll'), {}),
    (r'FUEL|PETROL|DIESEL|SERVICE STATION|HPCL|BPCL|IOCL|INDIAN OIL|BHARAT PET|NAYARA|SHELL|FILLING',
     (X, 'Transport', 'Car', 'Fuel'), {}),
    # --- Travel ------------------------------------------------------------------------
    (r'AIR ARABIA|AIR INDIA|INDIGO|SPICEJET|VISTARA|AKASA|EMIRATES|QATAR AIR|FLYDUBAI|AIRWAYS|AIRLINE|AIRASIA',
     (X, 'Travel', 'Flights', 'Air tickets'), {}),
    (r'CLEARTRIP|MAKEMYTRIP|GOIBIBO|YATRA|EASEMYTRIP|BOOKING\.COM|AGODA|AIRBNB|IXIGO|REDBUS',
     (X, 'Travel', 'Travel bookings', 'Booking sites'), {}),
    (r'HOTEL|\bHO$|BHOJAN', (X, 'Food & Dining', 'Restaurants', 'Dine-in'), {'type': 'debit', 'max': 1000}),
    (r'HOTEL|RESORT|LODGE|\bINN\b|OYO|STERLING',
     (X, 'Travel', 'Hotels & stay', 'Hotels'), {}),
    # --- Health ------------------------------------------------------------------------
    (r'HOSPITAL|HEALTHCARE PVT', (X, 'Health', 'Hospital', 'Hospital bills'), {}),
    (r'PHARMA|PHARMACY|MEDICAL|1MG|APOLLO|MEDPLUS|NETMEDS|CHEMIST|DRUG|WELLNESS',
     (X, 'Health', 'Pharmacy', 'Medicines & supplements'), {}),
    (r'CLINIC|DOCTOR|DIAGNOSTIC|\bLABS?\b|SCANS?\b|DENTAL', (X, 'Health', 'Doctor & diagnostics', 'Consultation & tests'), {}),
    # --- Insurance ---------------------------------------------------------------------
    (r'METLIFE|\bLIC\b|LIFE INSURANCE|HDFC LIFE|SBI LIFE|MAX LIFE|TATA AIA|ICICI ?PRU',
     (X, 'Insurance', 'Life insurance', 'Life premium'), {}),
    (r'STAR HEALTH|CARE HEALTH|\bNIVA\b|HEALTH INSURANCE|LOMBARD|ALLIANZ', (X, 'Insurance', 'Health insurance', 'Health premium'), {}),
    (r'PMSBY|PMJJBY|\bAPY\b', (X, 'Insurance', 'Government schemes', 'PMSBY / PMJJBY'), {}),
    # --- Bills & subscriptions ---------------------------------------------------------
    (r'AIRTEL|\bJIO\b|BSNL|VODAFONE|\bVI\b|RECHARGE', (X, 'Bills & Utilities', 'Mobile & internet', 'Mobile / data'), {}),
    (r'TNEB|TANGEDCO|BESCOM|ELECTRICITY|EB BILL', (X, 'Bills & Utilities', 'Electricity & water', 'Electricity'), {}),
    (r'NETFLIX|SPOTIFY|HOTSTAR|PRIME VIDEO|SUN TV|SUNNXT|ZEE5|SONYLIV|YOUTUBE|GOOGLE PLAY|APPLE\.COM|ITUNES|TIMEZONE',
     (X, 'Bills & Utilities', 'Subscriptions', 'OTT & entertainment'), {}),
    (r'ADOBE|MICROSOFT|GOOGLE ONE|CANVA|DROPBOX|NOTION', (X, 'Bills & Utilities', 'Subscriptions', 'Software & apps'), {}),
    (r'BILL PAYMENT', (X, 'Bills & Utilities', 'Other bills', 'Bill payment (unspecified)'), {'type': 'debit'}),
    # --- Shopping ----------------------------------------------------------------------
    (r'\bCSD\b|CANTEEN STORES', (X, 'Shopping', 'Canteen stores (CSD)', 'CSD purchases'), {}),
    (r'MOBILES|POORVIKA|SANGEETHA|CROMA|RELIANCE DIGITAL|VIJAY SALES|SAMSUNG|KONTAKT|ELECTRONICS|GADGET',
     (X, 'Shopping', 'Electronics', 'Gadgets & mobiles'), {}),
    (r'ADITYA BIRLA|LIFESTYLE|PANTALOON|MAX FASHION|TRENDS|ZUDIO|WESTSIDE|FOOTWEAR|BATA|CLOTH|TEXTILE|SILKS',
     (X, 'Shopping', 'Clothing & footwear', 'Clothing'), {}),
    (r'SALON|PARLOUR|BEAUTY|\bSPA\b|NATURALS|GROOMING', (X, 'Shopping', 'Personal care', 'Salon & beauty'), {}),
    (r'AMAZON|FLIPKART|MYNTRA|AJIO|MEESHO|NYKAA|TATA CLIQ|TEMU|ETSY|SHEIN|BLINK COMMERCE|JIOMART',
     (X, 'Shopping', 'Online marketplace', 'Amazon / Flipkart / others'), {}),
    (r'STORES?\b|AGENC(Y|IES)|MART\b|ENTERPRISES|\bSHOP\b', (X, 'Shopping', 'Stores', 'General stores'), {}),
    # --- Education / taxes -------------------------------------------------------------
    (r'SCHOOL|COLLEGE|UNIVERSITY|TUITION|ACADEMY|UDEMY|COURSERA|BYJU|EXAM FEE',
     (X, 'Education', 'Fees', 'Tuition / college'), {}),
    (r'INCOME TAX|\bITD\b|TIN NSDL|CBDT|PROTEAN|TDS', (X, 'Taxes', 'Income tax', 'Advance / self-assessment'), {}),
    (r'COMMISSIONERATE OF MUN|MUNICIPAL|CORPORATION OF|PROPERTY TAX', (X, 'Taxes', 'Property & local taxes', 'Property tax'), {}),
    # --- Family & people ---------------------------------------------------------------
    (r'FAMAPP|FAM ?PAY|TRI O TECH|TRIOTECH', (X, 'Family & Personal', 'Transfers to family', 'Pocket money (FamApp)'),
     {'type': 'debit', 'name': 'FamApp (pocket money)'}),
    (r'USD -?[\d.]+ @|OUTWARD REMIT|FOREIGN REMIT|SWIFT', (X, 'Family & Personal', 'Foreign remittance', 'Outward remittance'),
     {'type': 'debit', 'name': '__remittance__'}),
    (r'REFUND|REVERSAL', ('Income', 'Refunds & Rewards', 'Refunds', 'Merchant refunds'), {'type': 'credit'}),
    # person-to-person (UPI / IMPS / NEFT / INB to a person name) — after all merchant rules
    (r'^(UPI|IMPS|NEFT|INB|THIRD PARTY TRANSFER)', ('Income', 'Receipts from People', 'Individuals', 'Person-to-person'),
     {'type': 'credit'}),
    (r'^(UPI|IMPS|INB)', (X, 'Family & Personal', 'Payments to people', 'Individuals (UPI)'), {'type': 'debit'}),
]
_COMPILED = [(re.compile(p, re.I), path, opt) for p, path, opt in RULES]
# your profile's rules (name variants, family, companies, clients) are tried from this point on
_SPLIT = next(i for i, (p, path, opt) in enumerate(RULES) if path[-1] == 'Pension credit')


def _alt(words):
    words = sorted({w.strip().upper() for w in words if len(w.strip()) >= 4}, key=len, reverse=True)
    return re.compile(r'(?<![A-Z])(' + '|'.join(re.escape(w).replace(r'\ ', r'\s*') for w in words) + r')(?![A-Z])') if words else None


def profile_rules(con):
    """Rules built from what you entered on People & entities — nothing personal is written in the code."""
    out = []
    people = con.execute('SELECT name, aliases FROM people').fetchall()
    selfw = [a for n, al in people if n == 'Self' for a in (al or '').split(',') if a.strip().lower() != 'primary']
    rx = _alt(selfw)
    if rx:
        out.append((rx, ('Transfers', 'Own accounts', 'Between own accounts', 'Self transfer'), {'name': 'Own account transfer'}))
    for n, al in people:
        if n == 'Self':
            continue
        rx = _alt([n] + (al or '').split(','))
        if rx:
            out.append((rx, ('Expenses', 'Family & Personal', 'Transfers to family', 'Family members'),
                        {'type': 'debit', 'person': n}))
    try:
        ents = con.execute("SELECT name, COALESCE(role,'book'), COALESCE(aliases,'') FROM entities WHERE name<>'Personal'").fetchall()
    except sqlite3.OperationalError:
        ents = [(r[0], 'book', '') for r in con.execute("SELECT name FROM entities WHERE name<>'Personal'")]
    for n, role, al in ents:
        rx = _alt([n] + al.split(','))
        if not rx:
            continue
        if role == 'payer':
            out.append((rx, ('Income', 'Salary & Remuneration', 'Employers & clients', 'Consultancy fees'), {'type': 'credit', 'name': n}))
        elif role == 'book':
            out.append((rx, ('Income', 'Business Income', 'Own business', 'Transfers from business'),
                        {'type': 'credit', 'name': n, 'not_book': n}))
            out.append((rx, ('Investments', 'Own business', 'Capital & loans to business', 'Transfers to business'),
                        {'type': 'debit', 'name': f'Transfer to {n}', 'not_book': n}))
    return out

CHARGE_ROW = re.compile(r'(FOREX FEE|FOREX MARKUP|MARKUP FEE|DCC FEE|GST ON|IGST|CGST|SGST)\b', re.I)
TO_REVIEW_DEBIT = ('Expenses', 'Uncategorised', 'To review', 'To review')
TO_REVIEW_CREDIT = ('Income', 'Other Income', 'Miscellaneous', 'To review')
CARD_REFUND = ('Income', 'Refunds & Rewards', 'Refunds', 'Merchant refunds')

# ── Payee names ──────────────────────────────────────────────────────────────
CITIES = ('BANGALORE|BENGALURU|MUMBAI|CHENNAI|GURGAON|GURUGRAM|NEW ?DELHI|NEWDELHI|DELHI|NOIDA|'
          'HYDERABAD|PUNE|KOLKATA|AHMEDABAD|SINGAPORE|LONDON|DUBAI|SOUTH DELHI|COIMBATORE|WWW\\.AMAZON\\.IN')


BRANDS = [  # (regex on the raw description, friendly name)
    (r'AMAZON PAY IN GROCERY', 'Amazon Fresh'), (r'AMAZON', 'Amazon'), (r'FLIPKART', 'Flipkart'),
    (r'BIGBASKET|INNOVATIVE ?RETAIL', 'BigBasket'), (r'ZEPTO', 'Zepto'), (r'BLINKIT|BLINK COMMERCE', 'Blinkit'),
    (r'SWIGGY INSTAMART|INSTAMART', 'Swiggy Instamart'), (r'SWIGGY', 'Swiggy'), (r'ZOMATO', 'Zomato'),
    (r'CLEARTRIP', 'Cleartrip'), (r'MAKEMYTRIP', 'MakeMyTrip'), (r'IRCTC', 'IRCTC'), (r'AIR ARABIA', 'Air Arabia'),
    (r'FEDEX', 'FedEx'), (r'\bDHL\b', 'DHL'), (r'ALIEXPRESS', 'AliExpress'), (r'ALIBABA', 'Alibaba'),
    (r'ANTHROPIC|CLAUDE\.AI', 'Anthropic (Claude)'), (r'TATA 1MG|1MG', 'Tata 1mg'), (r'AIRTEL', 'Airtel'),
    (r'\bJIO\b', 'Jio'), (r'NETFLIX', 'Netflix'), (r'SPOTIFY', 'Spotify'), (r'METLIFE', 'PNB MetLife'),
    (r'DYSON', 'Dyson'), (r'RKSV|UPSTOX', 'Upstox'), (r'ZERODHA', 'Zerodha'), (r'SOLARSQUARE', 'SolarSquare'),
]
_BRANDS = [(re.compile(p, re.I), n) for p, n in BRANDS]


def payee_name(desc: str) -> str:
    """Readable payee: 'SWIGGY FOOD BANGALORE IN' → 'Swiggy Food';
    'UPI · A KUMAR' kept; reference numbers removed."""
    d = re.sub(r'\s+', ' ', str(desc or '')).strip()
    if not d:
        return ''
    for rx, nm in _BRANDS:
        if rx.search(d):
            return nm
    if re.match(r'NEFT UTR NO', d, re.I):
        return 'NEFT (no payee name)'
    d = re.sub(r'\s*\((Chennai|Bangalore|Bengaluru|Mumbai|Delhi|Hyderabad|Pune|Kolkata)\)$', '', d, flags=re.I)
    d = re.sub(r'\(Pay in EMIs\)', '', d, flags=re.I)
    m = re.match(r'UPI/(?:DR|CR)/\d+/([^/]+)/', d, flags=re.I)              # SBI: UPI/DR/ref/NAME/BANK/vpa
    if m:
        d = 'UPI · ' + m.group(1)
    d = re.sub(r'^UPI-\s*', 'UPI · ', d, flags=re.I)                       # HDFC card: UPI-NAME
    d = re.sub(r'^INB\s+MBS\s+', 'INB · ', d, flags=re.I)
    d = re.sub(r'^THIRD PARTY TRANSFER FROM-', 'From · ', d, flags=re.I)
    d = re.sub(r'^(RAZ|CAS|PYU|IIL|PNB|IND|BHARATPE|PAYU)\*\s*', '', d, flags=re.I)
    d = re.sub(r'\((Ref#|\w*\d{6,}\w*)[^)]*\)?', '', d)
    d = re.sub(r'\b[A-Z0-9]*\d{8,}[A-Z0-9]*\b', '', d)                 # long refs
    d = re.sub(rf'[,\s]+({CITIES})\b.*$', '', d, flags=re.I)           # city and everything after
    d = re.sub(rf'(?<=[a-z])({CITIES})$', '', d, flags=re.I) if re.search(r'[a-z]', d) else d   # 'LIMIMumbai'
    d = re.sub(r'IN(GURGAON|MUMBAI|BANGALORE|CHENNAI|DELHI)$', '', d)
    d = re.sub(r'\s+(IN|GE|GB|US|SG|AE)$', '', d)
    d = re.sub(r'\s+\d+\.\d{2} (GEL|USD|EUR|GBP)$', '', d)
    d = re.sub(r'[\s,*:-]+$', '', d).strip()
    if re.fullmatch(r'UPI · \d{6,}\w*', d) or d in ('UPI ·', 'UPI'):
        return 'UPI · (phone number only)'
    pre = ''
    m = re.match(r'(UPI · |INB · |From · )', d)
    if m:
        pre, d = m.group(1), d[m.end():]
    if d.isupper() or d.islower():
        d = ' '.join(w if (len(w) <= 3 and w.isalpha() and w.upper() in ('UPI', 'EMI', 'GST', 'ATM', 'SBI', 'HDFC', 'IMPS', 'NEFT', 'CSD', 'LLC', 'LTD', 'PVT', 'MS'))
                     else w.capitalize() for w in d.split())
        d = re.sub(r'\b(Upi|Imps|Neft|Emi|Gst|Atm|Sbi|Hdfc|Csd|Llc|Ltd|Pvt)\b', lambda m: m.group(1).upper(), d)
    d = (pre + d).strip()
    return d[:80] or str(desc)[:80]


def payee_key(desc: str) -> str:
    """Stable key for 'all from this payee' rules: letters only, upper case."""
    p = payee_name(desc).upper()
    p = re.sub(r'[^A-Z ]+', ' ', p)
    return re.sub(r'\s+', ' ', p).strip()


def dividend_name(text: str) -> str:
    t = text.upper()
    known = [('MAZAGON', 'Mazagon Dock'), ('TORRENT', 'Torrent Pharma'), ('BHARAT DYNAMIC', 'Bharat Dynamics'),
             ('MARKSANS', 'Marksans Pharma'), ('GETD', 'GE T&D India'), ('FBL', 'Federal Bank'), ('FEDERAL', 'Federal Bank'),
             ('BEL ', 'Bharat Electronics'), ('BHARAT ELEC', 'Bharat Electronics'), ('COAL INDIA', 'Coal India'),
             ('ITC', 'ITC'), ('INFOSYS', 'Infosys'), ('TCS', 'TCS'), ('HDFC', 'HDFC')]
    for k, v in known:
        if k in t:
            return f'Dividend – {v}'
    m = re.search(r'(?:ACHCR|NACH)\S*\s+(?:[A-Z]{4}\d+\s+)?([A-Z][A-Z .&]{3,30})', t)
    return f'Dividend – {m.group(1).strip().title()}' if m else 'Dividend'


# ── Database ─────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id  INTEGER REFERENCES categories(id),
    name       TEXT NOT NULL,
    level      INTEGER NOT NULL,          -- 1 Type, 2 Head, 3 Sub-head, 4 Item
    kind       TEXT NOT NULL,             -- income / expense / transfer / investment
    sort_order INTEGER DEFAULT 0,
    UNIQUE(parent_id, name)
);
CREATE TABLE IF NOT EXISTS rules (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern      TEXT NOT NULL,           -- text to find (upper case)
    match_type   TEXT NOT NULL DEFAULT 'contains',   -- contains / payee
    display_name TEXT,
    category_id  INTEGER REFERENCES categories(id),
    entity       TEXT,
    person       TEXT,
    created_at   TEXT DEFAULT (datetime('now')),
    UNIQUE(pattern, match_type)
);
CREATE TABLE IF NOT EXISTS entities (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, sort_order INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, aliases TEXT DEFAULT '');
"""
TXN_COLUMNS = [('category_id', 'INTEGER'), ('payee', 'TEXT'), ('display_name', 'TEXT'), ('entity', "TEXT"),
               ('person', 'TEXT'), ('manual', 'INTEGER DEFAULT 0'), ('rule_id', 'INTEGER'), ('notes', 'TEXT')]


def ensure_schema(con: sqlite3.Connection):
    con.executescript(SCHEMA)
    have = {r[1] for r in con.execute('PRAGMA table_info(transactions)')}
    for name, decl in TXN_COLUMNS:
        if name not in have:
            con.execute(f'ALTER TABLE transactions ADD COLUMN {name} {decl}')
    con.execute('CREATE INDEX IF NOT EXISTS idx_txn_catid ON transactions(category_id)')
    if not con.execute('SELECT COUNT(*) FROM categories').fetchone()[0]:
        seed_tree(con)
    for i, e in enumerate(DEFAULT_ENTITIES):
        con.execute('INSERT OR IGNORE INTO entities (name, sort_order) VALUES (?,?)', (e, i))
    for n, a in DEFAULT_PEOPLE:
        con.execute('INSERT OR IGNORE INTO people (name, aliases) VALUES (?,?)', (n, a))
    con.commit()


def seed_tree(con):
    for ti, (tname, kind, heads) in enumerate(TREE):
        tid = _ins(con, None, tname, 1, kind, ti)
        for hi, (hname, subs) in enumerate(heads.items()):
            hid = _ins(con, tid, hname, 2, kind, hi)
            for si, (sname, items) in enumerate(subs.items()):
                sid = _ins(con, hid, sname, 3, kind, si)
                for ii, iname in enumerate(items):
                    _ins(con, sid, iname, 4, kind, ii)


def _ins(con, parent, name, level, kind, order):
    con.execute('INSERT OR IGNORE INTO categories (parent_id, name, level, kind, sort_order) VALUES (?,?,?,?,?)',
                (parent, name, level, kind, order))
    row = con.execute('SELECT id FROM categories WHERE name=? AND ' +
                      ('parent_id IS NULL' if parent is None else 'parent_id=?'),
                      (name,) if parent is None else (name, parent)).fetchone()
    return row[0]


def path_id(con, path: tuple, create: bool = True):
    """('Expenses','Transport','Car','Fuel') → category id (creating missing nodes if asked)."""
    parent, kind = None, KINDS.get(path[0], 'expense')
    cid = None
    for level, name in enumerate(path, 1):
        q = 'SELECT id, kind FROM categories WHERE name=? AND ' + ('parent_id IS NULL' if parent is None else 'parent_id=?')
        row = con.execute(q, (name,) if parent is None else (name, parent)).fetchone()
        if row:
            cid, kind = row[0], row[1]
        elif create:
            cid = _ins(con, parent, name, level, kind, 99)
        else:
            return cid
        parent = cid
    return cid


class Classifier:
    """Load once per request / import; classify many rows."""

    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.acct_type = {r[0]: (r[1] or '') for r in con.execute('SELECT name, type FROM accounts')}
        self.people = []
        for name, aliases in con.execute('SELECT name, aliases FROM people'):
            for a in [name] + [x.strip() for x in (aliases or '').split(',') if x.strip()]:
                self.people.append((a.upper(), name))
        self.people.sort(key=lambda x: -len(x[0]))
        self.rules = [dict(id=r[0], pattern=(r[1] or '').upper(), match_type=r[2], display_name=r[3],
                           category_id=r[4], entity=r[5], person=r[6])
                      for r in con.execute('SELECT id, pattern, match_type, display_name, category_id, entity, person FROM rules')]
        self.rules.sort(key=lambda r: -len(r['pattern']))          # most specific first
        self._path_cache = {}
        self.profile = profile_rules(con)
        try:
            self.acct_book = {r[0]: (r[1] or 'Personal') for r in con.execute('SELECT name, entity FROM accounts')}
            self.company = next((r[0] for r in con.execute("SELECT name FROM entities WHERE name<>'Personal' AND "
                                                           "COALESCE(role,'book')='book' ORDER BY sort_order, id")), None)
        except sqlite3.OperationalError:
            self.acct_book, self.company = {}, None
        self.compiled = _COMPILED[:_SPLIT] + self.profile + _COMPILED[_SPLIT:]

    def _acct_kind(self, account: str) -> str:
        t = self.acct_type.get(account, '').lower()
        n = (account or '').lower()
        if 'loan' in t or ' loan' in n:
            return 'loan'
        if t in ('savings', 'current') or 'savings' in n:
            return 'savings'
        if t == 'credit_card' or re.search(r'\b(cc|card)\b', n):
            return 'credit_card'
        return t or 'savings'

    def person_for(self, cardholder: str, text: str = '') -> str:
        ch = (cardholder or '').strip().upper()
        if ch:
            for alias, name in self.people:
                if alias == ch or (len(alias) > 4 and alias in ch):
                    return name
            if not re.fullmatch(r'(CARD|SAVINGS|LOAN|CURRENT|ULTIMATE|CREDIT CARD).*\d{4}', ch):
                return cardholder.strip().title()
        return 'Self'

    def _pid(self, path):
        if path not in self._path_cache:
            self._path_cache[path] = path_id(self.con, path)
        return self._path_cache[path]

    def rule_matches(self, rule, text_upper: str, key: str) -> bool:
        if CHARGE_ROW.match(text_upper):          # 'Forex fee + GST on <merchant>' stays a bank charge
            return False
        if rule['match_type'] == 'payee':
            return key == rule['pattern']
        return rule['pattern'] and rule['pattern'] in text_upper

    def classify(self, t: dict) -> dict:
        """t: date, description, narration, amount, type, account, cardholder."""
        desc = t.get('description') or ''
        text = f"{desc} {t.get('narration') or ''}".upper().strip()
        key = payee_key(desc)
        out = {'payee': payee_name(desc), 'entity': 'Personal',
               'person': self.person_for(t.get('cardholder'), text), 'rule_id': None, 'display_name': None}
        # 1) user rules
        for r in self.rules:
            if self.rule_matches(r, text, key):
                out.update(rule_id=r['id'], category_id=r['category_id'])
                if r['display_name']:
                    out['display_name'] = r['display_name']
                if r['entity']:
                    out['entity'] = r['entity']
                if r['person']:
                    out['person'] = r['person']
                if out.get('category_id'):
                    return out
        # 2) built-in rules
        akind = self._acct_kind(t.get('account', ''))
        ttype = t.get('type', 'debit')
        for rx, path, opt in self.compiled:
            if opt.get('type') and opt['type'] != ttype:
                continue
            if opt.get('not_book') and self.acct_book.get(t.get('account')) == opt['not_book']:
                continue
            if opt.get('acct') and opt['acct'] != akind:
                continue
            if opt.get('acct_name') and opt['acct_name'] not in (t.get('account') or '').upper():
                continue
            if opt.get('max') and float(t.get('amount') or 0) > opt['max']:
                continue
            if not rx.search(text):
                continue
            out['category_id'] = self._pid(path)
            if opt.get('entity'):
                out['entity'] = (self.company or 'Personal') if opt['entity'] == '__company__' else opt['entity']
            if opt.get('person'):
                out['person'] = opt['person']
            nm = opt.get('name')
            if nm == '__dividend__':
                out['payee'] = dividend_name(text)
            elif nm == '__remittance__':
                m = re.search(r'(USD|EUR|GBP|GEL)\s*-?([\d.]+)', text)
                out['payee'] = f'Foreign remittance {m.group(1)} {float(m.group(2)):,.2f}' if m else 'Foreign remittance'
            elif nm:
                out['payee'] = nm
            if opt.get('person_from_text'):
                for alias, name in self.people:
                    if alias in text:
                        out['person'] = name
                        break
            return out
        # 3) fallbacks: a credit on a card with no rule is a merchant refund
        if ttype == 'credit' and akind == 'credit_card':
            out['category_id'] = self._pid(CARD_REFUND)
        else:
            out['category_id'] = self._pid(TO_REVIEW_CREDIT if ttype == 'credit' else TO_REVIEW_DEBIT)
        return out


def head_name(con, category_id) -> str:
    """Level-2 name (used to fill the legacy `category` column)."""
    row = con.execute('''WITH RECURSIVE up(id, parent_id, name, level) AS (
                           SELECT id, parent_id, name, level FROM categories WHERE id=?
                           UNION ALL SELECT c.id, c.parent_id, c.name, c.level FROM categories c JOIN up ON c.id=up.parent_id)
                         SELECT name FROM up WHERE level=2''', (category_id,)).fetchone()
    return row[0] if row else 'Others'


def apply_to_rows(con, where: str = 'COALESCE(manual,0)=0', params=(), only_unclassified=False, commit=True) -> int:
    """(Re)classify existing transactions. Manually edited rows are never touched."""
    clf = Classifier(con)
    cond = where + (' AND category_id IS NULL' if only_unclassified else '')
    rows = con.execute(f'SELECT id, date, description, narration, amount, type, account, cardholder FROM transactions '
                       f'WHERE {cond}', params).fetchall()
    heads = {}
    n = 0
    for r in rows:
        t = dict(zip(('id', 'date', 'description', 'narration', 'amount', 'type', 'account', 'cardholder'), r))
        c = clf.classify(t)
        cid = c['category_id']
        if cid not in heads:
            heads[cid] = head_name(con, cid)
        con.execute('UPDATE transactions SET category_id=?, payee=?, display_name=?, entity=?, person=?, rule_id=?, '
                    'category=? WHERE id=?',
                    (cid, c['payee'], c['display_name'], c['entity'], c['person'], c['rule_id'], heads[cid], t['id']))
        n += 1
    if commit:
        con.commit()
    return n


# ── Tree helpers for pages ───────────────────────────────────────────────────
def load_tree(con):
    """All categories as dicts with 'path' and 'children' (ordered)."""
    rows = [dict(id=r[0], parent_id=r[1], name=r[2], level=r[3], kind=r[4], sort_order=r[5])
            for r in con.execute('SELECT id, parent_id, name, level, kind, sort_order FROM categories ORDER BY level, sort_order, name')]
    by_id = {r['id']: r for r in rows}
    for r in rows:
        r['children'] = []
    roots = []
    for r in rows:
        if r['parent_id'] and r['parent_id'] in by_id:
            by_id[r['parent_id']]['children'].append(r)
        else:
            roots.append(r)
    for r in rows:
        p, names = r, []
        while p:
            names.append(p['name'])
            p = by_id.get(p['parent_id'])
        r['path'] = ' › '.join(reversed(names))
        r['short_path'] = ' › '.join(reversed(names[:-1])) if r['level'] > 1 else r['name']
    order = {t: i for i, (t, _, _) in enumerate(TREE)}
    roots.sort(key=lambda r: order.get(r['name'], 99))
    return roots, by_id


def descendants(by_id, cid) -> list:
    out, stack = [], [cid]
    while stack:
        c = stack.pop()
        out.append(c)
        stack.extend(ch['id'] for ch in by_id[c]['children']) if c in by_id else None
    return out


def flat_options(roots) -> list:
    """For <select>: [(id, label with indentation, path, level, kind)]"""
    out = []

    def walk(n):
        out.append({'id': n['id'], 'label': ('   ' * (n['level'] - 1)) + n['name'],
                    'path': n['path'], 'level': n['level'], 'kind': n['kind']})
        for ch in n['children']:
            walk(ch)
    for r in roots:
        walk(r)
    return out
