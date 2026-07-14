from penpine.cli.paths import slugify


def test_slugify_normalizes_names():
    assert slugify("My Engagement") == "my_engagement"
    assert slugify("a-b.c") == "a_b_c"
    assert slugify("123app") == "p_123app"
    assert slugify("  ok  ") == "ok"
    assert slugify("--!!--") == "p_"  # empty core -> prefixed
