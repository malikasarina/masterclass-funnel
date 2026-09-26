-- Воронка бронирования мастер-классов: аналитические запросы на SQLite.
-- Данные: таблица events (создаётся python3 load_db.py из events.json).
-- Запуск: python3 run_sql.py — выполнит все запросы и сверит результат с дашбордом.
-- Каждый запрос помечен строкой `-- name: <имя>`, по ней его находит run_sql.py.


-- name: funnel
-- Воронка: уникальные пользователи по шагам, конверсия шага и сквозная конверсия.
WITH steps(step_no, event_name, step_label) AS (
    VALUES (1, 'catalog_view',      'Просмотр каталога'),
           (2, 'event_view',        'Карточка мастер-класса'),
           (3, 'booking_started',   'Открыл форму брони'),
           (4, 'booking_created',   'Бронь создана'),
           (5, 'payment_initiated', 'Начал оплату'),
           (6, 'payment_success',   'Оплачено')
),
step_users AS (
    SELECT s.step_no, s.step_label, COUNT(DISTINCT e.user_id) AS users
    FROM steps s
    LEFT JOIN events e ON e.event_name = s.event_name
    GROUP BY s.step_no, s.step_label
)
SELECT step_no,
       step_label,
       users,
       ROUND(100.0 * users / LAG(users)         OVER (ORDER BY step_no), 1) AS step_cr_pct,
       ROUND(100.0 * users / FIRST_VALUE(users) OVER (ORDER BY step_no), 1) AS cum_cr_pct
FROM step_users
ORDER BY step_no;


-- name: revenue
-- Выручка и средний чек по успешным оплатам.
SELECT COUNT(*)                                             AS paid_bookings,
       SUM(json_extract(properties, '$.amount_kzt'))        AS revenue_kzt,
       ROUND(AVG(json_extract(properties, '$.amount_kzt'))) AS avg_check_kzt
FROM events
WHERE event_name = 'payment_success';


-- name: channels
-- Конверсия в оплату по каналам привлечения (канал не меняется внутри пользователя).
WITH user_flags AS (
    SELECT user_id,
           MIN(channel)                                   AS channel,
           MAX(event_name = 'payment_success')            AS paid
    FROM events
    GROUP BY user_id
)
SELECT channel,
       COUNT(*)                                AS users,
       SUM(paid)                               AS paid_users,
       ROUND(100.0 * SUM(paid) / COUNT(*), 1)  AS cr_to_paid_pct
FROM user_flags
GROUP BY channel
ORDER BY cr_to_paid_pct DESC;


-- name: payment_failures
-- Сбои оплаты по кодам ошибок; доля считается от числа начатых оплат.
WITH attempts AS (
    SELECT COUNT(DISTINCT user_id) AS initiated
    FROM events
    WHERE event_name = 'payment_initiated'
)
SELECT json_extract(e.properties, '$.error_code')         AS error_code,
       COUNT(*)                                           AS failures,
       ROUND(100.0 * COUNT(*) / a.initiated, 1)           AS pct_of_initiated
FROM events e
CROSS JOIN attempts a
WHERE e.event_name = 'payment_failed'
GROUP BY error_code
UNION ALL
SELECT 'ИТОГО', COUNT(*), ROUND(100.0 * COUNT(*) / a.initiated, 1)
FROM events e
CROSS JOIN attempts a
WHERE e.event_name = 'payment_failed'
ORDER BY failures DESC;


-- name: payment_retry
-- Помогает ли повторная попытка: успешные оплаты по номеру попытки.
SELECT json_extract(properties, '$.attempt') AS attempt,
       COUNT(*)                              AS successful_payments
FROM events
WHERE event_name = 'payment_success'
GROUP BY attempt
ORDER BY attempt;


-- name: drop_reasons
-- Причины потери пользователей вне оплаты: отказ по местам, брошенная форма, истёкшая бронь.
SELECT event_name,
       json_extract(properties, '$.reason') AS reason,
       COUNT(DISTINCT user_id)              AS users
FROM events
WHERE event_name IN ('booking_rejected', 'booking_abandoned', 'booking_expired')
GROUP BY event_name, reason
ORDER BY users DESC;


-- name: cohorts
-- Недельные когорты: неделя (пн–вс) первого просмотра каталога, доля когорты по шагам.
WITH first_visit AS (
    SELECT user_id,
           -- 'weekday 0' сдвигает на ближайшее воскресенье, минус 6 дней даёт понедельник
           date(MIN(event_date), 'weekday 0', '-6 days') AS cohort_week
    FROM events
    WHERE event_name = 'catalog_view'
    GROUP BY user_id
),
reach AS (
    SELECT user_id,
           MAX(event_name = 'event_view')         AS s2,
           MAX(event_name = 'booking_started')    AS s3,
           MAX(event_name = 'booking_created')    AS s4,
           MAX(event_name = 'payment_initiated')  AS s5,
           MAX(event_name = 'payment_success')    AS s6
    FROM events
    GROUP BY user_id
)
SELECT f.cohort_week,
       COUNT(*)                                     AS users,
       ROUND(100.0 * SUM(r.s2) / COUNT(*), 1)       AS card_pct,
       ROUND(100.0 * SUM(r.s3) / COUNT(*), 1)       AS form_pct,
       ROUND(100.0 * SUM(r.s4) / COUNT(*), 1)       AS booked_pct,
       ROUND(100.0 * SUM(r.s5) / COUNT(*), 1)       AS pay_started_pct,
       ROUND(100.0 * SUM(r.s6) / COUNT(*), 1)       AS paid_pct
