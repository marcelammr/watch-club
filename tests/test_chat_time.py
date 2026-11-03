from datetime import datetime

from app.chat_time import chat_clock, chat_day_key, chat_day_label


def test_chat_clock_and_day_use_sao_paulo():
    now = datetime(2026, 11, 3, 6, 0, 0)
    before_midnight_sp = datetime(2026, 11, 3, 2, 30, 0)
    assert chat_clock(before_midnight_sp) == "23:30"
    assert chat_day_key(before_midnight_sp) == "2026-11-02"
    assert chat_day_label(before_midnight_sp, now=now) == "Ontem"

    same_morning = datetime(2026, 11, 3, 12, 14, 0)
    assert chat_clock(same_morning) == "09:14"
    assert chat_day_key(same_morning) == "2026-11-03"
    assert chat_day_label(same_morning, now=now) == "Hoje"

    old = datetime(2026, 9, 15, 18, 6, 0)
    assert chat_clock(old) == "15:06"
    assert chat_day_label(old, now=now) == "15 de setembro de 2026"
    october = datetime(2026, 10, 26, 21, 0, 0)
    assert chat_day_label(october, now=now) == "26 de outubro de 2026"
