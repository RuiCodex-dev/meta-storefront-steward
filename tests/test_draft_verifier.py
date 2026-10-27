from steward.draft import guess_language, verify


def _d(text, **kw):
    return {"reply_text": text, "language": "en", "cites": kw.get("cites", []), "promises": kw.get("promises", [])}


def test_clean_reply_passes():
    assert verify(_d("Thanks for the feedback, we are looking at the ad pacing."), store="play", review_lang="en",
                  known_ids=set()) == []


def test_each_rule_fires():
    assert any("too long" in p for p in verify(_d("x" * 351), store="play", review_lang=None, known_ids=set()))
    assert any("promises" in p for p in verify(_d("We will refund you tomorrow"), store="play", review_lang="en",
                                               known_ids=set()))
    assert any("promises" in p for p in verify(_d("Please give the latest version a try!"), store="play",
                                               review_lang="en", known_ids=set()))
    assert any("placeholder" in p for p in verify(_d("Thanks [NAME], we are on it"), store="play", review_lang="en",
                                                  known_ids=set()))
    assert any("personal data" in p for p in verify(_d("Mail us at help@example.com"), store="play",
                                                    review_lang="en", known_ids=set()))
    assert any("cites unknown" in p for p in verify(_d("Thanks!", cites=["R-x"]), store="play", review_lang="en",
                                                    known_ids={"R-y"}))
    assert any("language mismatch" in p for p in verify(_d("Vielen Dank für dein Feedback, wir schauen uns das an"),
                                                        store="play", review_lang="en", known_ids=set()))


def test_language_guess():
    assert guess_language("Merci pour votre retour, nous regardons le problème") == "fr"
    assert guess_language("Спасибо за отзыв") == "ru"
