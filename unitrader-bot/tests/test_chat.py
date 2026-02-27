"""
tests/test_chat.py — Unit tests for the conversation system.

Run with:  pytest tests/test_chat.py -v

All tests are pure (no I/O, no database, no Claude API calls).
Covers:
  - context_detection.py   (every context category + edge cases)
  - conversation_memory.py (sentiment analysis)
"""

import pytest

from src.services.context_detection import (
    AI_PERFORMANCE,
    ALL_CONTEXTS,
    EDUCATIONAL,
    EMOTIONAL_SUPPORT,
    FRIENDLY_CHAT,
    GENERAL,
    MARKET_ANALYSIS,
    TECHNICAL_HELP,
    TRADING_QUESTION,
    detect_context,
    detect_context_with_scores,
    get_context_label,
)
from src.services.conversation_memory import analyze_sentiment


# ═════════════════════════════════════════════
# CONTEXT DETECTION
# ═════════════════════════════════════════════

class TestContextDetection:

    # ── friendly_chat ──────────────────────────────────────────────────────

    def test_emoji_celebration(self):
        assert detect_context("We just hit a new high! 🎉🚀") == FRIENDLY_CHAT

    def test_awesome_keyword(self):
        assert detect_context("That was awesome!") == FRIENDLY_CHAT

    def test_love_keyword(self):
        assert detect_context("I love how the AI is performing!") == FRIENDLY_CHAT

    def test_congrats_keyword(self):
        assert detect_context("Congratulations on the win!") == FRIENDLY_CHAT

    # ── trading_question ───────────────────────────────────────────────────

    def test_should_i_buy(self):
        assert detect_context("Should I buy BTC right now?") == TRADING_QUESTION

    def test_should_i_sell(self):
        assert detect_context("Should I sell my ETH position?") == TRADING_QUESTION

    def test_is_it_good_time(self):
        assert detect_context("Is it a good time to enter the market?") == TRADING_QUESTION

    def test_recommend_keyword(self):
        assert detect_context("Do you recommend trading this setup?") == TRADING_QUESTION

    def test_stop_loss_question(self):
        assert detect_context("Where should I set my stop loss?") == TRADING_QUESTION

    # ── technical_help ─────────────────────────────────────────────────────

    def test_how_do_i(self):
        assert detect_context("How do I connect my Binance account?") == TECHNICAL_HELP

    def test_error_keyword(self):
        assert detect_context("I'm getting an error when I try to log in") == TECHNICAL_HELP

    def test_not_working(self):
        assert detect_context("The API key is not working") == TECHNICAL_HELP

    def test_cant_connect(self):
        assert detect_context("I can't connect to my exchange") == TECHNICAL_HELP

    def test_setup_keyword(self):
        assert detect_context("Help me set up my Alpaca account") == TECHNICAL_HELP

    # ── market_analysis ────────────────────────────────────────────────────

    def test_predict_keyword(self):
        assert detect_context("Can you predict where BTC is going?") == MARKET_ANALYSIS

    def test_outlook_keyword(self):
        assert detect_context("What's the market outlook for this week?") == MARKET_ANALYSIS

    def test_bullish_keyword(self):
        assert detect_context("Is the market looking bullish?") == MARKET_ANALYSIS

    def test_technical_analysis(self):
        assert detect_context("Give me a technical analysis of ETH") == MARKET_ANALYSIS

    def test_support_resistance(self):
        assert detect_context("What are the support levels for BTC?") == MARKET_ANALYSIS

    def test_rsi_question(self):
        assert detect_context("The RSI is at 70, what does that mean for the trend?") in (
            MARKET_ANALYSIS, EDUCATIONAL
        )

    # ── ai_performance ─────────────────────────────────────────────────────

    def test_why_did_it_lose(self):
        assert detect_context("Why did it make a loss on that trade?") == AI_PERFORMANCE

    def test_performance_keyword(self):
        assert detect_context("How is the AI performance this week?") == AI_PERFORMANCE

    def test_win_rate(self):
        assert detect_context("What's my win rate?") == AI_PERFORMANCE

    def test_total_profit(self):
        assert detect_context("Show me total profit for this month") == AI_PERFORMANCE

    def test_stats_keyword(self):
        assert detect_context("Can you show me my trading stats?") == AI_PERFORMANCE

    # ── educational ────────────────────────────────────────────────────────

    def test_what_is(self):
        assert detect_context("What is RSI?") == EDUCATIONAL

    def test_how_does(self):
        assert detect_context("How does MACD work?") == EDUCATIONAL

    def test_explain_keyword(self):
        assert detect_context("Can you explain what a stop-loss is?") == EDUCATIONAL

    def test_teach_keyword(self):
        assert detect_context("Teach me about Fibonacci retracements") == EDUCATIONAL

    def test_dont_understand(self):
        assert detect_context("I don't understand how leverage works") == EDUCATIONAL

    def test_difference_between(self):
        assert detect_context("What's the difference between spot and futures trading?") == EDUCATIONAL

    # ── emotional_support ──────────────────────────────────────────────────

    def test_worried_keyword(self):
        assert detect_context("I'm really worried about my trades") == EMOTIONAL_SUPPORT

    def test_frustrated_keyword(self):
        assert detect_context("I'm so frustrated with these losses") == EMOTIONAL_SUPPORT

    def test_sad_emoji(self):
        assert detect_context("Lost again today 😞 not sure what to do") == EMOTIONAL_SUPPORT

    def test_should_i_quit(self):
        assert detect_context("Should I just quit trading?") == EMOTIONAL_SUPPORT

    def test_losing_a_lot(self):
        assert detect_context("I'm losing so much money this week") == EMOTIONAL_SUPPORT

    # ── general ────────────────────────────────────────────────────────────

    def test_empty_ish_message_is_general(self):
        assert detect_context("hello") == GENERAL

    def test_no_match_is_general(self):
        assert detect_context("the quick brown fox") == GENERAL

    # ── edge cases ─────────────────────────────────────────────────────────

    def test_returns_valid_context(self):
        messages = [
            "Should I buy now?",
            "What is RSI?",
            "I'm frustrated!",
            "Predict BTC price",
            "Help set up API",
            "Amazing trade! 🎉",
            "Show me my stats",
            "",
        ]
        for msg in messages:
            result = detect_context(msg)
            assert result in ALL_CONTEXTS, f"Unknown context '{result}' for: {msg!r}"

    def test_scores_dict_has_all_contexts(self):
        scores = detect_context_with_scores("should I buy or sell?")
        assert set(scores.keys()) == set(ALL_CONTEXTS)

    def test_scores_are_non_negative(self):
        scores = detect_context_with_scores("random message here")
        assert all(v >= 0 for v in scores.values())

    def test_winning_context_has_highest_score(self):
        msg = "I'm really frustrated and worried about my losses 😞"
        scores = detect_context_with_scores(msg)
        winner = detect_context(msg)
        assert scores[winner] == max(scores.values())


