"""
src/services/context_detection.py — Message context detection for the conversation agent.

Uses a weighted keyword/pattern scoring approach to classify user messages into
one of eight context categories. Designed to be fast (no I/O) and deterministic
so it can be called synchronously before the Claude API request.
"""

import re
from dataclasses import dataclass, field


# ─────────────────────────────────────────────
# Context constants
# ─────────────────────────────────────────────

FRIENDLY_CHAT = "friendly_chat"
TRADING_QUESTION = "trading_question"
TECHNICAL_HELP = "technical_help"
MARKET_ANALYSIS = "market_analysis"
AI_PERFORMANCE = "ai_performance"
EDUCATIONAL = "educational"
EMOTIONAL_SUPPORT = "emotional_support"
GENERAL = "general"

ALL_CONTEXTS = [
    FRIENDLY_CHAT,
    TRADING_QUESTION,
    TECHNICAL_HELP,
    MARKET_ANALYSIS,
    AI_PERFORMANCE,
    EDUCATIONAL,
    EMOTIONAL_SUPPORT,
    GENERAL,
]


# ─────────────────────────────────────────────
# Signal definitions
# ─────────────────────────────────────────────

@dataclass
class ContextSignal:
    """A scored keyword/pattern that votes for a particular context."""

    pattern: str          # regex pattern (case-insensitive)
    score: int = 1        # weight — stronger signals get higher scores
    is_regex: bool = False


# Maps each context to a list of signals
_SIGNALS: dict[str, list[ContextSignal]] = {

    FRIENDLY_CHAT: [
        ContextSignal(r"awesome", 2),
        ContextSignal(r"amazing", 2),
        ContextSignal(r"great job", 3),
        ContextSignal(r"\bgreat\b", 1),
        ContextSignal(r"\blove\b", 2),
        ContextSignal(r"\bwow\b", 2),
        ContextSignal(r"🎉|🚀|🙌|🥳|💪|😍|🔥", 3, is_regex=True),
        ContextSignal(r"nice work", 2),
        ContextSignal(r"you('re| are) (the best|awesome|great)", 3, is_regex=True),
        ContextSignal(r"\bcongrat", 2),
        ContextSignal(r"\bwon\b", 1),
        ContextSignal(r"\bprofit\b", 1),
        ContextSignal(r"made money", 2),
        ContextSignal(r"hell[o]? there", 1, is_regex=True),
        ContextSignal(r"\bhey\b", 1),
    ],

    TRADING_QUESTION: [
        ContextSignal(r"should i (buy|sell|trade|invest|hold)", 4, is_regex=True),
        ContextSignal(r"should we", 3),
        ContextSignal(r"is it (a good|the right) time", 3, is_regex=True),
        ContextSignal(r"\bbuy\b", 1),
        ContextSignal(r"\bsell\b", 1),
        ContextSignal(r"\benter\b", 1),
        ContextSignal(r"\bexit\b", 1),
        ContextSignal(r"\btrade\b", 1),
        ContextSignal(r"good (entry|trade|setup)", 2, is_regex=True),
        ContextSignal(r"recommend", 2),
        ContextSignal(r"(what|which) (stock|coin|asset|pair|symbol)", 2, is_regex=True),
        ContextSignal(r"take profit", 2),
        ContextSignal(r"stop loss", 2),
        ContextSignal(r"position size", 2),
    ],

    TECHNICAL_HELP: [
        ContextSignal(r"how do i", 3),
        ContextSignal(r"how to", 2),
        ContextSignal(r"can'?t", 2),
        ContextSignal(r"\berror\b", 3),
        ContextSignal(r"\bproblem\b", 2),
        ContextSignal(r"\bissue\b", 2),
        ContextSignal(r"not working", 3),
        ContextSignal(r"doesn'?t work", 3),
        ContextSignal(r"\bbroken\b", 2),
        ContextSignal(r"\bfix\b", 2),
        ContextSignal(r"help me (with|set|configure|connect|use)", 3, is_regex=True),
        ContextSignal(r"set ?up", 2),
        ContextSignal(r"connect(ing)? (my|the|to)", 2, is_regex=True),
        ContextSignal(r"api key", 2),
    ],

    MARKET_ANALYSIS: [
        ContextSignal(r"what will", 3),
        ContextSignal(r"where (is|will|do you see)", 2, is_regex=True),
        ContextSignal(r"\bpredict\b", 3),
        ContextSignal(r"\bforecast\b", 3),
        ContextSignal(r"\btrend\b", 2),
        ContextSignal(r"\boutlook\b", 3),
        ContextSignal(r"market (analysis|conditions?|sentiment|situation)", 3, is_regex=True),
        ContextSignal(r"(bull|bear)(ish)?", 2, is_regex=True),
        ContextSignal(r"price (action|movement|target)", 2, is_regex=True),
        ContextSignal(r"(support|resistance) (level|zone)", 2, is_regex=True),
        ContextSignal(r"\brsi\b", 2),
        ContextSignal(r"\bmacd\b", 2),
        ContextSignal(r"technical analysis", 3),
        ContextSignal(r"what('s| is) (btc|eth|bitcoin|ethereum|market) (at|doing)", 2, is_regex=True),
    ],

    AI_PERFORMANCE: [
        ContextSignal(r"why did (it|you|the ai|my ai)", 4, is_regex=True),
        ContextSignal(r"why (loss|lose|lost)", 3, is_regex=True),
        ContextSignal(r"\bperformance\b", 3),
        ContextSignal(r"\bstats\b", 2),
        ContextSignal(r"\bstatistics\b", 2),
        ContextSignal(r"win rate", 3),
        ContextSignal(r"(how|what) (is|was|are) (the|my|your)? ?(result|return|roi|profit|loss)", 3, is_regex=True),
        ContextSignal(r"how (is|was|did) (it|my ai|the ai) (doing|perform)", 3, is_regex=True),
        ContextSignal(r"last (trade|week|month)", 2, is_regex=True),
        ContextSignal(r"total (profit|loss|return)", 3, is_regex=True),
        ContextSignal(r"(good|bad|poor) (trade|result|decision)", 2, is_regex=True),
    ],

    EDUCATIONAL: [
        ContextSignal(r"how does", 3),
        ContextSignal(r"what is\b", 3),
        ContextSignal(r"what are\b", 2),
        ContextSignal(r"\bexplain\b", 3),
        ContextSignal(r"\bteach\b", 3),
        ContextSignal(r"\blearn\b", 2),
        ContextSignal(r"can you (explain|tell me|describe|show me)", 3, is_regex=True),
        ContextSignal(r"i (don'?t|do not) understand", 3, is_regex=True),
        ContextSignal(r"what does .{1,20} mean", 2, is_regex=True),
        ContextSignal(r"\bdefinition\b", 2),
        ContextSignal(r"difference between", 2),
        ContextSignal(r"(beginner|newbie|new to)", 2, is_regex=True),
        ContextSignal(r"guide me", 2),
    ],

    EMOTIONAL_SUPPORT: [
        ContextSignal(r"\bworried\b", 3),
        ContextSignal(r"\bfrustrated\b", 3),
        ContextSignal(r"\banxious\b", 3),
        ContextSignal(r"\bscared\b", 3),
        ContextSignal(r"\bstressed\b", 3),
        ContextSignal(r"\bconcerned\b", 2),
        ContextSignal(r"\bupset\b", 2),
        ContextSignal(r"\bdisappointed\b", 2),
        ContextSignal(r"\bnervous\b", 2),
        ContextSignal(r"😞|😢|😭|😟|😔|😰|🙁", 3, is_regex=True),
        ContextSignal(r"(lost|losing) (a lot|everything|too much|so much)", 3, is_regex=True),
        ContextSignal(r"should i (quit|stop|give up)", 3, is_regex=True),
        ContextSignal(r"(really|very|so) (bad|tough|hard|difficult)", 2, is_regex=True),
        ContextSignal(r"not (working out|going well|sure anymore)", 2, is_regex=True),
    ],
}


