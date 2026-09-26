"""Выполняет запросы из sql/queries.sql, печатает результаты и сверяет их с цифрами README и дашборда.

Запуск: python3 run_sql.py
Код возврата 1, если хоть одна сверка не сошлась — SQL и дашборд считают один и тот же поток событий
разными способами (SQL и JS), поэтому расхождение означало бы ошибку в одном из расчётов.
"""
import math
import os
import re
import sqlite3
import sys

import load_db

HERE = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.join(HERE, "sql", "queries.sql")


def load_queries():
    text = open(SQL_PATH, encoding="utf-8").read()
    parts = re.split(r"^-- name: (\w+)\s*$", text, flags=re.M)
    return dict(zip(parts[1::2], (p.strip() for p in parts[2::2])))


def run(con, sql):
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, cur.fetchall()


def show(name, cols, rows):
    print(f"\n== {name} ==")
    cells = [cols] + [["" if v is None else str(v) for v in r] for r in rows]
    widths = [max(len(str(row[i])) for row in cells) for i in range(len(cols))]
    for k, row in enumerate(cells):
        print("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
        if k == 0:
            print("  ".join("-" * w for w in widths))


def p_value(z):
    """Двусторонний p для z-статистики: 2·(1 − Φ(|z|)) = erfc(|z|/√2)."""
    return math.erfc(abs(z) / math.sqrt(2))


def main():
    if not os.path.exists(load_db.DB_PATH):
        load_db.main()
    con = sqlite3.connect(load_db.DB_PATH)
    queries = load_queries()
    res = {name: run(con, sql) for name, sql in queries.items()}
    for name, (cols, rows) in res.items():
        show(name, cols, rows)

    failures = []

    def check(label, actual, expected):
        ok = actual == expected
        print(f"  [{'OK' if ok else 'FAIL'}] {label}: {actual}" + ("" if ok else f"  (ожидалось {expected})"))
        if not ok:
            failures.append(label)

    print("\n== Сверка с README и дашбордом ==")

    funnel = res["funnel"][1]
    check("воронка, пользователи по шагам", [r[2] for r in funnel], [640, 500, 312, 214, 191, 153])
    check("воронка, конверсия шагов, %", [r[3] for r in funnel], [None, 78.1, 62.4, 68.6, 89.3, 80.1])
    check("сквозная конверсия, %", funnel[-1][4], 23.9)

    rev = res["revenue"][1][0]
    check("выручка / средний чек, ₸", (rev[1], rev[2]), (1_038_000, 6784))

    ch = {r[0]: (r[1], r[3]) for r in res["channels"][1]}
    check("канал organic_search, CR %", ch["organic_search"][1], 30.7)
    check("канал offline_flyer, CR %", ch["offline_flyer"][1], 15.4)
    check("канал email_digest, CR %", ch["email_digest"][1], 18.3)
    check("канал telegram_channel, CR %", ch["telegram_channel"][1], 26.7)
    check("канал instagram_ads, пользователи / CR %", ch["instagram_ads"], (187, 19.8))

    pf = {r[0]: r[1] for r in res["payment_failures"][1]}
    check("сбои оплаты, всего", pf["ИТОГО"], 49)
    check("сбои по кодам", {k: pf[k] for k in ("insufficient_funds", "card_declined", "3ds_timeout", "gateway_timeout")},
          {"insufficient_funds": 20, "card_declined": 12, "3ds_timeout": 10, "gateway_timeout": 7})
    check("доля сбоев от начатых оплат, %", [r[2] for r in res["payment_failures"][1] if r[0] == "ИТОГО"][0], 25.7)
    check("оплат со второй попытки", dict(res["payment_retry"][1])[2], 11)

    sold_out = sum(r[2] for r in res["drop_reasons"][1] if r[1] == "sold_out")
    check("sold_out, пользователи", sold_out, 29)

    cohorts = res["cohorts"][1]
    check("когорты, размеры", [r[1] for r in cohorts], [128, 160, 160, 174, 18])
    check("когорты, сквозная конверсия, %", [r[6] for r in cohorts], [22.7, 23.1, 27.5, 22.4, 22.2])

    ab = {r[0]: r for r in res["ab_test"][1]}
    form, booked, paid = ab["Переход в форму"], ab["Бронь создана"], ab["Оплачено"]
    check("A/B, размеры групп", (form[5], form[6]), (255, 245))
    check("A/B, переход в форму A→B, %", (form[1], form[2]), (52.2, 73.1))
    check("A/B, разница в форму / бронь / оплату, п.п.", (form[3], booked[3], paid[3]), (20.9, 11.3, 7.2))
    p_form, p_booked, p_paid = (p_value(r[4]) for r in (form, booked, paid))
    print(f"  p-value по z-статистике из SQL: форма {p_form:.4f}, бронь {p_booked:.3f}, оплата {p_paid:.3f}")
    check("A/B, значимость (форма и бронь значимы, оплата — нет)",
          (p_form < 0.001, round(p_booked, 3), round(p_paid, 3)), (True, 0.011, 0.080))

    statuses = {r[0]: r[1] for r in res["user_status"][1]}
    check("статус paid = число оплативших", statuses["paid"], 153)
    check("статусы покрывают всех пользователей", sum(statuses.values()), 640)

    print(f"\n{'Все сверки сошлись.' if not failures else 'Расхождения: ' + ', '.join(failures)}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
