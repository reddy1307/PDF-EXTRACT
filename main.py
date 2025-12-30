from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import pdfplumber
import re
import io
import pandas as pd

# =========================
# FASTAPI SETUP
# =========================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# CATEGORY RULES (MATCH FRONTEND)
# =========================
RAW_CATEGORY_RULES = {
    "Income / Transfer In": [
        r"salary", r"income", r"transfer.*in", r"credit.*transfer",
        r"deposit", r"refund", r"interest.*received",
        r"dividend", r"bonus", r"reimbursement"
    ],

    "Recharge": [
        r"airtel", r"jio", r"vi", r"vodafone", r"idea", r"bsnl",
        r"recharge", r"prepaid", r"postpaid",
        r"mobile.*bill", r"phone.*bill", r"telecom", r"sim.*card"
    ],

    "Food & Dining": [
        r"zomato", r"swiggy", r"dominos", r"pizza", r"mcdonald", r"mcd", r"kfc",
        r"restaurant", r"cafe", r"hotel", r"eatfit",
        r"food", r"dining", r"lunch", r"dinner", r"breakfast",
        r"coffee", r"chai", r"juice",
        r"bakery", r"dessert", r"ice.*cream",
        r"fast.*food", r"street.*food", r"dhaba",
        r"bar", r"pub", r"buffet"
    ],

    "Fuel": [
        r"petrol", r"diesel", r"fuel", r"oil",
        r"indian.*oil", r"hpcl", r"bharat.*petroleum",
        r"shell", r"gas", r"cng", r"lpg",
        r"petrol.*pump", r"filling.*station"
    ],

    "Shopping": [
        r"amazon", r"flipkart", r"myntra", r"ajio", r"meesho", r"snapdeal",
        r"shopping", r"purchase", r"buy", r"shop",
        r"mall", r"market", r"store", r"mart",
        r"fashion", r"clothing", r"electronics", r"furniture"
    ],

    "Groceries": [
        r"bigbasket", r"blinkit", r"zepto", r"instamart", r"dmart",
        r"grocery", r"vegetable", r"fruit", r"kirana",
        r"milk", r"bread", r"egg", r"rice", r"wheat", r"snacks"
    ],

    "Travel": [
        r"uber", r"ola", r"rapido", r"irctc",
        r"makemytrip", r"yatra", r"redbus",
        r"taxi", r"cab", r"bus", r"train",
        r"metro", r"flight"
    ],

    "Entertainment": [
        r"netflix", r"prime", r"hotstar", r"spotify",
        r"bookmyshow", r"sony.*liv",
        r"movie", r"cinema", r"gaming", r"ott", r"streaming"
    ],

    "Utilities": [
        r"electricity", r"power", r"water", r"gas",
        r"bill", r"utility", r"internet",
        r"wifi", r"broadband", r"rent", r"emi", r"insurance"
    ],

    "Education": [
        r"udemy", r"coursera", r"byju", r"unacademy",
        r"school", r"college", r"education", r"course",
        r"tuition", r"books", r"stationery"
    ],

    "Healthcare": [
        r"hospital", r"clinic", r"pharmacy",
        r"apollo", r"medplus", r"1mg", r"pharmeasy",
        r"doctor", r"medicine", r"medical",
        r"health.*insurance"
    ],

    "Banking & Finance": [
        r"emi", r"loan", r"interest", r"insurance",
        r"mutual.*fund", r"sip", r"credit.*card",
        r"investment", r"stock", r"tax", r"gst"
    ],

    "Transfer Out": [
        r"paid.*to", r"transfer.*out", r"sent.*to",
        r"upi.*payment", r"imps", r"neft", r"rtgs",
        r"gift", r"donation", r"subscription"
    ],
}

# Compile regex once (important for performance)
CATEGORY_RULES = {
    category: [re.compile(p, re.I) for p in patterns]
    for category, patterns in RAW_CATEGORY_RULES.items()
}

# =========================
# CATEGORIZE FUNCTION
# =========================
def categorize(description: str, txn_type: str) -> str:
    desc = description.lower()

    if txn_type.upper() == "CREDIT":
        return "Income / Transfer In"

    for category, patterns in CATEGORY_RULES.items():
        for pattern in patterns:
            if pattern.search(desc):
                return category

    return "Other Expense"

# =========================
# PARSE LINE
# =========================
def parse_line(line: str):
    date_match = re.search(r"([A-Z][a-z]{2} \d{2}, \d{4})", line)
    date = pd.to_datetime(date_match.group(1), format="%b %d, %Y") if date_match else None

    time_match = re.search(r"\b(\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?)\b", line, re.I)
    time_str = time_match.group(1) if time_match else None

    datetime_val = None
    if date is not None:
        datetime_val = pd.to_datetime(
            f"{date.strftime('%b %d, %Y')} {time_str}" if time_str else date,
            errors="coerce"
        )

    amount_match = re.search(r"₹([\d,]+\.?\d*)", line)
    amount = float(amount_match.group(1).replace(",", "")) if amount_match else 0.0

    type_match = re.search(r"\b(CREDIT|DEBIT)\b", line, re.I)
    txn_type = type_match.group(1).upper() if type_match else "UNKNOWN"

    desc_match = re.search(
        r"(Received from|Paid to|Cashback from|Transfer to)\s(.+?)\s(CREDIT|DEBIT)",
        line,
        re.I
    )
    desc = desc_match.group(2) if desc_match else line.strip()

    utr_match = re.search(r"\bUTR(?:\s*No\.?)?[:\-\s]*([0-9]+)\b", line, re.I)
    utr = utr_match.group(1) if utr_match else None

    return {
        "date": datetime_val,
        "time": time_str,
        "datetime": datetime_val,
        "description": desc,
        "type": txn_type,
        "amount": amount,
        "category": categorize(desc, txn_type),
        "UTR_No": utr,
    }

# =========================
# UPLOAD ENDPOINT
# =========================
@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    pdf_bytes = io.BytesIO(contents)

    texts = []
    with pdfplumber.open(pdf_bytes) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                texts.append(text)

    lines = "\n".join(texts).split("\n")

    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith(("Page", "Transaction Statement for", "Date Transaction")):
            continue
        if "system generated statement" in line.lower():
            continue
        clean_lines.append(line)

    filtered_lines = [
        line for line in clean_lines
        if re.search(r"\b(CREDIT|DEBIT|UTR)\b", line, re.I)
    ]

    rows = []
    i = 0
    while i < len(filtered_lines) - 1:
        combined = filtered_lines[i] + " " + filtered_lines[i + 1]
        rows.append(combined)
        i += 2

    parsed = [parse_line(row) for row in rows]
    df = pd.DataFrame(parsed)

    return {
        "transactions": df.to_dict(orient="records"),
        "count": len(df)
    }
