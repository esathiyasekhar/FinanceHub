"""Auto-categorization rules for transaction descriptions."""
import re

CATEGORY_RULES = [
    (r'NEFT PAYMENT|IMPS PAYMENT|PAYMENT RECEIVED|CREDIT INTEREST|MILESTONE OFFER|'
     r'REWARD REDEMPTION|Annual Fee reversal|Reward redemption|Paid Via Netbanking|'
     r'Paid Via Bank Transfer|Paid With Points|AUTOPAY|AUTO.?PAY|PAYMENT THANK', 'Payment/Reward'),

    (r'SLPE|PAYBIZ|SAVEX|CAS\*SLPE|PYUPAYBIZ|PYU\*SLPE|RAZ\*PAYBIZ|CLEARSETTLE|'
     r'Tri O Tech|TRIOTECH|BUSINESS', 'Business Payment'),

    (r'EMI|Principal Amount|Interest Amount|Amortization|SAMSUNG INDIA ELECTRON|'
     r'FLIPKRT.*LOAN|LAPTOP.*EMI|FRIDGE.*EMI|MOBILE.*EMI', 'EMI/Loan'),

    (r'IGST|GST|Annual Fee|Handling Fee|SMS CHARGES|LATE PAYMENT|OVERDUE|PENALTY|'
     r'Fees & Charges|Forex Fee', 'Charges & Tax'),

    (r'PMSBY|INSURANCE|LIC|HDFC LIFE|TERM|SBI LIFE|IRDAI|POLICYBAZAAR', 'Insurance'),

    (r'CLEARTRIP|HOTEL|MARRIOTT|OYO|GOIBIBO|MAKEMYTRIP|IRCTC|RAILWAY|FLIGHT|'
     r'AIR INDIA|INDIGO|YATRA|EASEMYTRIP|MMT|BOOKING\.COM|AGODA|AIRBNB|'
     r'EXPEDIA|HILTON|RADISSON|IBIS|AIRPORT', 'Travel'),

    (r'AMAZON|FLIPKART|MYNTRA|AJIO|MEESHO|NYKAA|ZARA|APPLE INDIA|EBAY|'
     r'RS COMPONENTS|RS COMPONENT|ELEMENT14|MOUSER|DIGIKEY|CROMA|RELIANCE DIGITAL|'
     r'VIJAY SALES|SAMSUNG INDIA(?! ELECTRON)', 'Shopping'),

    (r'ZOMATO|SWIGGY|BLINKIT|ZEPTO|BIGBASKET|DOMINOS|PIZZA|RESTAURANT|CAFE|'
     r'FOOD|DINING|CANTEEN', 'Food & Dining'),

    (r'FUEL|PETROL|DIESEL|OLA|UBER|RAPIDO|METRO|TOLL|FASTAG|BUS|AUTO RICKSHAW', 'Transport'),

    (r'NETFLIX|PRIME VIDEO|HOTSTAR|SPOTIFY|YOUTUBE|GOOGLE PLAY|DISNEY|'
     r'APPLE.?TV|HBO|ZEE5|SONYLIV|Adobe|CANVA|ENVATO|Canva|Google Play', 'Subscriptions'),

    (r'AIRTEL|JIO|BSNL|TATA SKY|DEN|ACT |ELECTRICITY|WATER|LPG|GAS|'
     r'BESCOM|TNEB|BSES|ADANI|JIO|BILLS', 'Utilities'),

    (r'MUTUAL FUND|SIP|DEMAT|ZERODHA|GROWW|COIN|NSE|BSE|STOCK|PPFA|'
     r'ICICIPRULIFE|KOTAK|BAJAJ FINSERV|CHIT FUND|CHITFUND|FD|RD', 'Investment'),

    (r'HOSPITAL|PHARMACY|MEDICAL|APOLLO|FORTIS|PRACTO|HEALTHKART|'
     r'MEDPLUS|NETMEDS|TATA 1MG|HEALTH|CLINIC|DOCTOR|Aversi|Health & Wellness', 'Healthcare'),

    (r'SCHOOL|COLLEGE|TUITION|UDEMY|COURSERA|BYJU|UNACADEMY|VEDANTU|'
     r'CAMBRIDGE|IITM|IIT|NIT|UNIVERSITY|Education', 'Education'),

    (r'ATM|CASH WITHDRAWAL', 'Cash'),

    (r'NEFT|RTGS|IMPS|UPI(?! )', 'Fund Transfer'),

    (r'PAYWWW VAKILSEARCH|LEGALRAASTA|INDIAFILINGS|REGISTRAR|CA |CHARTERED|'
     r'ADVOCATE|LEGAL|COURT|NOTARY', 'Professional Services'),

    (r'Electronics|LAPTOP|COMPUTER|MOBILE|PHONE|TABLET|GADGET|ELECTRONIC', 'Shopping'),
]


def categorize(description: str) -> str:
    """Return the best matching category for a transaction description."""
    if not description:
        return 'Others'
    upper = description.upper()
    for pattern, category in CATEGORY_RULES:
        if re.search(pattern, description, re.IGNORECASE):
            return category
    return 'Others'
