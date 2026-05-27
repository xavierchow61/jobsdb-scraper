"""Render a sample Telegram card to console (no actual send)."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from scraper import format_telegram_card

sample = {
    "Job Title": "Senior Accountant - 5 days work / Year-end bonus",
    "Company": "ABC Trading (Hong Kong) Limited",
    "Salary": "HKD 30,000 - 45,000",
    "Location": "Central / Hong Kong Island",
    "Posted Date": "2026-05-15T08:30:00",
    "Work Type": "Full time",
    "Responsibilities": (
        "- Handle full set of accounts including AR/AP, GL, fixed assets and inventory\n"
        "- Prepare monthly management reports and consolidation accounts\n"
        "- Liaise with external auditors and tax representatives for annual audit\n"
        "- Review weekly aging reports and follow up with overseas customers\n"
        "- Supervise junior accounting staff and review their work for accuracy"
    ),
    "Requirements": (
        "- Bachelor degree in Accounting, Finance or related discipline\n"
        "- HKICPA / ACCA qualified or finalist preferred\n"
        "- Minimum 5 years relevant experience, preferably in trading industry\n"
        "- Proficient in MS Excel, Word and Chinese word processing\n"
        "- Good command of written and spoken English, Cantonese and Mandarin"
    ),
    "How to apply": "Please send your full CV with expected salary to hr@abctrading.com.hk",
    "URL": "https://hk.jobsdb.com/job/99999999",
}

card = format_telegram_card(sample, "jobsdb")
print(card)
print()
print(f"---\nTotal chars: {len(card)}")
