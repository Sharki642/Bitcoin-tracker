#!/usr/bin/env python3
"""Bitcoin Price Tracker – CoinGecko API, nur Standardbibliothek.

Beispiele:
    python btc_tracker.py                    # EUR, alle 60s
    python btc_tracker.py -c usd -i 30       # USD, alle 30s
    python btc_tracker.py --log btc.csv      # zusätzlich in CSV loggen
"""
import argparse
import csv
import json
import os
import time
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies={cur}&include_24hr_change=true"
)

GREEN, RED, RESET = "\033[92m", "\033[91m", "\033[0m"


def get_price(cur):
    req = Request(URL.format(cur=cur), headers={"User-Agent": "btc-tracker"})
    with urlopen(req, timeout=10) as r:
        data = json.load(r)["bitcoin"]
    return data[cur], data[f"{cur}_24h_change"]


def log_row(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "price", "change_24h_pct"])
        w.writerow(row)


def main():
    p = argparse.ArgumentParser(description="Bitcoin Price Tracker")
    p.add_argument("-c", "--currency", default="eur", help="eur, usd, chf, ...")
    p.add_argument("-i", "--interval", type=int, default=60, help="Sekunden (min. 30)")
    p.add_argument("--log", metavar="DATEI", help="Preise in CSV speichern")
    args = p.parse_args()

    cur = args.currency.lower()
    interval = max(args.interval, 30)  # Rate-Limit der Free-API
    last = None

    print(f"BTC/{cur.upper()} Tracker – Strg+C zum Beenden\n")
    try:
        while True:
            try:
                price, change = get_price(cur)
                now = datetime.now().strftime("%H:%M:%S")

                if last is None or price == last:
                    arrow, color = "•", RESET
                elif price > last:
                    arrow, color = "▲", GREEN
                else:
                    arrow, color = "▼", RED

                c24 = GREEN if change >= 0 else RED
                print(
                    f"[{now}] {color}{arrow} {price:>12,.2f} {cur.upper()}{RESET}"
                    f"   24h: {c24}{change:+.2f}%{RESET}"
                )
                if args.log:
                    log_row(args.log, [datetime.now().isoformat(timespec="seconds"), price, round(change, 2)])
                last = price
            except (URLError, KeyError, TimeoutError, json.JSONDecodeError) as e:
                print(f"Fehler: {e} – neuer Versuch in {interval}s")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()