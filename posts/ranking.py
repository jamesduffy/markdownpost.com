"""Ranking for the "Helpful" sort: an exponentially time-decayed vote sum, stored as a logarithm.

The score of a post at time T is the sum over its helpful votes of 2 ** (-(T - t_i) / half_life), where t_i is when
the vote was cast. Each vote is worth 1 when cast and half as much one half-life later, so a burst of fresh votes
lifts a post and old votes fade, however many there were.

Doing that per request would mean re-scoring every post as time passes. We avoid it with a trick. Write the decay
rate as lam = ln(2) / half_life. Then

    score(T) = sum_i exp(-lam * (T - t_i)) = exp(-lam * T) * sum_i exp(lam * t_i)

The factor exp(-lam * T) is the same for every post, so ordering posts by S = sum_i exp(lam * t_i) gives exactly the
same order as ordering by the current decayed score at any later moment. We store the natural log of S (the sum would
overflow as time goes on), which is order-preserving too:

    helpful_rank = log( sum_i exp(lam * t_i) ),   t_i = days between EPOCH and the vote

Adding a vote is one numerically stable log-add-exp: new = logaddexp(old, lam * t). Removing a vote cannot be undone
that way, so it re-sums the post's remaining votes. `helpful_rank` is NULL when a post has no votes. The stored value
is a ranking key only; it is not a count and is never shown to anyone.

Changing the half-life changes lam, so every stored rank must be rebuilt (`manage.py rank_posts`).
"""

import math
from datetime import datetime, timezone

from django.conf import settings

# Any fixed moment will do, but it must never change: stored ranks are relative to it. Keeping it near the present
# keeps the exponents small.
EPOCH = datetime(2025, 1, 1, tzinfo=timezone.utc)
SECONDS_PER_DAY = 86400.0


def decay_rate():
    """lam = ln(2) / half-life, per day."""
    return math.log(2) / float(settings.HELPFUL_HALF_LIFE_DAYS)


def vote_term(when):
    """lam * t for a vote cast at `when` (t in days since EPOCH): the log of that vote's weight."""
    return decay_rate() * ((when - EPOCH).total_seconds() / SECONDS_PER_DAY)


def logaddexp(a, b):
    """log(exp(a) + exp(b)) without overflow."""
    hi, lo = (a, b) if a >= b else (b, a)
    return hi + math.log1p(math.exp(lo - hi))


def add_vote(rank, when):
    """The rank after one more vote at `when`. `rank` is the current stored value (None = no votes yet)."""
    term = vote_term(when)
    return term if rank is None else logaddexp(rank, term)


def rank_from_votes(times):
    """The rank for a post whose votes were cast at `times` (None when there are none). Same value add_vote reaches
    by adding the votes one at a time, up to floating point rounding."""
    terms = [vote_term(t) for t in times]
    if not terms:
        return None
    top = max(terms)
    return top + math.log(sum(math.exp(x - top) for x in terms))


def decayed_score(rank, now):
    """The human-meaning score (sum of decayed votes) at `now`, for tests and debugging only. Never display it."""
    if rank is None:
        return 0.0
    return math.exp(rank - vote_term(now))
