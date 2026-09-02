from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"


def _load(name: str) -> dict:
    return yaml.safe_load((TEMPLATES / name).read_text(encoding="utf-8"))


def test_issue_forms_have_current_top_level_shape_and_unique_ids() -> None:
    for name, expected_label in (
        ("first-use-feedback.yml", "feedback"),
        ("bug-report.yml", "bug"),
    ):
        form = _load(name)
        assert form["name"]
        assert form["description"]
        assert form["labels"] == [expected_label]
        assert form["body"]

        ids = [element["id"] for element in form["body"] if "id" in element]
        assert len(ids) == len(set(ids))


def test_first_use_form_collects_five_answers_and_requires_privacy_check() -> None:
    form = _load("first-use-feedback.yml")
    fields = {element.get("id"): element for element in form["body"]}

    assert [
        element.get("id")
        for element in form["body"]
        if element.get("id") not in {None, "privacy_check", "version"}
    ] == [
        "progress",
        "goal_and_result",
        "friction",
        "recommendation_clarity",
        "impact_and_improvement",
    ]
    assert fields["privacy_check"]["attributes"]["options"][0]["required"] is True
    assert all(
        fields[field_id]["validations"]["required"] is True
        for field_id in (
            "progress",
            "goal_and_result",
            "friction",
            "recommendation_clarity",
            "impact_and_improvement",
        )
    )
    assert (
        "resource recommendation" in fields["recommendation_clarity"]["attributes"]["label"].lower()
    )
    assert fields["impact_and_improvement"]["attributes"]["label"] == (
        "5. Would you use AtReady again?"
    )


def test_public_forms_warn_about_private_data_and_route_security_reports() -> None:
    feedback_text = (TEMPLATES / "first-use-feedback.yml").read_text(encoding="utf-8")
    bug_text = (TEMPLATES / "bug-report.yml").read_text(encoding="utf-8")
    config = _load("config.yml")

    for text in (feedback_text, bug_text):
        lowered = text.lower()
        for warning in (
            "real inventory",
            "credentials",
            "private notes",
            "account details",
            "proprietary plans",
        ):
            assert warning in lowered

    security_url = (
        "https://github.com/stoicpickle/atready/blob/main/SECURITY.md#reporting-a-vulnerability"
    )
    assert security_url in bug_text
    assert config == {
        "blank_issues_enabled": False,
        "contact_links": [
            {
                "name": "Report a security or privacy vulnerability",
                "url": security_url,
                "about": (
                    "Follow the private-reporting guidance in AtReady's security policy; "
                    "do not post vulnerability details publicly."
                ),
            }
        ],
    }