FROM first_visit f
JOIN reach r USING (user_id)
GROUP BY f.cohort_week
ORDER BY f.cohort_week;


-- name: ab_test
-- A/B card_price_dates: конверсия по вариантам и z-статистика разницы долей (пул. дисперсия).
-- p-value в SQLite не посчитать (нет функции нормального распределения) — его считает run_sql.py.
WITH exposed AS (
    SELECT user_id, json_extract(properties, '$.variant') AS variant
    FROM events
    WHERE event_name = 'experiment_exposed'
),
reach AS (
    SELECT user_id,
           MAX(event_name = 'booking_started') AS form,
           MAX(event_name = 'booking_created') AS booked,
           MAX(event_name = 'payment_success') AS paid
    FROM events
    GROUP BY user_id
),
per_variant AS (
    SELECT x.variant,
           COUNT(*)      AS n,
           SUM(r.form)   AS form,
           SUM(r.booked) AS booked,
           SUM(r.paid)   AS paid
    FROM exposed x
    JOIN reach r USING (user_id)
    GROUP BY x.variant
),
pair AS (
    SELECT a.n AS n_a, b.n AS n_b,
           a.form AS f_a, b.form AS f_b,
           a.booked AS k_a, b.booked AS k_b,
           a.paid AS p_a, b.paid AS p_b
    FROM per_variant a, per_variant b
    WHERE a.variant = 'A' AND b.variant = 'B'
)
SELECT 'Переход в форму' AS metric,
       ROUND(100.0 * f_a / n_a, 1) AS rate_a_pct,
       ROUND(100.0 * f_b / n_b, 1) AS rate_b_pct,
       ROUND(100.0 * (1.0 * f_b / n_b - 1.0 * f_a / n_a), 1) AS diff_pp,
       ROUND((1.0 * f_b / n_b - 1.0 * f_a / n_a) /
             sqrt((1.0 * (f_a + f_b) / (n_a + n_b)) * (1 - 1.0 * (f_a + f_b) / (n_a + n_b)) * (1.0 / n_a + 1.0 / n_b)), 4) AS z,
       n_a, n_b
FROM pair
UNION ALL
SELECT 'Бронь создана',
       ROUND(100.0 * k_a / n_a, 1), ROUND(100.0 * k_b / n_b, 1),
       ROUND(100.0 * (1.0 * k_b / n_b - 1.0 * k_a / n_a), 1),
       ROUND((1.0 * k_b / n_b - 1.0 * k_a / n_a) /
             sqrt((1.0 * (k_a + k_b) / (n_a + n_b)) * (1 - 1.0 * (k_a + k_b) / (n_a + n_b)) * (1.0 / n_a + 1.0 / n_b)), 4),
       n_a, n_b
FROM pair
UNION ALL
SELECT 'Оплачено',
       ROUND(100.0 * p_a / n_a, 1), ROUND(100.0 * p_b / n_b, 1),
       ROUND(100.0 * (1.0 * p_b / n_b - 1.0 * p_a / n_a), 1),
       ROUND((1.0 * p_b / n_b - 1.0 * p_a / n_a) /
             sqrt((1.0 * (p_a + p_b) / (n_a + n_b)) * (1 - 1.0 * (p_a + p_b) / (n_a + n_b)) * (1.0 / n_a + 1.0 / n_b)), 4),
       n_a, n_b
FROM pair;


-- name: user_status
-- Таблица по user_id: глубина воронки и статус. Приоритет статусов — как в дашборде
-- (оплата важнее ошибки, ошибка важнее ожидания и т.д.). Ниже — распределение по статусам.
WITH user_flags AS (
    SELECT user_id,
           MAX(event_name = 'event_view')         AS viewed,
           MAX(event_name = 'booking_started')    AS started,
           MAX(event_name = 'booking_created')    AS booked,
           MAX(event_name = 'payment_initiated')  AS pay_init,
           MAX(event_name = 'payment_success')    AS paid,
           MAX(event_name = 'payment_failed')     AS pay_failed,
           MAX(event_name = 'booking_expired')    AS expired,
           MAX(event_name = 'booking_rejected')   AS sold_out,
           MAX(event_name = 'booking_abandoned')  AS abandoned
    FROM events
    GROUP BY user_id
),
user_status AS (
    SELECT user_id,
           CASE WHEN paid       THEN 'paid'
                WHEN pay_failed THEN 'failed'
                WHEN expired    THEN 'expired'
                WHEN pay_init   THEN 'pending'
                WHEN booked     THEN 'reserved'
                WHEN sold_out   THEN 'sold_out'
                WHEN abandoned  THEN 'abandoned'
                WHEN started    THEN 'started'
                WHEN viewed     THEN 'viewed'
                ELSE 'catalog'
           END AS status
    FROM user_flags
)
SELECT status,
       COUNT(*)                                        AS users,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS share_pct
FROM user_status
GROUP BY status
ORDER BY users DESC;
