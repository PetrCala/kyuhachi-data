"""Tests for onsen_scraper.fees — the adult-fee parser shared by the
cost-analysis skill and the catalog publisher. Strings are verbatim from the
snapshot, including the three ids the heuristic gets wrong (151/192/239)."""
from onsen_scraper.fees import CORRECTIONS, adult_fee, fee_for


def test_explicit_adult_takes_weekday_base():
    # weekend 450 is parenthesised after the weekday base — take the base.
    assert adult_fee("大人 350円（土日祝450円）\n中人(6～11才) 200円") == (350, "adult")


def test_adult_skips_age_qualifier_before_price():
    # 13歳 is an age, not yen — the parser must reach 1,020円.
    assert adult_fee("大人（13歳以上）1,020円、こども（7～12歳）400円") == (1020, "adult")


def test_adult_with_time_prefix():
    assert adult_fee("60分大人1,000円\nこども（3～12才）500円") == (1000, "adult")


def test_fullwidth_digits_and_spaces_fold():
    assert adult_fee("大　人　５００円") == (500, "adult")


def test_hiragana_otona():
    assert adult_fee("おとな 500円\n小学生 250円") == (500, "adult")


def test_junior_high_equivalent_when_no_adult_marker():
    assert adult_fee("中学生以上 800円\n小学生450円") == (800, "jhs+")


def test_free_with_no_yen_figure():
    assert adult_fee("喫茶を利用した方のみ無料で利用可能") == (0, "free")


def test_fallback_single_price():
    assert adult_fee("700円\n貸し浴衣220円") == (700, "fallback")


def test_fallback_age_gated():
    # no 大人/中学生 marker; first yen figure is the entry price.
    assert adult_fee("(6才以上) 200円\n家族風呂 1,000円(60分)") == (200, "fallback")


def test_no_figure_at_all():
    assert adult_fee("") == (None, "none")
    assert adult_fee(None) == (None, "none")


def test_corrections_cover_the_three_known_misfires():
    assert set(CORRECTIONS) == {151, 192, 239}
    # 151: heuristic would grab the senior 500; corrected adult is 700.
    assert fee_for(151, "70才以上 500円\n13才以上 700円\n4才～小学生 350円") == (700, "corrected")
    # 192: private-bath-only; corrected to the solo 一人湯 rate.
    assert fee_for(192, "1室60分、2,400円～4,000円\n一人湯 ￥1,200") == (1200, "corrected")
    # 239: heuristic would grab a 貸切 1,200; corrected walk-in is 600.
    assert fee_for(239, "中学生以上600円 小学生400円\n貸切風呂（50分）大人1名1,200円") == (600, "corrected")


def test_fee_for_passes_through_when_not_corrected():
    assert fee_for(1, "大人 350円（土日祝450円）") == (350, "adult")