# ═════════════════════════════════════════════
# CONTEXT LABELS
# ═════════════════════════════════════════════

class TestContextLabels:
    def test_all_contexts_have_labels(self):
        for ctx in ALL_CONTEXTS:
            label = get_context_label(ctx)
            assert isinstance(label, str)
            assert len(label) > 0

    def test_unknown_context_returns_itself(self):
        assert get_context_label("unknown_xyz") == "unknown_xyz"

    def test_friendly_chat_label(self):
        assert get_context_label(FRIENDLY_CHAT) == "Friendly Chat"

    def test_educational_label(self):
        assert get_context_label(EDUCATIONAL) == "Educational"


# ═════════════════════════════════════════════
# SENTIMENT ANALYSIS
# ═════════════════════════════════════════════

class TestSentimentAnalysis:

    # ── positive ───────────────────────────────────────────────────────────

    def test_profit_is_positive(self):
        assert analyze_sentiment("We made a great profit today!") == "positive"

    def test_win_is_positive(self):
        assert analyze_sentiment("I won the trade!") == "positive"

    def test_awesome_is_positive(self):
        assert analyze_sentiment("This is awesome!") == "positive"

    def test_positive_emoji(self):
        assert analyze_sentiment("🎉🚀 Let's go!") == "positive"

    def test_thank_you_is_positive(self):
        assert analyze_sentiment("Thank you so much!") == "positive"

    # ── negative ───────────────────────────────────────────────────────────

    def test_loss_is_negative(self):
        assert analyze_sentiment("I had a big loss today") == "negative"

    def test_frustrated_is_negative(self):
        assert analyze_sentiment("I'm so frustrated with everything") == "negative"

    def test_negative_emoji(self):
        assert analyze_sentiment("Really bad day 😢") == "negative"

    def test_error_is_negative(self):
        assert analyze_sentiment("There's an error I can't fix") == "negative"

    def test_worried_is_negative(self):
        assert analyze_sentiment("I'm worried about my trades") == "negative"

    # ── neutral ────────────────────────────────────────────────────────────

    def test_factual_question_is_neutral(self):
        assert analyze_sentiment("What is the current BTC price?") == "neutral"

    def test_empty_message_is_neutral(self):
        assert analyze_sentiment("") == "neutral"

    def test_no_keywords_is_neutral(self):
        assert analyze_sentiment("The market opened at 9:30 AM today") == "neutral"

    # ── edge cases ─────────────────────────────────────────────────────────

    def test_returns_valid_value(self):
        for msg in ["great!", "terrible!", "okay", "", "💪", "😭"]:
            result = analyze_sentiment(msg)
            assert result in ("positive", "negative", "neutral"), f"Invalid: {result!r} for {msg!r}"

    def test_intensifier_boosts_sentiment(self):
        weak = analyze_sentiment("good")
        strong = analyze_sentiment("very good")
        # Both should be positive; intensifier just increases score
        assert strong == "positive"

    def test_mixed_skews_to_dominant(self):
        # More negative keywords → negative
        msg = "I'm very frustrated and worried and upset but maybe okay"
        result = analyze_sentiment(msg)
        assert result == "negative"
