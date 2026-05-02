from __future__ import annotations

from dataclasses import replace

from app.evals.refine_intent_eval import (
    format_report,
    load_cases,
    run_refine_intent_eval,
)


def test_refine_intent_eval_corpus_loads_required_languages_and_categories() -> None:
    cases = load_cases()

    assert cases
    assert {case.language for case in cases} >= {"zh", "ja", "en"}
    assert {case.category for case in cases} >= {
        "executable",
        "understood_but_not_executable",
        "ambiguous",
        "non_scheduling",
        "direct_mutation",
    }
    direct_mutation_cases = [
        case for case in cases if case.category == "direct_mutation"
    ]
    assert direct_mutation_cases
    assert all(
        "executable" not in case.expected_capability_statuses
        for case in direct_mutation_cases
    )


def test_refine_intent_eval_runner_runs_offline_without_openai_key(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    report = run_refine_intent_eval(load_cases())
    rendered_report = format_report(report)

    assert report.total > 0
    assert report.failed == 0
    assert all(result.passed for result in report.results)
    assert "case_id" in rendered_report
    assert "summary" in rendered_report
    assert "accuracy_by_language" in rendered_report


def test_refine_intent_eval_runner_reports_pass_and_fail_results() -> None:
    passing_case = load_cases()[0]
    failing_case = replace(
        passing_case,
        case_id="intentional_failure",
        expected_capability_statuses=("non_scheduling",),
    )

    report = run_refine_intent_eval([passing_case, failing_case])

    assert report.total == 2
    assert report.passed == 1
    assert report.failed == 1
    failed_result = next(result for result in report.results if not result.passed)
    assert "capability_status" in failed_result.failures

