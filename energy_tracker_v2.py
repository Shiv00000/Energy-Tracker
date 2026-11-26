
import csv
import math
import os
import shutil
import sys
import traceback
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

# ---------------- SETTINGS ----------------
if getattr(sys, "frozen", False):          
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, "usage_data.csv")
BACKUP_FILE = os.path.join(BASE_DIR, "usage_data_backup.csv")
LOG_FILE = os.path.join(BASE_DIR, "error_log.txt")

HEAD = ["month", "appliance", "watts", "hours_per_day", "days", "kwh", "rate", "cost"]
DEFAULT_RATE = 7.0        # price per unit (kWh) - change to your current tariff
MAX_ROWS_SHOWN = 3000     # saved-data window shows newest rows first (filter by month for more)
MAX_BARS = 12             # biggest appliances drawn in a chart, the rest become "Others"
MAX_TREND_MONTHS = 24     # trend chart shows the latest 24 months
MONTH_FORMATS = ("%Y-%m", "%Y/%m", "%b-%y", "%B-%y", "%b %Y", "%B %Y", "%Y-%m-%d")


# =====================================================================
#  DATA LAYER (CSV)
# =====================================================================
def calc(watts, hours, days, rate):
    """units (kWh) = Watts x Hours x Days / 1000 ; cost = units x price."""
    kwh = watts * hours * days / 1000
    return kwh, kwh * rate


def parse_month(text):
    """Accepts 2026-10, 2026-9, 2026/10, Oct-26, Oct 2026 ... and returns '2026-10'."""
    text = str(text).strip()
    for fmt in MONTH_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    raise ValueError(f"bad month: {text!r}")


