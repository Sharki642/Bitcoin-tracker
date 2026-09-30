#!/usr/bin/env python3
"""Bitcoin Price Tracker mit GUI – Binance (Fallback: CoinGecko), nur Standardbibliothek.

- Jede Zeile wird automatisch in btc_log.csv gespeichert (inkl. Wert deines Anteils)
- Dein Bestand wird in btc_state.json gespeichert und beim Start automatisch geladen
- Beim Start werden die letzten 3 Minuten Kursverlauf nachgeladen und mitgeloggt

Beispiele:
    python btc_tracker_gui.py                  # EUR, alle 60s
    python btc_tracker_gui.py -c usd -i 30     # USD, alle 30s
    python btc_tracker_gui.py --log mein.csv   # anderer Log-Dateiname
"""
import argparse
import csv
import json
import queue
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import simpledialog
from urllib.error import URLError
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent  # Dateien liegen neben dem Script, egal von wo gestartet
STATE_FILE = BASE / "btc_state.json"
DEFAULT_LOG = BASE / "btc_log.csv"
HISTORY_MINUTES = 3
MAX_LINES = 5000  # älteste Zeilen im Fenster werden entfernt (die CSV bleibt vollständig)

COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies={cur}"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
LOG_HEADER = ["timestamp", "price", "change_pct_vs_last", "btc_amount", "value", "source"]

BG, FG = "#1e1e1e", "#d4d4d4"
GREEN, RED, GREY, YELLOW = "#4ec96b", "#f0616d", "#8a8a8a", "#e5c07b"


# ---------- Daten holen ----------
def _get_json(url):
    with urlopen(Request(url, headers=UA), timeout=10) as r:
        return json.load(r)


def binance_symbol(cur):
    return "BTC" + ("USDT" if cur == "usd" else cur.upper())


