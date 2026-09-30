#!/usr/bin/env python3
"""Bitcoin Price Tracker mit GUI – Binance (Fallback: CoinGecko), nur Standardbibliothek.

Beispiele:
    python btc_tracker_gui.py                  # EUR, alle 60s
    python btc_tracker_gui.py -c usd -i 30     # USD, alle 30s
    python btc_tracker_gui.py --log btc.csv    # zusätzlich in CSV loggen
"""
import argparse
import csv
import json
import os
import queue
import threading
import tkinter as tk
from datetime import datetime
from urllib.error import URLError
from urllib.request import Request, urlopen

COINGECKO = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin&vs_currencies={cur}&include_24hr_change=true"
)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
MAX_LINES = 5000  # älteste Zeilen werden entfernt, damit das Fenster nicht endlos wächst

BG, FG = "#1e1e1e", "#d4d4d4"
GREEN, RED = "#4ec96b", "#f0616d"


# ---------- Daten holen ----------
def _get_json(url):
    with urlopen(Request(url, headers=UA), timeout=10) as r:
        return json.load(r)


def from_binance(cur):
    quote = "USDT" if cur == "usd" else cur.upper()
    d = _get_json(f"https://api.binance.com/api/v3/ticker/24hr?symbol=BTC{quote}")
    return float(d["lastPrice"]), float(d["priceChangePercent"])


def from_coingecko(cur):
    d = _get_json(COINGECKO.format(cur=cur))["bitcoin"]
    return d[cur], d[f"{cur}_24h_change"]


def get_price(cur):
    errors = []
    for source in (from_binance, from_coingecko):
        try:
            return source(cur)
        except (URLError, KeyError, TimeoutError, json.JSONDecodeError) as e:
            errors.append(f"{source.__name__}: {e}")
    raise URLError(" | ".join(errors))


def log_row(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "price", "change_24h_pct"])
        w.writerow(row)


# ---------- GUI ----------
class TrackerApp:
    def __init__(self, root, cur, interval, log_path):
        self.root, self.cur, self.interval, self.log_path = root, cur, interval, log_path
        self.last = None
        self.q = queue.Queue()
        self.stop = threading.Event()

        root.title(f"Bitcoin Tracker – BTC/{cur.upper()}")
        root.geometry("460x360")
        root.configure(bg=BG)

        self.header = tk.Label(root, text="Lade …", font=("monospace", 18, "bold"),
                               bg=BG, fg=FG, pady=8)
        self.header.pack(fill="x")

        frame = tk.Frame(root, bg=BG)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.scroll = tk.Scrollbar(frame)
        self.scroll.pack(side="right", fill="y")

        self.text = tk.Text(frame, bg=BG, fg=FG, font=("monospace", 11), state="disabled",
                            yscrollcommand=self.scroll.set, bd=0, highlightthickness=0,
                            wrap="none")
        self.text.pack(side="left", fill="both", expand=True)
        self.scroll.config(command=self.text.yview)

        self.text.tag_config("up", foreground=GREEN)
        self.text.tag_config("down", foreground=RED)
        self.text.tag_config("err", foreground="#e5c07b")

        threading.Thread(target=self.worker, daemon=True).start()
        root.after(200, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def worker(self):
        while not self.stop.is_set():
            try:
                self.q.put(("ok", *get_price(self.cur)))
            except Exception as e:  # Thread soll nie sterben
                self.q.put(("err", str(e)))
            self.stop.wait(self.interval)

    def poll(self):
        while not self.q.empty():
            msg = self.q.get()
            if msg[0] == "ok":
                self.show_price(msg[1], msg[2])
            else:
                self.append(f"[{datetime.now():%H:%M:%S}] Fehler: {msg[1]}\n", "err")
        self.root.after(200, self.poll)

    def show_price(self, price, change):
        if self.last is None or price == self.last:
            arrow, tag = "•", ()
        elif price > self.last:
            arrow, tag = "▲", "up"
        else:
            arrow, tag = "▼", "down"
        self.last = price

        line = f"[{datetime.now():%H:%M:%S}] {arrow} {price:>12,.2f} {self.cur.upper()}   24h: {change:+.2f}%\n"
        self.append(line, tag)
        self.header.config(text=f"{price:,.2f} {self.cur.upper()}",
                           fg=GREEN if tag == "up" else RED if tag == "down" else FG)
        if self.log_path:
            log_row(self.log_path, [datetime.now().isoformat(timespec="seconds"), price, round(change, 2)])

    def append(self, line, tag=()):
        at_bottom = self.text.yview()[1] >= 0.999  # nur autoscrollen, wenn ganz unten
        self.text.config(state="normal")
        self.text.insert("end", line, tag)
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > MAX_LINES:
            self.text.delete("1.0", f"{lines - MAX_LINES + 1}.0")
        self.text.config(state="disabled")
        if at_bottom:
            self.text.see("end")

    def close(self):
        self.stop.set()
        self.root.destroy()


def main():
    p = argparse.ArgumentParser(description="Bitcoin Price Tracker (GUI)")
    p.add_argument("-c", "--currency", default="eur", help="eur, usd, chf, ...")
    p.add_argument("-i", "--interval", type=int, default=60, help="Sekunden (min. 10)")
    p.add_argument("--log", metavar="DATEI", help="Preise in CSV speichern")
    args = p.parse_args()

    root = tk.Tk()
    TrackerApp(root, args.currency.lower(), max(args.interval, 10), args.log)
    root.mainloop()


if __name__ == "__main__":
    main()