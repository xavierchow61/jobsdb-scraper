"""Smoke-test the 18-HK-district JobsDB filter end-to-end.

For each district:
  1. Build the search URL via scraper.build_search_url()
  2. Fetch it with curl_cffi (impersonate chrome124)
  3. Parse SEEK_REDUX_DATA and count jobs returned
  4. Report status code, job count, and first job title for sanity

Run with:
    python _test_jobsdb_districts.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import scraper
from curl_cffi import requests


JOBSDB_DISTRICTS = {
    "":                              "全港",
    "Central and Western District":  "中西區",
    "Wan Chai District":             "灣仔區",
    "Eastern District":              "東區",
    "Southern District":             "南區",
    "Yau Tsim Mong District":        "油尖旺區",
    "Sham Shui Po District":         "深水埗區",
    "Kowloon City District":         "九龍城區",
    "Wong Tai Sin District":         "黃大仙區",
    "Kwun Tong District":            "觀塘區",
    "Kwai Tsing District":           "葵青區",
    "Tsuen Wan District":            "荃灣區",
    "Tuen Mun District":             "屯門區",
    "Yuen Long District":            "元朗區",
    "Northern District":             "北區",
    "Tai Po District":               "大埔區",
    "Sha Tin District":              "沙田區",
    "Sai Kung District":             "西貢區",
    "Islands District":              "離島區",
}


def main():
    keyword = "Accountant"
    session = requests.Session(impersonate="chrome124")

    print(f"\nWarm-up GET {scraper.BASE} ...")
    try:
        r = session.get(scraper.BASE, headers=scraper.HEADERS, timeout=30)
        print(f"  warm-up status: {r.status_code}")
    except Exception as e:
        print(f"  warm-up failed: {e}")

    print(f"\n{'區':<8} {'狀態':<8} {'工作數':<8} 第一個 job title")
    print("-" * 80)

    results = []
    for slug, label in JOBSDB_DISTRICTS.items():
        url = scraper.build_search_url(keyword, slug, page=1)
        try:
            r = session.get(url, headers=scraper.HEADERS, timeout=30)
            status = r.status_code
        except Exception as e:
            print(f"{label:<8} ERR      —        {e}")
            results.append((label, "ERR", 0, str(e)))
            continue

        if status != 200:
            print(f"{label:<8} {status:<8} —        (URL: {url})")
            results.append((label, status, 0, ""))
            time.sleep(1.5)
            continue

        try:
            data = scraper.fetch_redux(session, url)
            jobs = (data.get("results") or {}).get("results", {}).get("jobs") or []
            first_title = (jobs[0].get("title") if jobs else "(no jobs)") or "(untitled)"
            print(f"{label:<8} {status:<8} {len(jobs):<8} {first_title[:55]}")
            results.append((label, status, len(jobs), first_title))
        except Exception as e:
            # Already got 200, so we have HTML but failed to parse SEEK_REDUX_DATA
            print(f"{label:<8} {status:<8} parse?   {e}")
            results.append((label, status, -1, str(e)))

        time.sleep(1.5)

    # Summary
    ok = sum(1 for _, s, n, _ in results if s == 200 and n > 0)
    no_jobs = sum(1 for _, s, n, _ in results if s == 200 and n == 0)
    blocked = sum(1 for _, s, _, _ in results if s != 200 and s != "ERR")
    err = sum(1 for _, s, _, _ in results if s == "ERR")
    print("-" * 80)
    print(f"\nSummary: {ok} OK with jobs · {no_jobs} OK but 0 jobs · "
          f"{blocked} blocked / non-200 · {err} errors")


if __name__ == "__main__":
    main()
