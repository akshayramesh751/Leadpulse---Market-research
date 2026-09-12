"""Unit tests for the LeadPulse Statistical Evaluation Harness."""

import pytest
from agent.evaluator import (
    compute_set_metrics,
    compute_keyword_match,
    normalize_string,
    normalize_phone,
)


def test_compute_set_metrics_perfect_match():
    gt = ["admin@company.com", "sales@company.com"]
    pred = ["admin@company.com", "sales@company.com"]
    metrics = compute_set_metrics(pred, gt)
    assert metrics.tp == 2
    assert metrics.fp == 0
    assert metrics.fn == 0
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1_score == 1.0


def test_compute_set_metrics_partial_match():
    gt = ["admin@company.com", "sales@company.com"]
    pred = ["admin@company.com", "info@company.com"]
    metrics = compute_set_metrics(pred, gt)
    assert metrics.tp == 1
    assert metrics.fp == 1
    assert metrics.fn == 1
    assert metrics.precision == 0.5
    assert metrics.recall == 0.5
    assert metrics.f1_score == 0.5


def test_compute_set_metrics_empty_both():
    # When both ground truth and prediction are empty, agreement is 100%
    metrics = compute_set_metrics([], [])
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1_score == 1.0


def test_compute_set_metrics_empty_ground_truth_with_spurious_pred():
    # Model extracted items when ground truth has none -> Precision 0, Recall 1
    metrics = compute_set_metrics(["spam@tracker.com"], [])
    assert metrics.tp == 0
    assert metrics.fp == 1
    assert metrics.precision == 0.0
    assert metrics.f1_score == 0.0


def test_compute_set_metrics_empty_pred_with_nonempty_ground_truth():
    # Model failed to extract existing items -> Total miss
    metrics = compute_set_metrics([], ["founder@company.com"])
    assert metrics.tp == 0
    assert metrics.fn == 1
    assert metrics.precision == 0.0
    assert metrics.recall == 0.0
    assert metrics.f1_score == 0.0


def test_compute_set_metrics_phone_normalization():
    gt = ["+91 93807 38490"]
    pred = ["+919380738490"]
    metrics = compute_set_metrics(pred, gt, normalize_fn=normalize_phone)
    assert metrics.tp == 1
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1_score == 1.0


def test_compute_set_metrics_name_fuzzy_matching():
    gt = ["Paul Copplestone"]
    pred = ["Paul Copplestone (Co-founder & CEO)"]
    metrics = compute_set_metrics(pred, gt, normalize_fn=normalize_string)
    assert metrics.tp == 1
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1_score == 1.0


def test_compute_keyword_match():
    assert compute_keyword_match("Bengaluru, Karnataka, India", ["Karnataka", "Bangalore"]) is True
    assert compute_keyword_match("San Francisco, CA", ["San Francisco", "USA"]) is True
    assert compute_keyword_match("Berlin, Germany", ["San Francisco", "USA"]) is False
    assert compute_keyword_match(None, ["San Francisco"]) is False