# ─────────────────────────────────────────────
# Detection engine
# ─────────────────────────────────────────────

def detect_context(user_message: str) -> str:
    """Classify a user message into one of the eight context categories.

    Uses weighted keyword/pattern matching.  The context with the highest
    cumulative score wins.  Falls back to GENERAL if no signals fire.

    Args:
        user_message: The raw message string from the user.

    Returns:
        One of the ALL_CONTEXTS string constants.
    """
    text = user_message.lower().strip()
    scores: dict[str, int] = {ctx: 0 for ctx in ALL_CONTEXTS}

    for context, signals in _SIGNALS.items():
        for signal in signals:
            try:
                if re.search(signal.pattern, text, re.IGNORECASE | re.UNICODE):
                    scores[context] += signal.score
            except re.error:
                # Malformed pattern — skip silently
                continue

    best_context = max(scores, key=lambda c: scores[c])
    best_score = scores[best_context]

    # If nothing matched meaningfully, return GENERAL
    if best_score == 0:
        return GENERAL

    return best_context


def detect_context_with_scores(user_message: str) -> dict[str, int]:
    """Return raw scores for all contexts — useful for debugging and tests.

    Args:
        user_message: The raw message string from the user.

    Returns:
        Dict mapping each context name to its total score.
    """
    text = user_message.lower().strip()
    scores: dict[str, int] = {ctx: 0 for ctx in ALL_CONTEXTS}

    for context, signals in _SIGNALS.items():
        for signal in signals:
            try:
                if re.search(signal.pattern, text, re.IGNORECASE | re.UNICODE):
                    scores[context] += signal.score
            except re.error:
                continue

    return scores


def get_context_label(context: str) -> str:
    """Return a human-readable label for a context constant."""
    labels = {
        FRIENDLY_CHAT: "Friendly Chat",
        TRADING_QUESTION: "Trading Question",
        TECHNICAL_HELP: "Technical Help",
        MARKET_ANALYSIS: "Market Analysis",
        AI_PERFORMANCE: "AI Performance Review",
        EDUCATIONAL: "Educational",
        EMOTIONAL_SUPPORT: "Emotional Support",
        GENERAL: "General",
    }
    return labels.get(context, context)
