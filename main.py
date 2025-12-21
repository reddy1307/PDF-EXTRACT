from fastapi import FastAPI, UploadFile, File
import pdfplumber,re,io
import pandas as pd
from fastapi.middleware.cors import CORSMiddleware
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def categorize(desc, txn_type):
    d = desc.lower()
    if txn_type == "CREDIT":
        return "Income / Transfer In"

    categories = {
        "Recharge": [
            "airtel", "jio", "vi", "vodafone", "idea", "bsnl"
        ],
        "Food & Dining": [
            "zomato", "swiggy", "dominos", "pizza", "mcdonald",
            "kfc", "restaurant", "cafe", "hotel", "eatfit"
        ],
        "Fuel": [
            "petrol", "diesel", "fuel", "oil", "indian oil",
            "hp", "bharat petroleum", "shell"
        ],
        "Shopping": [
            "amazon", "flipkart", "myntra", "ajio", "meesho",
            "snapdeal", "store", "mart"
        ],
        "Groceries": [
            "bigbasket", "blinkit", "zepto", "instamart",
            "dmart", "grocery"
        ],
        "Travel": [
            "uber", "ola", "rapido", "irctc", "makemytrip",
            "yatra", "redbus"
        ],
        "Entertainment": [
            "netflix", "prime", "hotstar", "spotify",
            "bookmyshow", "sony liv"
        ],
        "Utilities": [
            "electricity", "power", "water", "gas",
            "bill", "recharge"
        ],
        "Education": [
            "udemy", "coursera", "byju", "unacademy",
            "college", "school", "exam"
        ],
        "Healthcare": [
            "hospital", "clinic", "pharmacy", "apollo",
            "medplus", "1mg", "pharmeasy"
        ],
        "Banking & Finance": [
            "emi", "loan", "interest", "insurance",
            "mutual fund", "sip", "credit card"
        ],
        "Transfer Out": [
            "paid to"
        ]
    }

    for category, keywords in categories.items():
        if any(keyword in d for keyword in keywords):
            return category

    return "Other Expense"

def parse_line(line):
    date_match = re.search(r"([A-Z][a-z]{2} \d{2}, \d{4})", line)
    date = (
        pd.to_datetime(date_match.group(1), format="%b %d, %Y")
        if date_match else None
    )

    time_match = re.search(
        r"\b(\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?)\b",
        line,
        re.IGNORECASE
    )
    time_str = time_match.group(1) if time_match else None

    if date is not None and time_str:
        datetime = pd.to_datetime(
            f"{date.strftime('%b %d, %Y')} {time_str}",
            errors="coerce"
        )
    else:
        datetime = date  # fallback to date only

    amount_match = re.search(r"₹([\d,]+\.?\d*)", line)
    amount = (
        float(amount_match.group(1).replace(",", ""))
        if amount_match else 0.0
    )
    type_match = re.search(r"\b(CREDIT|DEBIT)\b", line)
    txn_type = type_match.group(1) if type_match else "UNKNOWN"
    desc_match = re.search(
        r"(Received from|Paid to|Cashback from|Transfer to)\s(.+?)\s(CREDIT|DEBIT)",
        line,
        re.IGNORECASE
    )
    desc = desc_match.group(2) if desc_match else line.strip()
    utr_match = re.search(
        r"\bUTR(?:\s*No\.?)?[:\-\s]*([0-9]+)\b",
        line,
        re.IGNORECASE
    )
    utr = utr_match.group(1) if utr_match else None
    return {
        "date": date,
        "time": time_str,
        "datetime": datetime,
        "description": desc,
        "type": txn_type,
        "amount": amount,
        "category": categorize(desc, txn_type),
        "UTR_No": utr
    }

   

@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    contents = await file.read()
    pdf_bytes = io.BytesIO(contents)
    texts = []
    with pdfplumber.open(pdf_bytes) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            texts.append(text)
    raw_text = "\n".join(texts)


    lines = raw_text.split("\n")


    footer_phrases = [
        "this is an automatically generated statement",
        "the recipient specified in this document"
    ]

  
    clean_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("Page"):
            continue
        if "system generated statement" in line.lower():
            continue
        if line.startswith("Transaction Statement for"):
            continue
        if line.startswith("Date Transaction"):
            continue

        if any(phrase in line.lower() for phrase in footer_phrases):
            break  
        clean_lines.append(line)

    f_lines=[]
    for i in range(len(clean_lines)):
        if re.search(
            r"\b(CREDIT|DEBIT)\b|\bUTR\s*No\b|\bTransaction\s*ID\b",
            clean_lines[i],
            re.IGNORECASE
        ):
            f_lines.append(clean_lines[i])
    rows = []
    j = 0

    while j < len(f_lines):
        current_line = f_lines[j]
        if (
            j + 2 < len(f_lines)
            and re.search(r"\bUTR\s*No\b", f_lines[j + 2], re.IGNORECASE)
        ):
            combined_line = current_line + " " + f_lines[j + 1]+ " " + f_lines[j + 2]
            rows.append(combined_line)
            j += 3
        else:
            rows.append(current_line+ " " + f_lines[j + 1] )
            j += 2

    nrows = [parse_line(line) for line in rows]
    df = pd.DataFrame(nrows)

    return {
        "transactions": df.to_dict(orient="records"),
        "count": len(df)
    }
