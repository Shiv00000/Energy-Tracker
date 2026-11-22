"""
Home Appliance Energy Tracker
Tkinter + Matplotlib + MySQL + CSV (pure Python)

Install:  pip install matplotlib mysql-connector-python
Set your MySQL password in DB below. If MySQL is not available,
the app still works using the CSV file only.
"""
import csv
import math
import os
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

try:
    import mysql.connector
except ImportError:
    mysql = None

# ---------------- SETTINGS ----------------
DB = dict(host="", user="root", password="123456", database="school", port=3306 )
CSV_FILE = "usage_data.csv"
CSV_HEAD = ["month", "appliance", "watts", "hours_per_day", "days", "kwh", "rate", "cost"]
DEFAULT_RATE = 7.0  # price per unit (kWh) - change to your current tariff


# ---------------- DATA LAYER ----------------
def db_connect():
    cfg = DB.copy()
    name = cfg.pop("database")
    conn = mysql.connector.connect(connection_timeout=5, **cfg)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS {name}")
    conn.database = name
    cur.execute(
        "CREATE TABLE IF NOT EXISTS usage_data ("
        "id INT AUTO_INCREMENT PRIMARY KEY, month CHAR(7), appliance VARCHAR(50), "
        "watts FLOAT, hours_per_day FLOAT, days FLOAT, kwh FLOAT, rate FLOAT, cost FLOAT)"
    )
    return conn


def calc(watts, hours, days, rate):
    kwh = watts * hours * days / 1000  # Wh -> kWh
    return kwh, kwh * rate


