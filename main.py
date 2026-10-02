#!/usr/bin/env python3
"""Bitcoin Price Tracker mit GUI (PySide6) – Binance (Fallback: CoinGecko).

- Nur der Fenster-HINTERGRUND ist durchsichtig, der Text bleibt voll sichtbar
- Jede Zeile wird automatisch in btc_log.csv gespeichert (inkl. Wert deines Anteils)
- Dein Bestand wird in btc_state.json gespeichert und beim Start automatisch geladen
- Beim Start werden die letzten 3 Minuten Kursverlauf nachgeladen und mitgeloggt
- Fenster-Icon: logo.png neben dem Script

Installation:  pip install PySide6

Beispiele:
    python main.py                    # EUR, alle 60s
    python main.py -c usd -i 30       # USD, alle 30s
    python main.py --opacity 0.3      # Hintergrund noch durchsichtiger (0 = ganz klar, 1 = solid)
"""
import argparse
import csv
import json
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

BASE = Path(__file__).resolve().parent  # Dateien liegen neben dem Script, egal von wo gestartet
STATE_FILE = BASE / "btc_state.json"
DEFAULT_LOG = BASE / "btc_log.csv"
LOGO_FILE = BASE / "logo.png"  # Fenster-Icon
HISTORY_MINUTES = 3
MAX_LINES = 5000  # älteste Zeilen im Fenster werden entfernt (die CSV bleibt vollständig)

COINGECKO = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies={cur}"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
LOG_HEADER = ["timestamp", "price", "change_pct_vs_last", "btc_amount", "value", "source"]

FG, GREEN, RED, GREY, YELLOW = "#e4e4e4", "#4ec96b", "#f0616d", "#9a9a9a", "#e5c07b"
ORANGE, ORANGE_HOVER, ORANGE_PRESS = "#f7931a", "#ffa940", "#d97f0f"
TAG_COLORS = {"": FG, "up": GREEN, "down": RED, "hist": GREY, "info": YELLOW}


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
SCROLLBAR_CSS = """
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,130); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""


class TrackerApp(QWidget):
    def __init__(self, cur, interval, log_path, opacity):
        super().__init__()
        self.cur, self.interval, self.log_path = cur, interval, log_path
        self.bg_alpha = int(255 * opacity)  # nur der Hintergrund, Text bleibt solid
        self.last = None
        self.pending_eur = None
        self.q = queue.Queue()
        self.stop = threading.Event()

        state = load_state()
        self.amount = state.get("btc_amount")      # BTC-Menge
        self.invested = state.get("invested")      # Betrag, den du eingegeben hast
        prepare_log(self.log_path)

        self.setWindowTitle(f"Bitcoin Tracker – BTC/{cur.upper()}")
        self.setWindowIcon(QIcon(str(LOGO_FILE)))  # fehlt die Datei, bleibt das System-Icon
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(720, 430)

        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont).family()

        def font(size, bold=False):
            f = QFont(mono, size)
            f.setBold(bold)
            return f

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 4, 10, 10)
        root.setSpacing(8)

        self.header = QLabel("Lade …")
        self.header.setFont(font(24, True))
        self.header.setAlignment(Qt.AlignCenter)
        self.header.setStyleSheet(f"color: {FG}; padding: 6px;")
        root.addWidget(self.header)

        # Karte: Button links, Wert rechts
        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet("#card { background: rgba(255,255,255,24); border-radius: 8px; }")
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 10, 14, 10)

        btn = QPushButton("Bestand eingeben")
        btn.setFont(font(11, True))
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {ORANGE}; color: #1e1e1e; border: none;"
            f" border-radius: 10px; padding: 9px 18px; }}"
            f"QPushButton:hover {{ background: {ORANGE_HOVER}; }}"
            f"QPushButton:pressed {{ background: {ORANGE_PRESS}; }}")
        btn.clicked.connect(self.set_amount)
        row.addWidget(btn)
        row.addStretch()

        box = QVBoxLayout()
        box.setSpacing(0)
        self.value_label = QLabel("")
        self.value_label.setFont(font(18, True))
        self.value_label.setAlignment(Qt.AlignRight)
        self.pl_label = QLabel("")
        self.pl_label.setFont(font(10))
        self.pl_label.setAlignment(Qt.AlignRight)
        box.addWidget(self.value_label)
        box.addWidget(self.pl_label)
        row.addLayout(box)
        root.addWidget(card)

        # Log
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(font(11))
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.log.setMaximumBlockCount(MAX_LINES)
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setStyleSheet(f"QPlainTextEdit {{ background: transparent; color: {FG}; }}" + SCROLLBAR_CSS)
        root.addWidget(self.log, 1)

        if self.amount is not None:
            inv = f", eingezahlt {self.invested:,.2f} {cur.upper()}" if self.invested else ""
            self.append(f"Bestand geladen: {self.amount:.8f} BTC{inv}\n", "info")
        self.append(f"Log: {self.log_path}\n", "info")

        threading.Thread(target=self.worker, daemon=True).start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(200)

    # --- Hintergrund halbtransparent zeichnen (Text/Widgets bleiben solid) ---
    def paintEvent(self, _event):
        QPainter(self).fillRect(self.rect(), QColor(30, 30, 30, self.bg_alpha))

    # --- Hintergrund-Thread ---
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
            self.header.setStyleSheet(f"color: {TAG_COLORS[tag]}; padding: 6px;")
            self.header.setText(f"{price:,.2f} {cur}")
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
        color = TAG_COLORS[self.pl_tag(value)]
        self.value_label.setStyleSheet(f"color: {color};")
        self.value_label.setText(f"{value:,.2f} {cur}")
        self.pl_label.setStyleSheet(f"color: {color};")
        if self.invested:
            pl = value - self.invested
            self.pl_label.setText(f"{pl:+,.2f} {cur}  ({pl / self.invested * 100:+.2f}%)")
        else:
            self.pl_label.setText("")

    def save(self):
        save_state({"btc_amount": self.amount, "invested": self.invested,
                    "currency": self.cur, "saved_at": datetime.now().isoformat(timespec="seconds")})

    def set_amount(self):
        cur = self.cur.upper()
        s, ok = QInputDialog.getText(self, "Bestand", f"Wie viel {cur} hast du in Bitcoin?\n(z.B. 500 oder 250,50)")
        if not ok:
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
        bar = self.log.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2  # nur autoscrollen, wenn ganz unten
        cursor = QTextCursor(self.log.document())
        cursor.movePosition(QTextCursor.End)
        for text, tag in parts:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(TAG_COLORS[tag]))
            cursor.insertText(text, fmt)
        if at_bottom:
            QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))  # erst nach dem Layout

    def closeEvent(self, event):
        self.stop.set()
        event.accept()


def main():
    p = argparse.ArgumentParser(description="Bitcoin Price Tracker (GUI)")
    p.add_argument("-c", "--currency", default="eur", help="eur, usd, chf, ...")
    p.add_argument("-i", "--interval", type=int, default=60, help="Sekunden (min. 10)")
    p.add_argument("--log", metavar="DATEI", default=str(DEFAULT_LOG),
                   help=f"Log-Datei (Standard: {DEFAULT_LOG.name} neben dem Script)")
    p.add_argument("--opacity", type=float, default=0.6,
                   help="Deckkraft des HINTERGRUNDS 0-1 (0 = ganz klar, 1 = solid). Text bleibt immer klar.")
    args = p.parse_args()

    app = QApplication(sys.argv[:1])
    win = TrackerApp(args.currency.lower(), max(args.interval, 10), args.log,
                     min(max(args.opacity, 0.0), 1.0))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()