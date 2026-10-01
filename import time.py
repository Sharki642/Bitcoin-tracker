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
import tkinter.font as tkfont
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

BG, CARD, FG = "#1e1e1e", "#2a2a2e", "#d4d4d4"
GREEN, RED, GREY, YELLOW = "#4ec96b", "#f0616d", "#8a8a8a", "#e5c07b"
ORANGE, ORANGE_HOVER, ORANGE_PRESS = "#f7931a", "#ffa940", "#d97f0f"


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
ICON_B64 = (
    "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"
)


class RoundedButton(tk.Canvas):
    """Flacher Button mit runden Ecken und Hover-/Klick-Effekt."""

    def __init__(self, parent, text, command, parent_bg=CARD, radius=10, padx=18, pady=9):
        font = tkfont.Font(family="monospace", size=11, weight="bold")
        w = font.measure(text) + 2 * padx
        h = font.metrics("linespace") + 2 * pady
        super().__init__(parent, width=w, height=h, bg=parent_bg, bd=0,
                         highlightthickness=0, cursor="hand2")
        self.command, self.w, self.h = command, w, h
        r = radius
        pts = [r, 1, w - r, 1, w - 1, 1, w - 1, r, w - 1, h - r, w - 1, h - 1, w - r, h - 1,
               r, h - 1, 1, h - 1, 1, h - r, 1, r, 1, 1]
        self.shape = self.create_polygon(pts, smooth=True, fill=ORANGE, outline=ORANGE)
        self.create_text(w / 2, h / 2, text=text, fill="#1e1e1e", font=font)
        self.bind("<Enter>", lambda e: self._color(ORANGE_HOVER))
        self.bind("<Leave>", lambda e: self._color(ORANGE))
        self.bind("<ButtonPress-1>", lambda e: self._color(ORANGE_PRESS))
        self.bind("<ButtonRelease-1>", self._release)

    def _color(self, c):
        self.itemconfig(self.shape, fill=c, outline=c)

    def _release(self, e):
        inside = 0 <= e.x <= self.w and 0 <= e.y <= self.h
        self._color(ORANGE_HOVER if inside else ORANGE)
        if inside:
            self.command()


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
        root.geometry("720x430")
        root.configure(bg=BG)
        try:
            self._icon = tk.PhotoImage(data="".join(ICON_B64))  # Referenz behalten!
            root.iconphoto(True, self._icon)
        except tk.TclError:
            pass

        self.header = tk.Label(root, text="Lade …", font=("monospace", 24, "bold"),
                               bg=BG, fg=FG, pady=12)
        self.header.pack(fill="x")

        bar = tk.Frame(root, bg=CARD)
        bar.pack(fill="x", padx=10, pady=(0, 10), ipadx=10, ipady=8)
        RoundedButton(bar, "Bestand eingeben", self.set_amount).pack(side="left", padx=(10, 0))
        box = tk.Frame(bar, bg=CARD)
        box.pack(side="right", padx=(0, 10))
        self.value_label = tk.Label(box, text="", font=("monospace", 18, "bold"),
                                    bg=CARD, fg=FG, anchor="e")
        self.value_label.pack(anchor="e")
        self.pl_label = tk.Label(box, text="", font=("monospace", 10), bg=CARD, fg=FG, anchor="e")
        self.pl_label.pack(anchor="e")

        frame = tk.Frame(root, bg=BG)
        frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.scroll = tk.Scrollbar(frame, width=12, bd=0, relief="flat", highlightthickness=0,
                                   bg="#3c3c42", troughcolor=BG, activebackground="#55555c")
        self.scroll.pack(side="right", fill="y")
        self.text = tk.Text(frame, bg=BG, fg=FG, font=("monospace", 11), state="disabled",
                            yscrollcommand=self.scroll.set, bd=0, highlightthickness=0,
                            wrap="none", padx=6, pady=4)
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

        main = f"[{ts:%H:%M:%S}] {arrow} {price:>11,.2f} {cur} {pct_txt}"
        if hist:  # Verlauf komplett grau
            self.append_parts([(main + value_txt + suffix + "\n", "hist")])
        else:     # Kurs-Teil nach Kursbewegung, Wert-Teil nach Plus/Minus gegenüber Einzahlung
            self.append_parts([(main, tag), (value_txt + "\n", self.pl_tag(value))])
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

    def pl_tag(self, value):
        """'up' = im Plus, 'down' = im Minus, '' = neutral (gegenüber deinem eingegebenen Betrag)."""
        if self.invested is None or value is None:
            return ""
        diff = round(value - self.invested, 2)
        return "up" if diff > 0 else "down" if diff < 0 else ""

    def update_value(self):
        if self.amount is None or self.last is None:
            return
        value, cur = self.amount * self.last, self.cur.upper()
        color = {"up": GREEN, "down": RED, "": FG}[self.pl_tag(value)]
        self.value_label.config(text=f"{value:,.2f} {cur}", fg=color)
        if self.invested:
            pl = value - self.invested
            self.pl_label.config(text=f"{pl:+,.2f} {cur}  ({pl / self.invested * 100:+.2f}%)", fg=color)
        else:
            self.pl_label.config(text="")

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
        self.append_parts([(line, tag)])

    def append_parts(self, parts):
        at_bottom = self.text.yview()[1] >= 0.999
        self.text.config(state="normal")
        for text, tag in parts:
            self.text.insert("end", text, tag)
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
    