def from_binance(cur):
    return float(_get_json(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_symbol(cur)}")["price"])


def from_coingecko(cur):
    return float(_get_json(COINGECKO.format(cur=cur))["bitcoin"][cur])


def get_price(cur):
    errors = []
    for source in (from_binance, from_coingecko):
        try:
            return source(cur)
        except (URLError, KeyError, TimeoutError, json.JSONDecodeError, ValueError) as e:
            errors.append(f"{source.__name__}: {e}")
    raise URLError(" | ".join(errors))


def get_history(cur, minutes):
    """Schlusskurse der letzten abgeschlossenen Minuten -> [(datetime, preis), ...]"""
    url = (f"https://api.binance.com/api/v3/klines?symbol={binance_symbol(cur)}"
           f"&interval=1m&limit={minutes + 1}")
    candles = _get_json(url)[:-1]  # letzte Kerze läuft noch -> weglassen
    return [(datetime.fromtimestamp(k[6] / 1000), float(k[4])) for k in candles]


# ---------- Speichern ----------
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def prepare_log(path):
    """Log-Datei mit altem Format löschen, damit die neue mit passenden Spalten startet."""
    path = Path(path)
    if path.exists():
        with open(path, newline="") as f:
            first = next(csv.reader(f), None)
        if first != LOG_HEADER:
            path.unlink()


def log_row(path, row):
    path = Path(path)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        w.writerow(row)


# ---------- GUI ----------
class TrackerApp:
    def __init__(self, root, cur, interval, log_path):
        self.root, self.cur, self.interval, self.log_path = root, cur, interval, log_path
        self.last = None
        self.pending_eur = None
        self.q = queue.Queue()
        self.stop = threading.Event()

        state = load_state()
        self.amount = state.get("btc_amount")      # BTC-Menge
        self.invested = state.get("invested")      # Betrag, den du eingegeben hast
        prepare_log(self.log_path)

        root.title(f"Bitcoin Tracker – BTC/{cur.upper()}")
        root.geometry("720x380")
        root.configure(bg=BG)

        self.header = tk.Label(root, text="Lade …", font=("monospace", 18, "bold"),
                               bg=BG, fg=FG, pady=8)
        self.header.pack(fill="x")

        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=8, pady=(0, 6))
        tk.Button(bar, text="Bestand eingeben", command=self.set_amount).pack(side="left")
        self.value_label = tk.Label(bar, text="", font=("monospace", 14, "bold"), bg=BG, fg=FG)
        self.value_label.pack(side="right")

        frame = tk.Frame(root, bg=BG)
        frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.scroll = tk.Scrollbar(frame)
        self.scroll.pack(side="right", fill="y")
        self.text = tk.Text(frame, bg=BG, fg=FG, font=("monospace", 11), state="disabled",
                            yscrollcommand=self.scroll.set, bd=0, highlightthickness=0, wrap="none")
        self.text.pack(side="left", fill="both", expand=True)
        self.scroll.config(command=self.text.yview)
        self.text.tag_config("up", foreground=GREEN)
        self.text.tag_config("down", foreground=RED)
        self.text.tag_config("hist", foreground=GREY)
        self.text.tag_config("info", foreground=YELLOW)

        if self.amount is not None:
            inv = f", eingezahlt {self.invested:,.2f} {cur.upper()}" if self.invested else ""
            self.append(f"Bestand geladen: {self.amount:.8f} BTC{inv}\n", "info")
        self.append(f"Log: {self.log_path}\n", "info")

        threading.Thread(target=self.worker, daemon=True).start()
        root.after(200, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.close)

    # --- Hintergrund ---
    def worker(self):
        try:
            for ts, price in get_history(self.cur, HISTORY_MINUTES):
                self.q.put(("hist", ts, price))
        except Exception as e:
            self.q.put(("err", f"Verlauf nicht geladen: {e}"))
        while not self.stop.is_set():
            try:
                self.q.put(("live", datetime.now(), get_price(self.cur)))
            except Exception as e:  # Thread soll nie sterben
                self.q.put(("err", str(e)))
            self.stop.wait(self.interval)

    def poll(self):
        while not self.q.empty():
            msg = self.q.get()
            if msg[0] == "err":
                self.append(f"[{datetime.now():%H:%M:%S}] Fehler: {msg[1]}\n", "info")
            else:
                self.show_price(msg[1], msg[2], hist=(msg[0] == "hist"))
        self.root.after(200, self.poll)

    # --- Anzeige ---
    def show_price(self, ts, price, hist=False):
        prev, self.last = self.last, price

        if self.pending_eur is not None and not hist:  # Eingabe vor dem ersten Kurs
            self.amount, self.invested, self.pending_eur = self.pending_eur / price, self.pending_eur, None
            self.save()

        if prev is None or price == prev:
            arrow, tag = "•", ""
        elif price > prev:
            arrow, tag = "▲", "up"
        else:
            arrow, tag = "▼", "down"

        pct = None if prev is None else (price - prev) / prev * 100
        pct_txt = "    –    " if pct is None else f"{pct:+8.3f}%"
        value = None if self.amount is None else self.amount * price
        cur = self.cur.upper()
        value_txt = "" if value is None else f"   Wert: {value:>10,.2f} {cur}"
        suffix = "  (Verlauf)" if hist else ""

        self.append(f"[{ts:%H:%M:%S}] {arrow} {price:>11,.2f} {cur} {pct_txt}{value_txt}{suffix}\n",
                    "hist" if hist else tag)
        if not hist:
            self.header.config(text=f"{price:,.2f} {cur}",
                               fg=GREEN if tag == "up" else RED if tag == "down" else FG)
            self.update_value()

        log_row(self.log_path, [
            ts.isoformat(timespec="seconds"), price,
            "" if pct is None else round(pct, 4),
            "" if self.amount is None else f"{self.amount:.8f}",
            "" if value is None else round(value, 2),
            "history" if hist else "live",
        ])

    def update_value(self):
        if self.amount is not None and self.last is not None:
            self.value_label.config(text=f"{self.amount * self.last:,.2f} {self.cur.upper()}")

    def save(self):
        save_state({"btc_amount": self.amount, "invested": self.invested,
                    "currency": self.cur, "saved_at": datetime.now().isoformat(timespec="seconds")})

    def set_amount(self):
        cur = self.cur.upper()
        s = simpledialog.askstring("Bestand", f"Wie viel {cur} hast du in Bitcoin?\n(z.B. 500 oder 250,50)",
                                   parent=self.root)
        if s is None:
            return
        try:
            money = float(s.strip().replace(",", "."))
            if money < 0:
                raise ValueError
        except ValueError:
            self.append(f"[{datetime.now():%H:%M:%S}] Ungültige Eingabe: {s!r}\n", "info")
            return
        if self.last is None:
            self.pending_eur = money
            return
        self.amount, self.invested = money / self.last, money  # Euro -> BTC zum aktuellen Kurs
        self.save()
        self.update_value()

    def append(self, line, tag=""):
        at_bottom = self.text.yview()[1] >= 0.999
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
    p.add_argument("--log", metavar="DATEI", default=str(DEFAULT_LOG),
                   help=f"Log-Datei (Standard: {DEFAULT_LOG.name} neben dem Script)")
    args = p.parse_args()

    root = tk.Tk()
    TrackerApp(root, args.currency.lower(), max(args.interval, 10), args.log)
    root.mainloop()


if __name__ == "__main__":
    main()