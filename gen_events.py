import json, random, hashlib
from datetime import datetime, timedelta

random.seed(20260920)

CHANNELS = {
    # channel: (share, intent_mult, pay_mult)
    "instagram_ads": (0.30, 1.00, 0.97),
    "organic_search": (0.22, 1.18, 1.05),
    "telegram_channel": (0.18, 1.12, 1.02),
    "referral_friend": (0.14, 1.32, 1.08),
    "email_digest": (0.10, 0.86, 1.03),
    "offline_flyer": (0.06, 0.70, 0.95),
}
DEVICES = [("mobile", 0.68), ("desktop", 0.24), ("tablet", 0.08)]
CITIES = [("Алматы", 0.52), ("Астана", 0.28), ("Шымкент", 0.12), ("Караганда", 0.08)]

WORKSHOPS = [
    ("ws_101", "Роспись керамики", 7500, 12),
    ("ws_102", "Робототехника LEGO", 9000, 10),
    ("ws_103", "Мыловарение", 5500, 16),
    ("ws_104", "Слайм-лаборатория", 4500, 20),
    ("ws_105", "Мультстудия: стоп-моушен", 11000, 8),
    ("ws_106", "Кулинарный: пицца", 6500, 14),
]
WORKSHOP_W = [0.20, 0.18, 0.14, 0.16, 0.12, 0.20]
# per-workshop pull on booking intent (quality/price fit)
WS_INTENT = {"ws_101": 1.06, "ws_102": 0.92, "ws_103": 1.10, "ws_104": 1.14, "ws_105": 0.82, "ws_106": 1.00}

PAY_METHODS = [("card", 0.74), ("kaspi_pay", 0.21), ("apple_pay", 0.05)]
PAY_ERRORS = [
    ("insufficient_funds", 0.38),
    ("3ds_timeout", 0.27),
    ("gateway_timeout", 0.19),
    ("card_declined", 0.16),
]

BASE = {
    "event_view": 0.72,
    "booking_started": 0.48,
    "booking_created": 0.74,
    "payment_initiated": 0.88,
    "payment_success": 0.76,
}

def pick(pairs):
    r, acc = random.random(), 0.0
    for name, w in pairs:
        acc += w
        if r <= acc:
            return name
    return pairs[-1][0]

def pick_ws():
    r, acc = random.random(), 0.0
    for w, p in zip(WORKSHOPS, WORKSHOP_W):
        acc += p
        if r <= acc:
            return w
    return WORKSHOPS[-1]

START = datetime(2026, 7, 6, 8, 0)  # пилотный запуск, 4 недели
N_USERS = 640
events = []
eid = 0

def add(name, ts, user, session, ch, dev, city, props):
    global eid
    eid += 1
    events.append({
        "event_id": f"evt_{eid:05d}",
        "event_name": name,
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%S+05:00"),
        "user_id": user,
        "session_id": session,
        "source": {"channel": ch, "device": dev, "city": city},
        "properties": props,
    })

chan_pairs = [(c, v[0]) for c, v in CHANNELS.items()]

