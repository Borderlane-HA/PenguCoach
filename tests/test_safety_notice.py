from pengucoach.safety.notice import NOTICE, NOTICE_VERSION


def test_notice_is_bilingual_and_versioned():
    assert NOTICE_VERSION.startswith("health-notice-")
    assert "de-DE" in NOTICE and "en-US" in NOTICE
    assert len(NOTICE["de-DE"]["paragraphs"]) >= 5
    assert len(NOTICE["en-US"]["paragraphs"]) >= 5
