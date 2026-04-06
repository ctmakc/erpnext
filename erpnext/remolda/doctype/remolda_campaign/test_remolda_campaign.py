import json

from erpnext.remolda.doctype.remolda_campaign.remolda_campaign import (
	ProspectCandidate,
	build_queries,
	build_social_outreach_body,
	classify_response,
	fallback_outreach,
	get_mailhog_api_url,
	infer_company_name_from_profile_url,
	infer_contact_gap_status,
	parse_seed_line,
	resolve_duckduckgo_url,
)


def test_build_queries():
	queries = build_queries("HVAC contractor\nair conditioning repair", "Ottawa", "Ontario", "Canada")
	assert queries == [
		"HVAC contractor Ottawa Ontario Canada",
		"air conditioning repair Ottawa Ontario Canada",
	]


def test_resolve_duckduckgo_url():
	href = "/l/?uddg=https%3A%2F%2Fexample.com%2Fcontact"
	assert resolve_duckduckgo_url(href) == "https://example.com/contact"


def test_fallback_outreach_contains_offer():
	candidate = ProspectCandidate(
		company_name="North Wind HVAC",
		website="https://northwind.example",
		source_url="https://northwind.example",
		source_query="HVAC contractor Ottawa Ontario Canada",
		location="Ottawa",
	)

	class Campaign:
		target_city = "Ottawa"
		service_offer = "HVAC AI Workflow Audit"

	data = fallback_outreach(candidate, Campaign())
	assert "North Wind HVAC" in data["subject"]
	assert "HVAC AI Workflow Audit" in data["body"]


def test_classify_response_marks_acceptance_as_won():
	class Campaign:
		classify_responses = 0

	classification, summary = classify_response(
		Campaign(), "Looks good. Approved on our side. Please proceed with kickoff and next steps."
	)
	assert classification == "Won"
	assert "Approved on our side" in summary


def test_get_mailhog_api_url_for_local_sink():
	class Account:
		smtp_server = "erpnext-mailhog"
		smtp_port = "1025"

	assert get_mailhog_api_url(Account()) == "http://erpnext-mailhog:8025"


def test_parse_seed_line_for_linkedin_url():
	class Campaign:
		target_city = "Ottawa"

	candidate = parse_seed_line("https://www.linkedin.com/company/example-hvac", Campaign())
	assert candidate is not None
	assert candidate.source_channel == "LinkedIn"
	assert "linkedin.com" in candidate.source_profile_url
	assert candidate.company_name == "Example Hvac"
	assert candidate.website == ""


def test_parse_seed_line_for_pipe_format():
	class Campaign:
		target_city = "Ottawa"

	candidate = parse_seed_line(
		"Example HVAC|https://examplehvac.com|owner@examplehvac.com|613-555-1111|LinkedIn", Campaign()
	)
	assert candidate is not None
	assert candidate.company_name == "Example HVAC"
	assert candidate.email == "owner@examplehvac.com"
	assert candidate.source_channel == "LinkedIn"
	assert candidate.website == "https://examplehvac.com"


def test_infer_company_name_from_social_profile_url():
	assert (
		infer_company_name_from_profile_url("https://www.facebook.com/coolairhvac/")
		== "Coolairhvac"
	)


def test_social_seed_gap_status_prefers_decision_maker():
	candidate = ProspectCandidate(
		company_name="Nordik HVAC",
		website="",
		source_url="https://www.linkedin.com/company/nordik-hvac",
		source_query="seed:LinkedIn",
		source_channel="LinkedIn",
		source_profile_url="https://www.linkedin.com/company/nordik-hvac",
	)
	assert infer_contact_gap_status(candidate) == "Needs Decision Maker"


def test_build_social_outreach_body_mentions_profile():
	class Campaign:
		target_city = "Ottawa"

	class Row:
		company_name = "Nordik Hvac"
		source_channel = "LinkedIn"
		source_profile_url = "https://www.linkedin.com/company/nordik-hvac"
		source_url = "https://www.linkedin.com/company/nordik-hvac"
		location = "Ottawa"
		pain_hypothesis = "dispatching and quoting bottlenecks"

	body = build_social_outreach_body(Campaign(), Row())
	assert "LinkedIn" in body
	assert "https://www.linkedin.com/company/nordik-hvac" in body
	assert "dispatching and quoting bottlenecks" in body
