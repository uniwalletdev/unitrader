"""
tests/test_content.py — Unit tests for the content generation system.

Run with:  pytest tests/test_content.py -v

All tests are pure (no I/O, no database, no Claude API calls).
Covers:
  - content_writer.py  (slug generation, read time, word count)
  - social_media.py    (type distribution, schedule slots, char limits)
"""

import pytest
from datetime import datetime, timezone, timedelta

from src.agents.marketing.content_writer import (
    SUGGESTED_TOPICS,
    count_words,
    estimate_read_time,
    make_slug,
    _placeholder_post,
)
from src.agents.marketing.social_media import (
    CHAR_LIMITS,
    PLATFORMS,
    _build_schedule_slots,
    _get_type_distribution,
    _next_morning,
    _placeholder_posts,
)


# ═════════════════════════════════════════════
# SLUG GENERATION
# ═════════════════════════════════════════════

class TestMakeSlug:
    def test_basic_title(self):
        assert make_slug("How MACD Works") == "how-macd-works"

    def test_punctuation_removed(self):
        assert make_slug("Stop-Loss: The #1 Tool!") == "stop-loss-the-1-tool"

    def test_multiple_spaces_collapsed(self):
        assert make_slug("Hello   World") == "hello-world"

    def test_already_lowercase(self):
        assert make_slug("already lowercase") == "already-lowercase"

    def test_numbers_preserved(self):
        assert make_slug("78% Win Rate Proof") == "78-win-rate-proof"

    def test_long_title_truncated(self):
        long_title = "A " * 150  # 300 chars
        result = make_slug(long_title)
        assert len(result) <= 200

    def test_leading_trailing_hyphens_stripped(self):
        result = make_slug("  Leading and trailing  ")
        assert not result.startswith("-")
        assert not result.endswith("-")

    def test_empty_string(self):
        result = make_slug("")
        assert result == ""

    def test_unicode_chars_handled(self):
        # Non-word non-hyphen chars are removed
        result = make_slug("Café Trading")
        assert isinstance(result, str)


# ═════════════════════════════════════════════
# READ TIME ESTIMATION
# ═════════════════════════════════════════════

class TestEstimateReadTime:
    def test_1000_words_is_about_4_minutes(self):
        text = "word " * 1000
        result = estimate_read_time(text, wpm=225)
        assert result == 4

    def test_minimum_is_1_minute(self):
        assert estimate_read_time("short", wpm=225) == 1

    def test_empty_string_is_1_minute(self):
        assert estimate_read_time("", wpm=225) == 1

    def test_2000_words(self):
        text = "word " * 2000
        result = estimate_read_time(text, wpm=200)
        assert result == 10

    def test_custom_wpm(self):
        text = "word " * 300
        fast = estimate_read_time(text, wpm=300)
        slow = estimate_read_time(text, wpm=150)
        assert slow >= fast


# ═════════════════════════════════════════════
# WORD COUNT
# ═════════════════════════════════════════════

class TestCountWords:
    def test_basic_sentence(self):
        assert count_words("Hello world how are you") == 5

    def test_empty_string(self):
        assert count_words("") == 0

    def test_single_word(self):
        assert count_words("trading") == 1

    def test_extra_whitespace(self):
        assert count_words("  too   many   spaces  ") == 3


# ═════════════════════════════════════════════
# PLACEHOLDER POST
# ═════════════════════════════════════════════

class TestPlaceholderPost:
    def test_returns_dict_with_required_keys(self):
        post = _placeholder_post("Test Topic")
        for key in ("title", "slug", "topic", "content", "seo_keywords",
                    "estimated_read_time", "word_count"):
            assert key in post

    def test_topic_preserved(self):
        post = _placeholder_post("My Topic")
        assert post["topic"] == "My Topic"

    def test_slug_is_url_safe(self):
        post = _placeholder_post("A Great Topic!")
        assert " " not in post["slug"]
        assert "!" not in post["slug"]

    def test_has_error_field(self):
        post = _placeholder_post("Any")
        assert "error" in post

    def test_unique_slugs(self):
        a = _placeholder_post("Same Topic")
        b = _placeholder_post("Same Topic")
        assert a["slug"] != b["slug"]


# ═════════════════════════════════════════════
# SUGGESTED TOPICS LIST
# ═════════════════════════════════════════════