for i in range(N_USERS):
    uid = f"u_{4100 + i * 7}"
    ch = pick(chan_pairs)
    intent_m, pay_m = CHANNELS[ch][1], CHANNELS[ch][2]
    dev = pick(DEVICES)
    city = pick(CITIES)
    sess = "s_" + hashlib.md5(f"{uid}{ch}{i}".encode()).hexdigest()[:10]
    t = START + timedelta(days=random.random() * 28, hours=random.random() * 12)

    add("catalog_view", t, uid, sess, ch, dev, city,
        {"list_size": 6, "filter": random.choice(["all", "age_5_8", "age_9_12", "weekend"]),
         "load_ms": int(random.gauss(820, 260))})

    ws_id, ws_title, price, cap = pick_ws()
    seats_left = random.randint(0, cap - 2)

    # step 2: карточка мастер-класса
    t += timedelta(seconds=random.randint(12, 180))
    if random.random() > BASE["event_view"] * min(intent_m, 1.25):
        continue
    add("event_view", t, uid, sess, ch, dev, city,
        {"workshop_id": ws_id, "workshop_title": ws_title, "price_kzt": price,
         "capacity": cap, "seats_left": seats_left})

    # step 3: открыл форму бронирования
    t += timedelta(seconds=random.randint(20, 240))
    if random.random() > BASE["booking_started"] * intent_m * WS_INTENT[ws_id]:
        continue
    add("booking_started", t, uid, sess, ch, dev, city,
        {"workshop_id": ws_id, "workshop_title": ws_title, "price_kzt": price, "seats_left": seats_left})

    # step 4: бронирование создано (FR-2, FR-3)
    t += timedelta(seconds=random.randint(30, 300))
    if seats_left == 0:
        add("booking_rejected", t, uid, sess, ch, dev, city,
            {"workshop_id": ws_id, "workshop_title": ws_title, "reason": "sold_out", "seats_left": 0})
        continue
    if random.random() > BASE["booking_created"] * (1.04 if dev == "desktop" else 0.98):
        add("booking_abandoned", t, uid, sess, ch, dev, city,
            {"workshop_id": ws_id, "workshop_title": ws_title,
             "reason": random.choice(["form_validation_error", "left_page", "changed_date"])})
        continue
    bid = "bk_" + hashlib.md5(f"{uid}{ws_id}{i}".encode()).hexdigest()[:8]
    add("booking_created", t, uid, sess, ch, dev, city,
        {"booking_id": bid, "workshop_id": ws_id, "workshop_title": ws_title,
         "price_kzt": price, "status": "Reserved", "child_age": random.randint(5, 12),
         "seats_left_after": seats_left - 1})

    # step 5: инициирована оплата (FR-4)
    t += timedelta(seconds=random.randint(25, 400))
    if random.random() > BASE["payment_initiated"]:
        add("booking_expired", t + timedelta(minutes=30), uid, sess, ch, dev, city,
            {"booking_id": bid, "status": "Cancelled", "reason": "payment_timeout"})
        continue
    method = pick(PAY_METHODS)
    add("payment_initiated", t, uid, sess, ch, dev, city,
        {"booking_id": bid, "workshop_id": ws_id, "amount_kzt": price,
         "currency": "KZT", "method": method, "status": "Pending Payment"})

    # step 6: успешная оплата
    t += timedelta(seconds=random.randint(8, 120))
    ok = random.random() <= BASE["payment_success"] * pay_m * (1.03 if method == "kaspi_pay" else 1.0)
    if not ok:
        add("payment_failed", t, uid, sess, ch, dev, city,
            {"booking_id": bid, "amount_kzt": price, "method": method,
             "error_code": pick(PAY_ERRORS), "status": "Pending Payment", "retry_allowed": True})
        # часть пользователей повторяет попытку
        if random.random() < 0.34:
            t += timedelta(minutes=random.randint(2, 45))
            if random.random() < 0.58:
                add("payment_success", t, uid, sess, ch, dev, city,
                    {"booking_id": bid, "amount_kzt": price, "method": method,
                     "status": "Paid", "attempt": 2, "confirmation_sent": True})
        continue
    add("payment_success", t, uid, sess, ch, dev, city,
        {"booking_id": bid, "amount_kzt": price, "method": method,
         "status": "Paid", "attempt": 1, "confirmation_sent": True})

events.sort(key=lambda e: e["ts"])
for n, e in enumerate(events, 1):
    e["event_id"] = f"evt_{n:05d}"

with open("/home/claude/events.json", "w", encoding="utf-8") as f:
    json.dump(events, f, ensure_ascii=False, separators=(",", ":"))

# --- быстрая сверка воронки ---
steps = ["catalog_view", "event_view", "booking_started", "booking_created", "payment_initiated", "payment_success"]
users = {}
for e in events:
    users.setdefault(e["user_id"], set()).add(e["event_name"])
print("users:", len(users), "events:", len(events))
prev = None
for s in steps:
    c = sum(1 for v in users.values() if s in v)
    line = f"{s:20s} {c:5d}"
    if prev:
        line += f"   step CR {c/prev*100:5.1f}%"
    print(line)
    prev = c
first = sum(1 for v in users.values() if "catalog_view" in v)
last = sum(1 for v in users.values() if "payment_success" in v)
print(f"end-to-end CR: {last/first*100:.2f}%")
print("payment_failed:", sum(1 for e in events if e["event_name"] == "payment_failed"))
import os
print("size KB:", round(os.path.getsize("/home/claude/events.json") / 1024, 1))
