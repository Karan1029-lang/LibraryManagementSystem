"""Library Management System (console app, SQLite storage).

Run:  python library_management.py
No extra installs needed: sqlite3 ships with Python.
"""

import sqlite3
from datetime import date, timedelta

DB_FILE = "library.db"
LOAN_DAYS = 14          # days a book can be kept
FINE_PER_DAY = 2        # fine per day after the due date (Rs.)


# ---------- Database setup ----------
def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            book_id   INTEGER PRIMARY KEY AUTOINCREMENT,
            title     TEXT NOT NULL,
            author    TEXT NOT NULL,
            isbn      TEXT UNIQUE,
            copies    INTEGER NOT NULL DEFAULT 1 CHECK (copies >= 0)
        );
        CREATE TABLE IF NOT EXISTS members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL,
            email     TEXT UNIQUE,
            joined_on TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS loans (
            loan_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id     INTEGER NOT NULL REFERENCES books(book_id),
            member_id   INTEGER NOT NULL REFERENCES members(member_id),
            issue_date  TEXT NOT NULL,
            due_date    TEXT NOT NULL,
            return_date TEXT,
            fine        INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()


# ---------- Helpers ----------
def ask_int(prompt):
    while True:
        try:
            return int(input(prompt).strip())
        except ValueError:
            print("Please enter a number.")


def print_rows(rows, headers):
    if not rows:
        print("  (nothing found)")
        return
    widths = [len(h) for h in headers]
    data = [[str(r[h]) if r[h] is not None else "-" for h in headers] for r in rows]
    for row in data:
        widths = [max(w, len(c)) for w, c in zip(widths, row)]
    line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    print("  " + line)
    print("  " + "-" * len(line))
    for row in data:
        print("  " + " | ".join(c.ljust(w) for c, w in zip(row, widths)))


# ---------- Book operations ----------
def add_book(conn):
    title = input("Title: ").strip()
    author = input("Author: ").strip()
    isbn = input("ISBN (optional): ").strip() or None
    copies = ask_int("Number of copies: ")
    if not title or not author or copies < 1:
        print("Title, author and at least 1 copy are required.")
        return
    try:
        conn.execute(
            "INSERT INTO books (title, author, isbn, copies) VALUES (?, ?, ?, ?)",
            (title, author, isbn, copies),
        )
        conn.commit()
        print("Book added.")
    except sqlite3.IntegrityError:
        print("A book with that ISBN already exists.")


def list_books(conn):
    rows = conn.execute(
        "SELECT book_id, title, author, isbn, copies FROM books ORDER BY title"
    ).fetchall()
    print_rows(rows, ["book_id", "title", "author", "isbn", "copies"])


def search_books(conn):
    term = input("Search title/author: ").strip()
    rows = conn.execute(
        """SELECT book_id, title, author, isbn, copies FROM books
           WHERE title LIKE ? OR author LIKE ? ORDER BY title""",
        (f"%{term}%", f"%{term}%"),
    ).fetchall()
    print_rows(rows, ["book_id", "title", "author", "isbn", "copies"])


def remove_book(conn):
    book_id = ask_int("Book ID to remove: ")
    active = conn.execute(
        "SELECT COUNT(*) FROM loans WHERE book_id = ? AND return_date IS NULL",
        (book_id,),
    ).fetchone()[0]
    if active:
        print("Cannot remove: copies are currently issued.")
        return
    cur = conn.execute("DELETE FROM books WHERE book_id = ?", (book_id,))
    if cur.rowcount == 0:
        print("No such book.")
        return
    conn.commit()
    print("Book removed.")


# ---------- Member operations ----------
def add_member(conn):
    name = input("Member name: ").strip()
    email = input("Email (optional): ").strip() or None
    if not name:
        print("Name is required.")
        return
    try:
        cur = conn.execute(
            "INSERT INTO members (name, email, joined_on) VALUES (?, ?, ?)",
            (name, email, date.today().isoformat()),
        )
        conn.commit()
        print(f"Member added with ID {cur.lastrowid}.")
    except sqlite3.IntegrityError:
        print("A member with that email already exists.")


def list_members(conn):
    rows = conn.execute(
        "SELECT member_id, name, email, joined_on FROM members ORDER BY name"
    ).fetchall()
    print_rows(rows, ["member_id", "name", "email", "joined_on"])


# ---------- Issue / return ----------
def issue_book(conn):
    book_id = ask_int("Book ID: ")
    member_id = ask_int("Member ID: ")

    book = conn.execute("SELECT * FROM books WHERE book_id = ?", (book_id,)).fetchone()
    member = conn.execute("SELECT * FROM members WHERE member_id = ?", (member_id,)).fetchone()
    if not book or not member:
        print("Invalid book or member ID.")
        return
    if book["copies"] < 1:
        print("No copies available right now.")
        return
    already = conn.execute(
        "SELECT 1 FROM loans WHERE book_id=? AND member_id=? AND return_date IS NULL",
        (book_id, member_id),
    ).fetchone()
    if already:
        print("This member already has this book.")
        return

    today = date.today()
    due = today + timedelta(days=LOAN_DAYS)
    conn.execute(
        "INSERT INTO loans (book_id, member_id, issue_date, due_date) VALUES (?, ?, ?, ?)",
        (book_id, member_id, today.isoformat(), due.isoformat()),
    )
    conn.execute("UPDATE books SET copies = copies - 1 WHERE book_id = ?", (book_id,))
    conn.commit()
    print(f"Issued '{book['title']}' to {member['name']}. Due on {due}.")


def return_book(conn):
    book_id = ask_int("Book ID: ")
    member_id = ask_int("Member ID: ")
    loan = conn.execute(
        """SELECT * FROM loans
           WHERE book_id=? AND member_id=? AND return_date IS NULL""",
        (book_id, member_id),
    ).fetchone()
    if not loan:
        print("No active loan found for that book and member.")
        return

    today = date.today()
    due = date.fromisoformat(loan["due_date"])
    late_days = max((today - due).days, 0)
    fine = late_days * FINE_PER_DAY

    conn.execute(
        "UPDATE loans SET return_date = ?, fine = ? WHERE loan_id = ?",
        (today.isoformat(), fine, loan["loan_id"]),
    )
    conn.execute("UPDATE books SET copies = copies + 1 WHERE book_id = ?", (book_id,))
    conn.commit()
    print("Book returned.")
    if fine:
        print(f"Late by {late_days} day(s). Fine: Rs. {fine}")


def list_issued(conn):
    rows = conn.execute(
        """SELECT l.loan_id, b.title, m.name AS member, l.issue_date, l.due_date
           FROM loans l
           JOIN books b ON b.book_id = l.book_id
           JOIN members m ON m.member_id = l.member_id
           WHERE l.return_date IS NULL
           ORDER BY l.due_date"""
    ).fetchall()
    print_rows(rows, ["loan_id", "title", "member", "issue_date", "due_date"])


def list_overdue(conn):
    rows = conn.execute(
        """SELECT l.loan_id, b.title, m.name AS member, l.due_date,
                  (julianday('now') - julianday(l.due_date)) AS days_late
           FROM loans l
           JOIN books b ON b.book_id = l.book_id
           JOIN members m ON m.member_id = l.member_id
           WHERE l.return_date IS NULL AND l.due_date < date('now')
           ORDER BY l.due_date"""
    ).fetchall()
    rows = [dict(r, days_late=int(r["days_late"])) for r in rows]
    print_rows(rows, ["loan_id", "title", "member", "due_date", "days_late"])


# ---------- Menu ----------
MENU = """
===== LIBRARY MANAGEMENT SYSTEM =====
 1. Add book              6. List members
 2. List books            7. Issue book
 3. Search books          8. Return book
 4. Remove book           9. Issued books
 5. Add member           10. Overdue books
 0. Exit
"""

ACTIONS = {
    1: add_book, 2: list_books, 3: search_books, 4: remove_book,
    5: add_member, 6: list_members, 7: issue_book, 8: return_book,
    9: list_issued, 10: list_overdue,
}


def main():
    conn = get_connection()
    init_db(conn)
    while True:
        print(MENU)
        choice = ask_int("Choose an option: ")
        if choice == 0:
            print("Goodbye!")
            break
        action = ACTIONS.get(choice)
        if action:
            print()
            action(conn)
        else:
            print("Invalid option.")
    conn.close()


if __name__ == "__main__":
    main()