def read_rows():
    """Return (rows, skipped). Broken lines are skipped and counted, never crash."""
    rows, skipped = [], 0
    if not os.path.exists(CSV_FILE):
        return rows, skipped
    with open(CSV_FILE, newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                row = {
                    "month": parse_month(r["month"]),
                    "appliance": r["appliance"].strip(),
                    "watts": float(r["watts"]),
                    "hours": float(r["hours_per_day"]),
                    "days": float(r["days"]),
                    "kwh": float(r["kwh"]),
                    "rate": float(r["rate"]),
                    "cost": float(r["cost"]),
                }
            except (KeyError, ValueError, AttributeError, TypeError):
                skipped += 1
                continue
            nums = (row["watts"], row["hours"], row["days"], row["kwh"], row["rate"], row["cost"])
            if not row["appliance"] or not all(math.isfinite(n) for n in nums):
                skipped += 1
                continue
            rows.append(row)
    return rows, skipped


def write_rows(rows):
    """Write safely: temp file first, then replace. Keeps a backup of the old file."""
    tmp = CSV_FILE + ".tmp"
    rows = sorted(rows, key=lambda r: r["month"])          # stable sort
    try:
        with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(HEAD)
            for r in rows:
                w.writerow([r["month"], r["appliance"], r["watts"], r["hours"], r["days"],
                            round(r["kwh"], 4), r["rate"], round(r["cost"], 2)])
        if os.path.exists(CSV_FILE):
            try:
                shutil.copyfile(CSV_FILE, BACKUP_FILE)
            except OSError:
                pass
        os.replace(tmp, CSV_FILE)
    except OSError:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise


def save_month(month, items, rate):
    """Save one month. If the month already exists it is replaced. Returns rows saved."""
    rows, _ = read_rows()
    keep = [r for r in rows if r["month"] != month]
    new = []
    for name, w, h, d in items:
        kwh, cost = calc(w, h, d, rate)
        new.append({"month": month, "appliance": name, "watts": w, "hours": h,
                    "days": d, "kwh": kwh, "rate": rate, "cost": cost})
    write_rows(keep + new)
    return len(new)


# =====================================================================
#  ANALYSIS (no GUI - easy to test)
# =====================================================================
def aggregate(rows):
    """{month: {appliance_key: [display_name, kwh, cost]}}  (same name = same appliance)."""
    out = {}
    for r in rows:
        m = out.setdefault(r["month"], {})
        e = m.setdefault(r["appliance"].lower(), [r["appliance"], 0.0, 0.0])
        e[1] += r["kwh"]
        e[2] += r["cost"]
    return out


def pick_pair(months, prefer=None):
    """Default 'previous month' and 'this month' for the drop-downs."""
    if len(months) < 2:
        return "", ""
    if prefer in months:
        i = months.index(prefer)
        return (months[i - 1], prefer) if i > 0 else (prefer, months[1])
    return months[-2], months[-1]


def top_n(names, *series, n=MAX_BARS, others=True):
    """Keep the n biggest items. The rest are merged into 'Others' (or dropped if others=False)."""
    order = sorted(range(len(names)), key=lambda i: max(s[i] for s in series), reverse=True)
    keep, rest = order[:n], order[n:]
    out_names = [names[i] for i in keep]
    out = [[s[i] for i in keep] for s in series]
    if rest and others:
        out_names.append(f"Others ({len(rest)})")
        for o, s in zip(out, series):
            o.append(math.fsum(s[i] for i in rest))
    return out_names, out


def bill_summary(month, items, rate):
    names = [i[0] for i in items]
    kwhs = [calc(w, h, d, rate)[0] for _, w, h, d in items]
    costs = [k * rate for k in kwhs]
    total_kwh, total_cost = math.fsum(kwhs), math.fsum(costs)
    top = max(range(len(names)), key=lambda i: kwhs[i])
    share = kwhs[top] / total_kwh * 100
    text = (
        f"BILL FOR {month}\n"
        f"• Total electricity used: {total_kwh:.2f} units (kWh)\n"
        f"• Price per unit: ₹{rate:.2f}\n"
        f"• Estimated bill: ₹{total_cost:.2f}\n\n"
        f"In simple words: {names[top]} uses the most power, about {share:.0f}% of your bill "
        f"(₹{costs[top]:.2f}). Using it fewer hours is the easiest way to save money.\n\n"
        f"How it is calculated: units = Watts x Hours x Days / 1000, then bill = units x price.\n"
        f"Press 'Save Month' to keep this data so you can compare it later."
    )
    return text, names, kwhs, costs, total_cost


def compare_data(agg, m1, m2):
    """Compare two saved months. The older month is always 'a', the newer 'b'."""
    a, b = sorted((m1, m2))
    da, db = agg[a], agg[b]
    zero = ["", 0.0, 0.0]
    keys = list(set(da) | set(db))
    keys.sort(key=lambda k: (-max(da.get(k, zero)[1], db.get(k, zero)[1]), k))
    return {
        "a": a, "b": b,
        "names": [(db.get(k) or da[k])[0] for k in keys],
        "ka": [da.get(k, zero)[1] for k in keys],
        "kb": [db.get(k, zero)[1] for k in keys],
        "units_a": math.fsum(v[1] for v in da.values()),
        "units_b": math.fsum(v[1] for v in db.values()),
        "bill_a": math.fsum(v[2] for v in da.values()),
        "bill_b": math.fsum(v[2] for v in db.values()),
    }


def compare_text(c):
    a, b = c["a"], c["b"]
    diff = c["bill_b"] - c["bill_a"]
    udiff = c["units_b"] - c["units_a"]
    pct = f" ({abs(diff) / c['bill_a'] * 100:.1f}%)" if c["bill_a"] else ""
    if diff < -0.005:
        verdict = "BETTER - you spent less in " + b
    elif diff > 0.005:
        verdict = "WORSE - you spent more in " + b
    else:
        verdict = "about the same"
    lines = [
        f"{b} compared with {a}",
        f"• {a}: {c['units_a']:.2f} units, bill ₹{c['bill_a']:.2f}",
        f"• {b}: {c['units_b']:.2f} units, bill ₹{c['bill_b']:.2f}",
        f"• Difference: ₹{abs(diff):.2f}{pct} -> {verdict}.",
    ]
    chg = [y - x for x, y in zip(c["ka"], c["kb"])]
    worst = max(range(len(chg)), key=lambda i: chg[i])
    best = min(range(len(chg)), key=lambda i: chg[i])
    lines.append("")
    if chg[worst] > 0.005:
        lines.append(f"Biggest increase: {c['names'][worst]} ({chg[worst]:+.2f} kWh)")
    if chg[best] < -0.005:
        lines.append(f"Biggest saving: {c['names'][best]} ({chg[best]:+.2f} kWh)")
    new = [n for n, x, y in zip(c["names"], c["ka"], c["kb"]) if x == 0 and y > 0]
    gone = [n for n, x, y in zip(c["names"], c["ka"], c["kb"]) if x > 0 and y == 0]
    if new:
        lines.append(f"New in {b}: " + ", ".join(new[:5]) + (" ..." if len(new) > 5 else ""))
    if gone:
        lines.append(f"Not used in {b}: " + ", ".join(gone[:5]) + (" ..." if len(gone) > 5 else ""))
    if abs(diff) > 0.005 and abs(udiff) > 0.005 and (diff > 0) != (udiff > 0):
        lines.append("Note: the price per unit was different in the two months, so the bill "
                     "and the units moved in opposite directions.")
    if diff > 0.005 and chg[worst] > 0.005:
        lines.append(f"Tip: {c['names'][worst]} is the main reason the bill went up. "
                     f"Try using it fewer hours.")
    return "\n".join(lines)


def trend_data(agg):
    months = sorted(agg)[-MAX_TREND_MONTHS:]
    units = [math.fsum(v[1] for v in agg[m].values()) for m in months]
    bills = [math.fsum(v[2] for v in agg[m].values()) for m in months]
    return months, units, bills


# ---------------- charts (return Matplotlib Figures) ----------------
def bill_figure(month, names, kwhs, costs, total_cost):
    bar_names, (bar_costs,) = top_n(names, costs, others=False)
    pie_names, (pie_kwh,) = top_n(names, kwhs, n=8)
    fig = Figure(figsize=(10, 4.8))
    a1, a2 = fig.add_subplot(121), fig.add_subplot(122)
    a1.bar(bar_names, bar_costs, color="#4c9be8")
    a1.set_title("Cost per appliance (₹)")
    if len(names) > len(bar_names):
        a1.set_xlabel(f"Top {len(bar_names)} of {len(names)} appliances shown")
    a1.tick_params(axis="x", rotation=30)
    for lab in a1.get_xticklabels():
        lab.set_ha("right")
    a2.pie(pie_kwh, labels=pie_names, autopct="%1.0f%%")
    a2.set_title("Share of electricity used")
    fig.suptitle(f"{month}  |  Total bill ₹{total_cost:.2f}")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def compare_figure(c):
    names, (ka, kb) = top_n(c["names"], c["ka"], c["kb"], others=False)
    fig = Figure(figsize=(11, 5))
    a1, a2 = fig.add_subplot(121), fig.add_subplot(122)
    x, w = list(range(len(names))), 0.38
    a1.bar([i - w / 2 for i in x], ka, w, label=c["a"], color="#9aa0a6")
    a1.bar([i + w / 2 for i in x], kb, w, label=c["b"], color="#4c9be8")
    a1.set_xticks(x)
    a1.set_xticklabels(names, rotation=30, ha="right")
    a1.set_title("Units used per appliance (kWh)")
    if len(c["names"]) > len(names):
        a1.set_xlabel(f"Top {len(names)} of {len(c['names'])} appliances shown (totals include all)")
    a1.legend()
    bills = [c["bill_a"], c["bill_b"]]
    bars = a2.bar([c["a"], c["b"]], bills, color=["#9aa0a6", "#4c9be8"])
    for rect, val in zip(bars, bills):
        a2.text(rect.get_x() + rect.get_width() / 2, val, f"₹{val:.0f}", ha="center", va="bottom")
    a2.set_title("Total bill (₹)")
    a2.set_ylim(0, max(bills) * 1.15 if max(bills) > 0 else 1)
    fig.suptitle(f"{c['b']} vs {c['a']}")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def trend_figure(months, units, bills):
    fig = Figure(figsize=(11, 4.8))
    a1, a2 = fig.add_subplot(121), fig.add_subplot(122)
    a1.plot(months, bills, marker="o", color="#e8744c")
    a1.set_title("Bill per month (₹)")
    a2.bar(months, units, color="#4c9be8")
    a2.set_title("Units used per month (kWh)")
    for ax in (a1, a2):
        ax.tick_params(axis="x", rotation=45)
        for lab in ax.get_xticklabels():
            lab.set_ha("right")
    fig.tight_layout()
    return fig


# =====================================================================
#  GUI
# =====================================================================
class App:
    def __init__(self, root):
        self.root = root
        root.title("Home Appliance Energy Tracker")
        root.geometry("840x800")
        self.items = []          # (name, watts, hours, days) currently in the table
        self.skipped = 0

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
        for i, (txt, key) in enumerate([("Name", "name"), ("Power (Watts)", "watts"),
                                        ("Hours/day", "hours"), ("Days used/month", "days")]):
            ttk.Label(form, text=txt).grid(row=0, column=i, padx=5)
            ttk.Entry(form, textvariable=self.vars[key], width=14).grid(row=1, column=i, padx=5, pady=5)
        ttk.Button(form, text="Add", command=self.add).grid(row=1, column=4, padx=5)
        ttk.Button(form, text="Delete selected", command=self.delete).grid(row=1, column=5, padx=5)

        cols = ("Appliance", "Watts", "Hours/day", "Days", "kWh", "Cost (₹)")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=7)
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=110, anchor="center")
        self.tree.pack(fill="x", padx=10, pady=5)

        row1 = ttk.Frame(root)
        row1.pack(pady=3)
        ttk.Button(row1, text="Calculate Bill + Graph", command=self.show_bill).grid(row=0, column=0, padx=5)
        ttk.Button(row1, text="Save Month", command=self.save).grid(row=0, column=1, padx=5)
        ttk.Button(row1, text="Clear Table (new month)", command=self.clear).grid(row=0, column=2, padx=5)

        cmp_box = ttk.LabelFrame(root, text="Compare saved months")
        cmp_box.pack(fill="x", padx=10, pady=5)
        self.cmp_a, self.cmp_b = tk.StringVar(), tk.StringVar()
        ttk.Label(cmp_box, text="Previous month:").grid(row=0, column=0, padx=5, pady=5)
        self.cb_a = ttk.Combobox(cmp_box, textvariable=self.cmp_a, state="readonly", width=10)
        self.cb_a.grid(row=0, column=1)
        ttk.Label(cmp_box, text="This month:").grid(row=0, column=2, padx=5)
        self.cb_b = ttk.Combobox(cmp_box, textvariable=self.cmp_b, state="readonly", width=10)
        self.cb_b.grid(row=0, column=3)
        ttk.Button(cmp_box, text="Compare", command=self.compare).grid(row=0, column=4, padx=8)
        ttk.Button(cmp_box, text="Trend (all months)", command=self.trend).grid(row=0, column=5, padx=4)
        ttk.Button(cmp_box, text="View Saved Data", command=self.view_saved).grid(row=0, column=6, padx=4)

        self.status = tk.StringVar()
        ttk.Label(root, textvariable=self.status).pack()
        self.bar = ttk.Progressbar(root, mode="indeterminate", length=300)
        self.bar.pack(pady=3)

        self.text = tk.Text(root, height=12, wrap="word", bg="#f7f7f7")
        self.text.pack(fill="both", expand=True, padx=10, pady=5)
        ttk.Button(root, text="Exit", command=self.exit_app).pack(pady=5)

        # the app keeps running after any error; it only closes when you choose Exit
        root.report_callback_exception = self.on_error
        root.protocol("WM_DELETE_WINDOW", self.exit_app)

        rows = self.load(quiet=True)
        months = sorted(aggregate(rows or []))
        self.set_months(months)
        self.say("Welcome! Add your appliances, press 'Calculate Bill + Graph', then 'Save Month'.\n"
                 "Save two or more different months, then use 'Compare saved months'.\n\n"
                 f"Saved months found: {', '.join(months) if months else 'none yet'}\n"
                 f"Data file: {CSV_FILE}")

    # ----- basics -----
    def say(self, msg):
        self.text.delete("1.0", "end")
        self.text.insert("end", msg)

    def on_error(self, exc, val, tb):
        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now()}\n{text}\n")
        except OSError:
            pass
        self.bar.stop()
        self.status.set("")
        messagebox.showerror("Something went wrong (the app is still running)", str(val))

    def exit_app(self):
        if messagebox.askyesno("Exit", "Close the app?"):
            self.root.destroy()

    def busy(self, msg, func):
        """Show the progress bar while a (possibly slow) job runs."""
        self.status.set(msg)
        self.bar.start(10)
        self.root.update_idletasks()
        try:
            return func()
        finally:
            self.bar.stop()
            self.status.set("")

    def load(self, quiet=False):
        """Read the CSV. Returns the list of rows, or None if the file can't be read."""
        try:
            rows, self.skipped = read_rows()
            return rows
        except OSError as e:
            if not quiet:
                messagebox.showerror("Cannot read data file",
                                     f"Could not read:\n{CSV_FILE}\n\nIf it is open in Excel, close it.\n\n{e}")
            return None

    def set_months(self, months, prefer=None):
        self.cb_a["values"] = months
        self.cb_b["values"] = months
        if prefer or self.cmp_a.get() not in months or self.cmp_b.get() not in months:
            a, b = pick_pair(months, prefer)
            self.cmp_a.set(a)
            self.cmp_b.set(b)

    def get_rate(self):
        try:
            r = float(self.rate.get())
            if not (0 < r < 1e6):
                raise ValueError
            return r
        except ValueError:
            messagebox.showerror("Error", "Enter a valid price per unit (a number above 0).")
            return None

    def get_month(self):
        try:
            m = parse_month(self.month.get())
        except ValueError:
            messagebox.showerror("Error", "Month must look like 2026-10 (year-month).")
            return None
        self.month.set(m)
        return m

    def show_fig(self, fig, title):
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("1000x560")
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, win)   # zoom / save-as-image buttons
        toolbar.update()
        canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    # ----- table of appliances -----
    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        try:
            rate = float(self.rate.get())
        except ValueError:
            rate = DEFAULT_RATE
        for n, w, h, d in self.items:
            kwh, cost = calc(w, h, d, rate)
            self.tree.insert("", "end", values=(n, w, h, d, f"{kwh:.2f}", f"{cost:.2f}"))

    def add(self):
        try:
            name = self.vars["name"].get().strip()
            w, h, d = (float(self.vars[k].get()) for k in ("watts", "hours", "days"))
            if not name or len(name) > 40 or not (0 < w <= 100000) \
                    or not (0 < h <= 24) or not (0 < d <= 31):
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a name, watts above 0, hours 0-24 and days 1-31.")
            return
        self.items.append((name, w, h, d))
        for v in self.vars.values():
            v.set("")
        self.refresh()

    def delete(self):
        for i in sorted((self.tree.index(s) for s in self.tree.selection()), reverse=True):
            del self.items[i]
        self.refresh()

    def clear(self):
        self.items.clear()
        self.refresh()
        self.say("Table cleared. Change the month, then add that month's appliances.")

    # ----- actions -----
    def show_bill(self):
        rate, month = self.get_rate(), self.get_month()
        if rate is None or month is None:
            return
        if not self.items:
            messagebox.showinfo("Info", "Add at least one appliance first.")
            return
        text, names, kwhs, costs, total = bill_summary(month, self.items, rate)
        self.say(text)
        self.show_fig(bill_figure(month, names, kwhs, costs, total), f"Bill {month}")

    def save(self):
        rate, month = self.get_rate(), self.get_month()
        if rate is None or month is None:
            return
        if not self.items:
            messagebox.showinfo("Info", "Nothing to save. Add appliances first.")
            return
        rows = self.load()
        if rows is None:
            return
        old = sum(1 for r in rows if r["month"] == month)
        if old and not messagebox.askyesno(
                "Replace?", f"{month} is already saved ({old} entries).\nReplace it with the table?"):
            return
        try:
            n = self.busy("Saving...", lambda: save_month(month, list(self.items), rate))
        except OSError as e:
            messagebox.showerror("Could not save",
                                 f"Could not write:\n{CSV_FILE}\n\nIf it is open in Excel, close it and "
                                 f"press Save again.\n\n{e}")
            return
        months = sorted(aggregate(self.load() or []))
        self.set_months(months, prefer=month)
        self.say(f"Saved {n} appliance(s) for {month}.\nFile: {CSV_FILE}\n"
                 f"Saved months: {', '.join(months)}\n\n"
                 + ("Now press 'Compare' to see this month against the previous one."
                    if len(months) > 1 else
                    "Save another month (change the Month box, press 'Clear Table', add its "
                    "appliances, Save) and then you can compare."))
        messagebox.showinfo("Saved", f"Saved {n} appliance(s) for {month}.\n\n{CSV_FILE}")

    def compare(self):
        rows = self.busy("Loading saved data...", self.load)
        if rows is None:
            return
        agg = aggregate(rows)
        months = sorted(agg)
        self.set_months(months)
        if len(months) < 2:
            messagebox.showinfo("Compare", f"Saved months: {', '.join(months) or 'none'}.\n\n"
                                           "Save at least two different months first.")
            return
        a, b = self.cmp_a.get(), self.cmp_b.get()
        if a not in agg or b not in agg:
            messagebox.showinfo("Compare", "Pick two saved months in the drop-down boxes.")
            return
        if a == b:
            messagebox.showinfo("Compare", "Pick two different months.")
            return
        c = compare_data(agg, a, b)
        self.say(compare_text(c))
        self.show_fig(compare_figure(c), f"{c['b']} vs {c['a']}")

    def trend(self):
        rows = self.busy("Loading saved data...", self.load)
        if rows is None:
            return
        agg = aggregate(rows)
        if len(agg) < 2:
            messagebox.showinfo("Trend", "Save at least two different months first.")
            return
        months, units, bills = trend_data(agg)
        best = min(range(len(bills)), key=lambda i: bills[i])
        worst = max(range(len(bills)), key=lambda i: bills[i])
        self.say(f"Trend over {len(months)} month(s): {months[0]} to {months[-1]}\n"
                 f"• Lowest bill: {months[best]} (₹{bills[best]:.2f})\n"
                 f"• Highest bill: {months[worst]} (₹{bills[worst]:.2f})\n"
                 f"• Latest bill: {months[-1]} (₹{bills[-1]:.2f})")
        self.show_fig(trend_figure(months, units, bills), "Trend")

    def view_saved(self):
        rows = self.busy("Loading saved data...", self.load)
        if rows is None:
            return
        if not rows:
            messagebox.showinfo("Saved data", f"No saved data yet.\n\nFile checked:\n{CSV_FILE}")
            return
        win = tk.Toplevel(self.root)
        win.title("Saved data")
        win.geometry("800x520")
        months = sorted({r["month"] for r in rows}, reverse=True)
        head = ttk.Frame(win)
        head.pack(fill="x", padx=8, pady=5)
        ttk.Label(head, text="Show month:").pack(side="left")
        pick = tk.StringVar(value="All")
        cb = ttk.Combobox(head, textvariable=pick, values=["All"] + months, state="readonly", width=10)
        cb.pack(side="left", padx=5)
        info = tk.StringVar()
        ttk.Label(head, textvariable=info).pack(side="left", padx=10)

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=8)
        cols = ("Month", "Appliance", "Watts", "Hours/day", "Days", "kWh", "Cost (₹)")
        tv = ttk.Treeview(body, columns=cols, show="headings", height=18)
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=100, anchor="center")
        sb = ttk.Scrollbar(body, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def fill(*_):
            chosen = [r for r in rows if pick.get() in ("All", r["month"])]
            chosen.sort(key=lambda r: (r["month"], r["appliance"].lower()), reverse=True)
            shown = chosen[:MAX_ROWS_SHOWN]
            tv.delete(*tv.get_children())
            for r in shown:
                tv.insert("", "end", values=(r["month"], r["appliance"], r["watts"], r["hours"],
                                             r["days"], f"{r['kwh']:.2f}", f"{r['cost']:.2f}"))
            tot_k = math.fsum(r["kwh"] for r in chosen)
            tot_c = math.fsum(r["cost"] for r in chosen)
            more = f" (showing newest {len(shown)})" if len(chosen) > len(shown) else ""
            info.set(f"{len(chosen)} rows{more} | {tot_k:.2f} kWh | ₹{tot_c:.2f}")

        cb.bind("<<ComboboxSelected>>", fill)
        fill()
        ttk.Label(win, text=f"File: {CSV_FILE}").pack(pady=4)
        note = f"{self.skipped} unreadable line(s) in the file were ignored." if self.skipped else ""
        self.say(f"Saved months: {', '.join(sorted(months))}\n{note}")


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