def save_data(month, items, rate):
    """Save to CSV (always) and MySQL (if reachable). Re-saving a month replaces it."""
    rows = []
    for name, w, h, d in items:
        kwh, cost = calc(w, h, d, rate)
        rows.append([month, name, w, h, d, round(kwh, 3), rate, round(cost, 2)])

    old = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline="") as f:
            old = [r for r in csv.reader(f) if r and r[0] != month and r[0] != "month"]
    with open(CSV_FILE, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(CSV_HEAD)
        wr.writerows(old + rows)

    if mysql is None:
        return "Saved to CSV only (mysql-connector not installed)."
    try:
        conn = db_connect()
        cur = conn.cursor()
        cur.execute("DELETE FROM usage_data WHERE month=%s", (month,))
        cur.executemany(
            "INSERT INTO usage_data (month,appliance,watts,hours_per_day,days,kwh,rate,cost) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        conn.commit()
        conn.close()
        return "Saved to MySQL and CSV."
    except Exception as e:
        return f"Saved to CSV only (MySQL error: {e})"


def load_all():
    """Return list of (month, appliance, kwh, cost). MySQL first, CSV as fallback."""
    if mysql is not None:
        try:
            conn = db_connect()
            cur = conn.cursor()
            cur.execute("SELECT month, appliance, kwh, cost FROM usage_data")
            data = [(m, a, float(k), float(c)) for m, a, k, c in cur.fetchall()]
            conn.close()
            if data:
                return data
        except Exception:
            pass
    data = []
    if os.path.exists(CSV_FILE):
        with open(CSV_FILE, newline="") as f:
            for r in csv.DictReader(f):
                data.append((r["month"], r["appliance"], float(r["kwh"]), float(r["cost"])))
    return data


# ---------------- GUI ----------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Home Appliance Energy Tracker")
        root.geometry("760x640")
        self.items = []  # (name, watts, hours, days)

        top = ttk.LabelFrame(root, text="Settings")
        top.pack(fill="x", padx=10, pady=5)
        ttk.Label(top, text="Month (YYYY-MM):").grid(row=0, column=0, padx=5, pady=5)
        self.month = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        ttk.Entry(top, textvariable=self.month, width=10).grid(row=0, column=1)
        ttk.Label(top, text="Price per unit (₹/kWh):").grid(row=0, column=2, padx=5)
        self.rate = tk.StringVar(value=str(DEFAULT_RATE))
        ttk.Entry(top, textvariable=self.rate, width=8).grid(row=0, column=3)

        form = ttk.LabelFrame(root, text="Add appliance")
        form.pack(fill="x", padx=10, pady=5)
        self.vars = {k: tk.StringVar() for k in ("name", "watts", "hours", "days")}
        labels = [("Name", "name"), ("Power (Watts)", "watts"),
                  ("Hours/day", "hours"), ("Days used/month", "days")]
        for i, (txt, key) in enumerate(labels):
            ttk.Label(form, text=txt).grid(row=0, column=i, padx=5)
            ttk.Entry(form, textvariable=self.vars[key], width=14).grid(row=1, column=i, padx=5, pady=5)
        ttk.Button(form, text="Add", command=self.add).grid(row=1, column=4, padx=5)
        ttk.Button(form, text="Delete selected", command=self.delete).grid(row=1, column=5, padx=5)

        cols = ("Appliance", "Watts", "Hours/day", "Days", "kWh", "Cost (₹)")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=8)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="center")
        self.tree.pack(fill="x", padx=10, pady=5)

        btns = ttk.Frame(root)
        btns.pack(pady=5)
        ttk.Button(btns, text="Calculate Bill + Graph", command=self.show_bill).grid(row=0, column=0, padx=5)
        ttk.Button(btns, text="Save Data (MySQL + CSV)", command=self.save).grid(row=0, column=1, padx=5)
        ttk.Button(btns, text="Compare with Previous Month", command=self.compare).grid(row=0, column=2, padx=5)

        self.bar = ttk.Progressbar(root, mode="indeterminate", length=300)
        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status).pack()
        self.bar.pack(pady=3)

        self.text = tk.Text(root, height=10, wrap="word", bg="#f7f7f7")
        self.text.pack(fill="both", expand=True, padx=10, pady=5)

    # ----- helpers -----
    def get_rate(self):
        try:
            r = float(self.rate.get())
            if r <= 0:
                raise ValueError
            return r
        except ValueError:
            messagebox.showerror("Error", "Enter a valid price per unit.")
            return None

    def get_month(self):
        try:
            datetime.strptime(self.month.get(), "%Y-%m")
            return self.month.get()
        except ValueError:
            messagebox.showerror("Error", "Month must look like 2026-10")
            return None

    def say(self, msg):
        self.text.delete("1.0", "end")
        self.text.insert("end", msg)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        rate = float(self.rate.get() or DEFAULT_RATE)
        for n, w, h, d in self.items:
            kwh, cost = calc(w, h, d, rate)
            self.tree.insert("", "end", values=(n, w, h, d, f"{kwh:.2f}", f"{cost:.2f}"))

    def buffered(self, work, done, msg):
        """Run slow work in a thread with a moving progress bar so the window never freezes."""
        self.status.set(msg)
        self.bar.start(10)
        box = {}

        def runner():
            try:
                box["result"] = work()
            except Exception as e:
                box["error"] = e

        t = threading.Thread(target=runner, daemon=True)
        t.start()

        def poll():
            if t.is_alive():
                self.root.after(100, poll)
            else:
                self.bar.stop()
                self.status.set("")
                if "error" in box:
                    messagebox.showerror("Error", str(box["error"]))
                else:
                    done(box.get("result"))
        poll()

    def show_fig(self, fig, title):
        win = tk.Toplevel(self.root)
        win.title(title)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)

    # ----- actions -----
    def add(self):
        try:
            name = self.vars["name"].get().strip()
            w, h, d = (float(self.vars[k].get()) for k in ("watts", "hours", "days"))
            if not name or w <= 0 or not (0 < h <= 24) or not (0 < d <= 31):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a name, watts > 0, hours 1-24, days 1-31.")
            return
        self.items.append((name, w, h, d))
        for v in self.vars.values():
            v.set("")
        self.refresh()

    def delete(self):
        for sel in self.tree.selection():
            del self.items[self.tree.index(sel)]
        self.refresh()

    def show_bill(self):
        rate, month = self.get_rate(), self.get_month()
        if rate is None or month is None:
            return
        if not self.items:
            messagebox.showinfo("Info", "Add at least one appliance first.")
            return
        names = [i[0] for i in self.items]
        kwhs = [calc(w, h, d, rate)[0] for _, w, h, d in self.items]
        costs = [k * rate for k in kwhs]
        total_kwh, total_cost = math.fsum(kwhs), math.fsum(costs)
        top = max(range(len(names)), key=lambda i: kwhs[i])
        share = kwhs[top] / total_kwh * 100

        self.say(
            f"BILL FOR {month}\n"
            f"• Total electricity used: {total_kwh:.2f} units (kWh)\n"
            f"• Price per unit: ₹{rate:.2f}\n"
            f"• Estimated bill: ₹{total_cost:.2f}\n\n"
            f"In simple words: {names[top]} uses the most power, about {share:.0f}% of your bill "
            f"(₹{costs[top]:.2f}). Using it fewer hours is the easiest way to save money.\n\n"
            f"How it is calculated: units = Watts × Hours × Days ÷ 1000, then bill = units × price."
        )

        fig = Figure(figsize=(10, 4.5))
        a1, a2 = fig.add_subplot(121), fig.add_subplot(122)
        a1.bar(names, costs, color="#4c9be8")
        a1.set_title("Cost per appliance (₹)")
        a1.tick_params(axis="x", rotation=30)
        a2.pie(kwhs, labels=names, autopct="%1.0f%%")
        a2.set_title("Share of electricity used")
        fig.suptitle(f"{month}  |  Total ₹{total_cost:.2f}")
        fig.tight_layout()
        self.show_fig(fig, "Bill & Usage")

    def save(self):
        rate, month = self.get_rate(), self.get_month()
        if rate is None or month is None:
            return
        if not self.items:
            messagebox.showinfo("Info", "Nothing to save.")
            return
        items = list(self.items)
        self.buffered(lambda: save_data(month, items, rate),
                      lambda msg: messagebox.showinfo("Saved", msg), "Saving data...")

    def compare(self):
        month = self.get_month()
        if month is None:
            return
        self.buffered(load_all, lambda data: self.plot_compare(data, month), "Loading saved data...")

    def plot_compare(self, data, month):
        by_month = {}
        for m, a, k, c in data:
            e = by_month.setdefault(m, {})
            old = e.get(a, (0, 0))
            e[a] = (old[0] + k, old[1] + c)
        if month not in by_month:
            messagebox.showinfo("Info", f"No saved data for {month}. Save it first.")
            return
        earlier = sorted(m for m in by_month if m < month)
        if not earlier:
            messagebox.showinfo("Info", "No earlier month found to compare with.")
            return
        prev = earlier[-1]
        cur_d, prev_d = by_month[month], by_month[prev]
        apps = sorted(set(cur_d) | set(prev_d))
        cur_k = [cur_d.get(a, (0, 0))[0] for a in apps]
        prev_k = [prev_d.get(a, (0, 0))[0] for a in apps]
        tc = math.fsum(v[1] for v in cur_d.values())
        tp = math.fsum(v[1] for v in prev_d.values())
        tk_c, tk_p = math.fsum(cur_k), math.fsum(prev_k)

        diff = tc - tp
        pct = (diff / tp * 100) if tp else 0
        change = [c - p for c, p in zip(cur_k, prev_k)]
        worst = max(range(len(apps)), key=lambda i: change[i])
        best = min(range(len(apps)), key=lambda i: change[i])
        verdict = ("BETTER - you used less electricity 👍" if diff < 0
                   else "WORSE - you used more electricity" if diff > 0 else "the same")
        self.say(
            f"{month} vs {prev}\n"
            f"• {prev}: {tk_p:.2f} units, ₹{tp:.2f}\n"
            f"• {month}: {tk_c:.2f} units, ₹{tc:.2f}\n"
            f"• Difference: ₹{abs(diff):.2f} ({abs(pct):.1f}%) → this month is {verdict}.\n\n"
            f"Biggest increase: {apps[worst]} ({change[worst]:+.2f} kWh)\n"
            f"Biggest saving: {apps[best]} ({change[best]:+.2f} kWh)"
        )

        fig = Figure(figsize=(10, 4.5))
        a1, a2 = fig.add_subplot(121), fig.add_subplot(122)
        x, w = range(len(apps)), 0.38
        a1.bar([i - w / 2 for i in x], prev_k, w, label=prev, color="#aaaaaa")
        a1.bar([i + w / 2 for i in x], cur_k, w, label=month, color="#4c9be8")
        a1.set_xticks(list(x))
        a1.set_xticklabels(apps, rotation=30)
        a1.set_title("Units used per appliance (kWh)")
        a1.legend()
        a2.bar([prev, month], [tp, tc], color=["#aaaaaa", "#4c9be8"])
        a2.set_title("Total bill (₹)")
        fig.tight_layout()
        self.show_fig(fig, "Month Comparison")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