class TestSuggestedTopics:
    def test_not_empty(self):
        assert len(SUGGESTED_TOPICS) > 0

    def test_all_strings(self):
        assert all(isinstance(t, str) for t in SUGGESTED_TOPICS)

    def test_all_non_empty(self):
        assert all(len(t) > 0 for t in SUGGESTED_TOPICS)

    def test_no_duplicates(self):
        assert len(SUGGESTED_TOPICS) == len(set(SUGGESTED_TOPICS))


# ═════════════════════════════════════════════
# POST TYPE DISTRIBUTION
# ═════════════════════════════════════════════

class TestTypeDistribution:
    def test_5_posts_all_types_covered(self):
        dist = _get_type_distribution(5)
        assert len(dist) == 5
        assert "educational" in dist
        assert "social_proof" in dist
        assert "call_to_action" in dist
        assert "inspirational" in dist

    def test_1_post_is_educational(self):
        dist = _get_type_distribution(1)
        assert dist == ["educational"]

    def test_extra_posts_are_educational(self):
        dist = _get_type_distribution(8)
        # First 4 are the standard types; remainder should be educational
        assert dist[4] == "educational"
        assert dist[7] == "educational"

    def test_returns_correct_length(self):
        for n in [1, 3, 5, 10]:
            assert len(_get_type_distribution(n)) == n

    def test_all_values_are_valid_types(self):
        valid = {"educational", "social_proof", "call_to_action", "inspirational"}
        for n in [1, 5, 10]:
            for t in _get_type_distribution(n):
                assert t in valid


# ═════════════════════════════════════════════
# SCHEDULE SLOTS
# ═════════════════════════════════════════════

class TestBuildScheduleSlots:
    def test_correct_count(self):
        start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        slots = _build_schedule_slots(5, start)
        assert len(slots) == 5

    def test_one_day_apart(self):
        start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        slots = _build_schedule_slots(3, start)
        assert slots[1] - slots[0] == timedelta(days=1)
        assert slots[2] - slots[1] == timedelta(days=1)

    def test_first_slot_is_start(self):
        start = datetime(2026, 3, 15, 9, 0, tzinfo=timezone.utc)
        slots = _build_schedule_slots(1, start)
        assert slots[0] == start

    def test_empty_count_returns_empty(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert _build_schedule_slots(0, start) == []


# ═════════════════════════════════════════════
# NEXT MORNING
# ═════════════════════════════════════════════

class TestNextMorning:
    def test_returns_datetime(self):
        result = _next_morning()
        assert isinstance(result, datetime)

    def test_hour_is_9(self):
        result = _next_morning()
        assert result.hour == 9

    def test_is_in_the_future(self):
        result = _next_morning()
        assert result > datetime.now(timezone.utc)

    def test_has_timezone(self):
        result = _next_morning()
        assert result.tzinfo is not None


# ═════════════════════════════════════════════
# CHAR LIMITS
# ═════════════════════════════════════════════

class TestCharLimits:
    def test_twitter_limit(self):
        assert CHAR_LIMITS["twitter"] == 280

    def test_all_platforms_have_limits(self):
        for platform in PLATFORMS:
            assert platform in CHAR_LIMITS
            assert CHAR_LIMITS[platform] > 0

    def test_twitter_shortest(self):
        assert CHAR_LIMITS["twitter"] == min(CHAR_LIMITS.values())


# ═════════════════════════════════════════════
# PLACEHOLDER SOCIAL POSTS
# ═════════════════════════════════════════════

class TestPlaceholderPosts:
    def test_correct_count(self):
        posts = _placeholder_posts("Test", 5)
        assert len(posts) == 5

    def test_all_have_required_keys(self):
        posts = _placeholder_posts("Test", 3)
        for post in posts:
            for key in ("platform", "post_type", "content", "hashtags",
                        "estimated_engagement", "topic", "scheduled_for"):
                assert key in post

    def test_platforms_rotate(self):
        posts = _placeholder_posts("Test", len(PLATFORMS))
        used_platforms = {p["platform"] for p in posts}
        assert used_platforms == set(PLATFORMS)

    def test_all_have_error_field(self):
        posts = _placeholder_posts("Test", 2)
        assert all("error" in p for p in posts)

    def test_topic_preserved(self):
        posts = _placeholder_posts("My Topic", 3)
        assert all(p["topic"] == "My Topic" for p in posts)

    def test_scheduled_for_is_future(self):
        now = datetime.now(timezone.utc)
        posts = _placeholder_posts("Test", 3)
        for post in posts:
            scheduled = datetime.fromisoformat(post["scheduled_for"])
            assert scheduled > now
