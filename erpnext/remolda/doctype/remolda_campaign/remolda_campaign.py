# Copyright (c) 2026, contributors

from __future__ import annotations

import html
import json
import quopri
import re
import smtplib
import time
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import requests

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, now_datetime, strip_html

SEARCH_HEADERS = {
	"User-Agent": (
		"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
		"(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
	)
}
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}")
TAG_RE = re.compile(r"<[^>]+>")
DDG_RESULT_RE = re.compile(
	r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
	re.I | re.S,
)


@dataclass
class ProspectCandidate:
	company_name: str
	website: str
	source_url: str
	source_query: str
	source_channel: str = "Web Search"
	source_profile_url: str = ""
	location: str = ""
	email: str = ""
	phone: str = ""
	summary: str = ""
	personalization_notes: str = ""
	pain_hypothesis: str = ""
	outreach_subject: str = ""
	outreach_body: str = ""
	icp_score: int = 0
	priority_tier: str = "C"
	service_fit: str = ""
	contact_gap_status: str = "Needs Research"
	status: str = "Discovered"
	last_error: str = ""


class RemoldaCampaign(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from erpnext.remolda.doctype.remolda_campaign_prospect.remolda_campaign_prospect import (
			RemoldaCampaignProspect,
		)
		from frappe.types import DF

		auto_create_deals: DF.Check
		auto_create_leads: DF.Check
		auto_run: DF.Check
		auto_send_outreach: DF.Check
		auto_send_proposals: DF.Check
		campaign_name: DF.Data
		classify_responses: DF.Check
		company: DF.Link | None
		dry_run: DF.Check
		enable_follow_ups: DF.Check
		follow_up_delay_days: DF.Int | None
		generated_count: DF.Int
		last_automation_on: DF.Datetime | None
		last_run_on: DF.Datetime | None
		max_results: DF.Int
		max_follow_ups: DF.Int | None
		ollama_base_url: DF.Data | None
		ollama_model: DF.Data | None
		prospects: DF.Table[RemoldaCampaignProspect]
		run_frequency_hours: DF.Int | None
		run_log: DF.LongText | None
		search_terms: DF.LongText
		seed_prospects: DF.LongText | None
		sender_email: DF.Data | None
		service_offer: DF.Link
		status: DF.Literal["Draft", "Running", "Completed", "Failed"]
		target_city: DF.Data
		target_country: DF.Data | None
		target_region: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self.max_results = max(int(self.max_results or 5), 1)
		self.follow_up_delay_days = max(int(self.follow_up_delay_days or 3), 1)
		self.max_follow_ups = max(int(self.max_follow_ups or 2), 0)
		if not self.company:
			self.company = frappe.db.get_value("Company", {}, "name")
		if not self.campaign_name:
			self.campaign_name = f"{self.target_city} HVAC Autonomous Outreach"
		if self.auto_run and not self.run_frequency_hours:
			self.run_frequency_hours = 24

	def run_cycle(self) -> int:
		logs: list[str] = []
		self.status = "Running"
		self.last_run_on = now_datetime()
		self.run_log = self.run_log or ""
		save_doc(self)

		try:
			candidates = self._discover_candidates(logs)
			for candidate in candidates:
				try:
					self._process_candidate(candidate, logs)
				except Exception:
					candidate.status = "Failed"
					candidate.last_error = frappe.get_traceback()
					logs.append(
						f"Failed candidate {candidate.company_name or candidate.website}: {candidate.last_error}"
					)
					self._upsert_candidate(candidate)

			self.process_workflow(logs)

			self.generated_count = len(self.prospects)
			self.status = "Completed"
			logs.append(f"Completed with {self.generated_count} prospects.")
		except Exception:
			self.status = "Failed"
			logs.append(frappe.get_traceback())
			raise
		finally:
			self.run_log = "\n".join(logs)[-100000:]
			save_doc(self)

		return self.generated_count

	def _process_candidate(self, candidate: ProspectCandidate, logs: list[str]) -> None:
		row = self._find_existing_prospect_row(candidate)
		lead_name = row.lead if row else None
		deal_name = row.deal if row else None

		if self.auto_create_leads and not self.dry_run and not lead_name:
			lead_name = ensure_lead(candidate, self)
			candidate.status = "Lead Created"
			logs.append(f"Lead {lead_name} created or reused for {candidate.company_name}.")

		if self.auto_create_deals and lead_name and not self.dry_run and not deal_name:
			deal_name = ensure_deal(candidate, self, lead_name)
			candidate.status = "Deal Created"
			logs.append(f"Deal {deal_name} created or reused for {candidate.company_name}.")

		row = self._upsert_candidate(candidate)
		row.lead = lead_name
		row.deal = deal_name
		row.email_status = classify_email_status(candidate.email)
		row.icp_score = int(candidate.icp_score or 0)
		row.priority_tier = candidate.priority_tier or row.priority_tier or "C"
		row.service_fit = candidate.service_fit or row.service_fit
		row.contact_gap_status = candidate.contact_gap_status or row.contact_gap_status
		if not row.lifecycle_stage:
			row.lifecycle_stage = "Deal" if deal_name else "Lead" if lead_name else "Discovered"
		if not candidate.email:
			if row.response_status in (None, "", "Awaiting Outreach", "Ready To Send"):
				row.response_status = "No Email Found"
			if candidate.status not in {"Lead Created", "Deal Created"}:
				row.status = "No Email Found"
			logs.append(f"No email found for {candidate.company_name}. Draft retained only.")
		else:
			if row.response_status in (None, "", "No Email Found"):
				row.response_status = "Ready To Send" if self.auto_send_outreach else "Awaiting Outreach"
			if not row.next_action_on:
				row.next_action_on = now_datetime()
			if row.status in (None, "", "Discovered"):
				row.status = "Drafted"

		if lead_name and candidate.outreach_body and not self.dry_run and not row.outreach_attempts:
			add_outreach_comment("Lead", lead_name, candidate)
		if deal_name and candidate.outreach_body and not self.dry_run and not row.outreach_attempts:
			add_outreach_comment("Opportunity", deal_name, candidate)

	def _find_existing_prospect_row(self, candidate: ProspectCandidate):
		for row in self.prospects:
			if candidate.email and row.email and row.email == candidate.email:
				return row
			if candidate.website and row.website and row.website == candidate.website:
				return row
			if candidate.company_name and row.company_name == candidate.company_name:
				return row
		return None

	def _upsert_candidate(self, candidate: ProspectCandidate):
		row = self._find_existing_prospect_row(candidate)
		if not row:
			row = self.append("prospects", {})

		row.company_name = candidate.company_name
		if not row.status or row.status in {"Discovered", "Drafted", "Lead Created", "Deal Created", "No Email Found"}:
			row.status = candidate.status or row.status or "Discovered"
		row.website = candidate.website
		row.email = candidate.email or row.email
		row.phone = candidate.phone or row.phone
		row.location = candidate.location or row.location
		row.source_channel = candidate.source_channel or row.source_channel
		row.source_query = candidate.source_query
		row.source_url = candidate.source_url
		row.source_profile_url = candidate.source_profile_url or row.source_profile_url
		row.summary = candidate.summary or row.summary
		row.personalization_notes = candidate.personalization_notes or row.personalization_notes
		row.pain_hypothesis = candidate.pain_hypothesis or row.pain_hypothesis
		row.outreach_subject = candidate.outreach_subject or row.outreach_subject
		row.outreach_body = candidate.outreach_body or row.outreach_body
		row.icp_score = int(candidate.icp_score or row.icp_score or 0)
		row.priority_tier = candidate.priority_tier or row.priority_tier
		row.service_fit = candidate.service_fit or row.service_fit
		row.contact_gap_status = candidate.contact_gap_status or row.contact_gap_status
		row.last_error = candidate.last_error or ""
		return row

	def process_workflow(self, logs: list[str] | None = None) -> None:
		logs = logs or []
		self.last_automation_on = now_datetime()
		for row in self.prospects:
			try:
				process_prospect_workflow(self, row, logs)
			except Exception:
				row.status = "Failed"
				row.last_error = frappe.get_traceback()
				logs.append(f"Workflow failed for {row.company_name}: {row.last_error}")

	def _discover_candidates(self, logs: list[str]) -> list[ProspectCandidate]:
		queries = build_queries(self.search_terms, self.target_city, self.target_region, self.target_country)
		collected: list[ProspectCandidate] = seed_candidates_from_text(self.seed_prospects, self, logs)
		seen_domains: set[str] = set()
		for candidate in collected:
			domain = canonical_domain(candidate.website or candidate.source_profile_url or candidate.source_url)
			if domain:
				seen_domains.add(domain)

		for query in queries:
			logs.append(f"Search query: {query}")
			for result in search_duckduckgo(query, self.max_results):
				for seed in expand_result_targets(result):
					domain = canonical_domain(seed["url"])
					if not domain or domain in seen_domains:
						continue
					seen_domains.add(domain)
					candidate = enrich_candidate(seed, query)
					draft = draft_outreach(candidate, self)
					candidate.outreach_subject = draft.get("subject", "")
					candidate.outreach_body = draft.get("body", "")
					candidate.personalization_notes = draft.get("personalization_notes", "")
					candidate.pain_hypothesis = draft.get("pain_hypothesis", "")
					candidate.icp_score = score_candidate(candidate, self)
					candidate.priority_tier = priority_tier(candidate.icp_score)
					candidate.service_fit = infer_service_fit(candidate, self)
					candidate.contact_gap_status = infer_contact_gap_status(candidate)
					collected.append(candidate)
					logs.append(f"Drafted {candidate.company_name} <{candidate.email or 'no-email'}>.")
					if len(collected) >= self.max_results * 4:
						break
		return rank_candidates(collected, self.max_results)


@frappe.whitelist()
def run_campaign(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	count = doc.run_cycle()
	return {"name": doc.name, "count": count, "status": doc.status}


@frappe.whitelist()
def process_campaign_workflow(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	logs: list[str] = []
	doc.process_workflow(logs)
	if logs:
		doc.run_log = ((doc.run_log or "") + "\n" + "\n".join(logs)).strip()[-100000:]
	save_doc(doc)
	return {"name": doc.name, "status": doc.status, "prospects": len(doc.prospects)}


@frappe.whitelist()
def get_operator_snapshot(name: str) -> dict[str, str]:
	doc = frappe.get_doc("Remolda Campaign", name)
	return {"html": build_operator_snapshot_html(doc)}


@frappe.whitelist()
def ingest_seed_prospects(name: str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	logs: list[str] = []
	count = 0
	for candidate in seed_candidates_from_text(doc.seed_prospects, doc, logs):
		try:
			if candidate.website and not is_social_profile_url(candidate.website):
				try:
					enriched = enrich_candidate(
						{"url": candidate.website, "title": candidate.company_name or infer_company_name("", candidate.website)},
						candidate.source_query,
					)
					candidate.email = candidate.email or enriched.email
					candidate.phone = candidate.phone or enriched.phone
					candidate.location = candidate.location or enriched.location
					candidate.summary = enriched.summary or candidate.summary
				except Exception:
					logs.append(f"Seed enrichment skipped for {candidate.company_name}: {frappe.get_traceback().splitlines()[-1]}")
			draft = draft_outreach(candidate, doc)
			candidate.outreach_subject = draft.get("subject", "")
			candidate.outreach_body = draft.get("body", "")
			candidate.personalization_notes = draft.get("personalization_notes", "")
			candidate.pain_hypothesis = draft.get("pain_hypothesis", "")
			candidate.icp_score = score_candidate(candidate, doc)
			candidate.priority_tier = priority_tier(candidate.icp_score)
			candidate.service_fit = infer_service_fit(candidate, doc)
			candidate.contact_gap_status = infer_contact_gap_status(candidate)
			doc._process_candidate(candidate, logs)
			count += 1
		except Exception:
			logs.append(f"Seed prospect failed for {candidate.company_name or candidate.source_url}: {frappe.get_traceback()}")
	doc.process_workflow(logs)
	doc.generated_count = len(doc.prospects)
	doc.last_run_on = now_datetime()
	if logs:
		doc.run_log = ((doc.run_log or "") + "\n" + "\n".join(logs)).strip()[-100000:]
	save_doc(doc)
	return {"name": doc.name, "count": count, "status": doc.status, "prospects": len(doc.prospects)}


@frappe.whitelist()
def queue_social_outreach(name: str, row_names: list[str] | str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	rows = get_prospect_rows(doc, row_names)
	logs: list[str] = []
	count = 0
	for row in rows:
		if (row.source_channel or "") not in {"LinkedIn", "Facebook"}:
			continue
		row.social_outreach_body = build_social_outreach_body(doc, row)
		row.social_outreach_task = ensure_social_outreach_task(row, doc)
		if row.response_status == "Sent" or row.status == "Sent":
			row.social_stage = "DM Sent"
			row.social_next_step = "Wait for reply or identify decision maker email"
		elif row.email:
			row.social_stage = "Decision Maker Found"
			row.social_next_step = "Move into email outreach"
		else:
			row.social_stage = "Queued"
			row.social_next_step = "Send DM via social profile"
		row.contact_gap_status = row.contact_gap_status or "Needs Decision Maker"
		count += 1
		logs.append(f"Queued social outreach for {row.company_name}.")
	return finalize_campaign_action(doc, logs, count)


@frappe.whitelist()
def mark_social_dm_sent(name: str, row_names: list[str] | str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	rows = get_prospect_rows(doc, row_names)
	logs: list[str] = []
	count = 0
	for row in rows:
		if (row.source_channel or "") not in {"LinkedIn", "Facebook"}:
			continue
		if not row.social_outreach_body:
			row.social_outreach_body = build_social_outreach_body(doc, row)
		row.status = "Sent"
		row.response_status = "Sent"
		row.lifecycle_stage = "Outreach"
		row.last_contact_on = now_datetime()
		row.next_action_on = add_days(now_datetime(), int(doc.follow_up_delay_days or 3))
		row.outreach_attempts = int(row.outreach_attempts or 0) + 1
		row.social_outreach_task = ensure_social_outreach_task(row, doc)
		row.social_stage = "DM Sent"
		row.social_next_step = "Wait for reply or identify decision maker email"
		if row.lead:
			add_social_outreach_comment("Lead", row.lead, row)
		if row.deal:
			add_social_outreach_comment("Opportunity", row.deal, row)
		update_deal_after_touch(row)
		count += 1
		logs.append(f"Marked social DM sent for {row.company_name}.")
	return finalize_campaign_action(doc, logs, count)


@frappe.whitelist()
def mark_social_not_interested(name: str, row_names: list[str] | str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	rows = get_prospect_rows(doc, row_names)
	logs: list[str] = []
	count = 0
	for row in rows:
		row.response_status = "Not Interested"
		row.status = "Not Interested"
		row.lifecycle_stage = "Lost"
		row.social_stage = "Not Interested"
		row.social_next_step = "Stop outreach"
		mark_deal_closed(row, "Not Interested", logs)
		count += 1
		logs.append(f"Marked {row.company_name} as not interested.")
	return finalize_campaign_action(doc, logs, count)


@frappe.whitelist()
def mark_decision_maker_found(
	name: str, row_name: str, email: str, phone: str | None = None, contact_name: str | None = None
) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	row = get_prospect_row(doc, row_name)
	row.email = (email or "").strip().lower()
	if phone:
		row.phone = phone.strip()
	row.contact_gap_status = "Ready"
	row.email_status = classify_email_status(row.email)
	row.last_error = ""
	row.social_stage = "Decision Maker Found"
	row.social_next_step = "Prepare or send email outreach"
	if row.response_status in {"No Email Found", "", None}:
		row.response_status = "Ready To Send" if doc.auto_send_outreach else "Awaiting Outreach"
	if row.status in {"No Email Found", "Failed", "", None}:
		row.status = "Drafted"
	if contact_name:
		row.personalization_notes = (
			((row.personalization_notes or "").strip() + " | ") if row.personalization_notes else ""
		) + f"Decision maker found: {contact_name}"
	row.email_handoff_task = ensure_email_handoff(doc, row)
	logs = [f"Decision maker found for {row.company_name}: {row.email}."]
	return finalize_campaign_action(doc, logs, 1)


@frappe.whitelist()
def prepare_email_handoff(name: str, row_names: list[str] | str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	rows = get_prospect_rows(doc, row_names)
	logs: list[str] = []
	count = 0
	for row in rows:
		if not row.email:
			continue
		row.email_handoff_task = ensure_email_handoff(doc, row)
		row.social_stage = row.social_stage or "Decision Maker Found"
		row.social_next_step = "Review or send email outreach"
		if row.response_status in {"No Email Found", "", None}:
			row.response_status = "Ready To Send" if doc.auto_send_outreach else "Awaiting Outreach"
		if row.status in {"No Email Found", "Failed", "", None}:
			row.status = "Drafted"
		logs.append(f"Prepared email handoff for {row.company_name}.")
		count += 1
	return finalize_campaign_action(doc, logs, count)


@frappe.whitelist()
def send_email_now(name: str, row_names: list[str] | str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	rows = get_prospect_rows(doc, row_names)
	logs: list[str] = []
	count = 0
	for row in rows:
		if not row.email:
			continue
		if not row.outreach_subject or not row.outreach_body:
			candidate = ProspectCandidate(
				company_name=row.company_name,
				website=row.website or "",
				source_url=row.source_url or row.website or "",
				source_query=row.source_query or "",
				source_channel=row.source_channel or "Manual Seed",
				source_profile_url=row.source_profile_url or "",
				location=row.location or doc.target_city,
				email=row.email or "",
				phone=row.phone or "",
				summary=row.summary or "",
				personalization_notes=row.personalization_notes or "",
				pain_hypothesis=row.pain_hypothesis or "",
			)
			draft = draft_outreach(candidate, doc)
			row.outreach_subject = draft.get("subject", "")
			row.outreach_body = draft.get("body", "")
			row.personalization_notes = draft.get("personalization_notes", "") or row.personalization_notes
			row.pain_hypothesis = draft.get("pain_hypothesis", "") or row.pain_hypothesis
		dispatch_email(doc, row, row.outreach_subject, row.outreach_body, logs)
		row.outreach_attempts = int(row.outreach_attempts or 0) + 1
		row.last_contact_on = now_datetime()
		row.next_action_on = add_days(now_datetime(), int(doc.follow_up_delay_days or 3))
		row.response_status = "Sent"
		row.status = "Sent"
		row.lifecycle_stage = "Outreach"
		if (row.source_channel or "") in {"LinkedIn", "Facebook"}:
			row.social_stage = "DM Sent"
			row.social_next_step = "Wait for reply or identify decision maker email"
		update_deal_after_touch(row)
		count += 1
		logs.append(f"Sent email outreach immediately to {row.company_name} <{row.email}>.")
	return finalize_campaign_action(doc, logs, count)


@frappe.whitelist()
def log_social_reply(name: str, row_name: str, reply_text: str) -> dict[str, Any]:
	doc = frappe.get_doc("Remolda Campaign", name)
	row = get_prospect_row(doc, row_name)
	classification, summary = classify_response(doc, reply_text or "")
	row.latest_response_summary = summary
	row.response_status = classification
	row.status = classification if classification in {"Interested", "Won", "Not Interested"} else "Replied"
	row.social_stage = classification if classification in {"Interested", "Won", "Not Interested"} else "Replied"
	if classification == "Interested":
		row.lifecycle_stage = "Proposal"
		row.social_next_step = "Prepare proposal and continue deal"
		ensure_proposal(doc, row, [])
	elif classification == "Won":
		row.lifecycle_stage = "Won"
		row.social_next_step = "Kick off delivery"
		ensure_customer_success_motion(doc, row, [])
		process_post_sale_motion(doc, row, [])
	elif classification == "Not Interested":
		row.lifecycle_stage = "Lost"
		row.social_next_step = "Stop outreach"
		mark_deal_closed(row, "Not Interested", [])
	else:
		row.social_next_step = "Review reply and decide next move"
	add_social_reply_comment(row, reply_text, classification)
	logs = [f"Logged social reply for {row.company_name}: {classification}."]
	return finalize_campaign_action(doc, logs, 1)


def run_due_campaigns():
	for name in frappe.get_all("Remolda Campaign", filters={"auto_run": 1}, pluck="name"):
		doc = frappe.get_doc("Remolda Campaign", name)
		if doc.status == "Running":
			continue
		frequency = int(doc.run_frequency_hours or 24)
		if doc.last_run_on and now_datetime() < doc.last_run_on + timedelta(hours=frequency):
			continue
		try:
			doc.run_cycle()
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Remolda auto-run failed: {doc.name}")


def build_operator_snapshot_html(doc: RemoldaCampaign) -> str:
	rows = list(doc.prospects or [])
	total = len(rows)
	a_tier = sum(1 for row in rows if (row.priority_tier or "") == "A")
	no_email = sum(1 for row in rows if (row.response_status or "") == "No Email Found")
	sent = sum(1 for row in rows if (row.response_status or "") == "Sent")
	won = sum(1 for row in rows if (row.response_status or "") == "Won")
	customer_live = sum(1 for row in rows if (row.status or "") in {"Customer Live", "Upsell Opened"})
	upsell_open = sum(1 for row in rows if getattr(row, "upsell_deal", None))

	def is_social_queue_row(row) -> bool:
		return (
			(row.source_channel or "") in {"LinkedIn", "Facebook"}
			and (getattr(row, "social_outreach_task", None) or getattr(row, "research_task", None))
			and (getattr(row, "social_stage", "") or "") in {"Queued", "DM Sent", "Decision Maker Found"}
		)

	def is_social_replied_row(row) -> bool:
		return (getattr(row, "social_stage", "") or "") in {"Replied", "Interested", "Won", "Not Interested"}

	def is_proposal_follow_up_due(row) -> bool:
		return (
			(row.status or "") == "Proposal Sent"
			and getattr(row, "next_action_on", None)
			and row.next_action_on <= now_datetime()
		)

	social_queue = sum(
		1
		for row in rows
		if is_social_queue_row(row)
	)

	def badge(text: str, tone: str) -> str:
		colors = {
			"blue": "#dbeafe",
			"green": "#dcfce7",
			"amber": "#fef3c7",
			"red": "#fee2e2",
			"slate": "#e2e8f0",
		}
		return (
			f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
			f"background:{colors.get(tone, colors['slate'])};font-size:12px;font-weight:600;'>{html.escape(text)}</span>"
		)

	def prospect_row(row) -> str:
		return (
			"<tr>"
			f"<td><b>{html.escape(row.company_name or '')}</b></td>"
			f"<td>{html.escape(row.priority_tier or '-')}</td>"
			f"<td>{html.escape(str(row.icp_score or 0))}</td>"
			f"<td>{html.escape(row.response_status or row.status or '-')}</td>"
			f"<td>{html.escape(row.contact_gap_status or '-')}</td>"
			f"<td>{html.escape(row.service_fit or '-')}</td>"
			"</tr>"
		)

	top_priority = sorted(
		rows,
		key=lambda row: (int(row.icp_score or 0), 1 if row.email else 0, 1 if getattr(row, "upsell_deal", None) else 0),
		reverse=True,
	)[:5]
	recovery_rows = [row for row in rows if (row.response_status or "") == "No Email Found"][:5]
	customer_rows = [row for row in rows if (row.response_status or "") == "Won"][:5]
	social_rows = [
		row
		for row in rows
		if is_social_queue_row(row)
	][:5]
	queued_social_rows = [row for row in rows if (getattr(row, "social_stage", "") or "") == "Queued"][:5]
	dm_sent_rows = [row for row in rows if (getattr(row, "social_stage", "") or "") == "DM Sent"][:5]
	follow_up_due_rows = [
		row
		for row in rows
		if (getattr(row, "social_stage", "") or "") == "DM Sent"
		and getattr(row, "next_action_on", None)
		and row.next_action_on <= now_datetime()
	][:5]
	social_replied_rows = [row for row in rows if is_social_replied_row(row)][:5]
	proposal_follow_up_rows = [row for row in rows if is_proposal_follow_up_due(row)][:5]
	ready_for_email_rows = [row for row in rows if (getattr(row, "social_stage", "") or "") == "Decision Maker Found"][:5]
	queued_social = len([row for row in rows if (getattr(row, "social_stage", "") or "") == "Queued"])
	dm_sent = len([row for row in rows if (getattr(row, "social_stage", "") or "") == "DM Sent"])
	follow_up_due = len(
		[
			row
			for row in rows
			if (getattr(row, "social_stage", "") or "") == "DM Sent"
			and getattr(row, "next_action_on", None)
			and row.next_action_on <= now_datetime()
		]
	)
	social_replied = len([row for row in rows if is_social_replied_row(row)])
	proposal_follow_up_due = len([row for row in rows if is_proposal_follow_up_due(row)])
	ready_for_email = len([row for row in rows if (getattr(row, "social_stage", "") or "") == "Decision Maker Found"])

	return f"""
	<div style="display:flex;flex-direction:column;gap:16px;">
	  <div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:12px;">
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">Prospects</div><div style="font-size:24px;font-weight:700;">{total}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">A-Tier</div><div style="font-size:24px;font-weight:700;">{a_tier}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">Outreach Sent</div><div style="font-size:24px;font-weight:700;">{sent}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">No Email / Recovery</div><div style="font-size:24px;font-weight:700;">{no_email}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">Social Queue</div><div style="font-size:24px;font-weight:700;">{social_queue}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">Won Customers</div><div style="font-size:24px;font-weight:700;">{won}</div></div>
	    <div style="padding:12px;border:1px solid #e5e7eb;border-radius:12px;"><div style="font-size:12px;color:#64748b;">Upsell Open</div><div style="font-size:24px;font-weight:700;">{upsell_open}</div></div>
	  </div>

	  <div style="display:grid;grid-template-columns:1.2fr 1fr 1fr 1fr;gap:16px;">
	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Top Priority Prospects</div>
	        {badge(f"{a_tier} A-tier", "blue")}
	      </div>
	      <table style="width:100%;font-size:12px;border-collapse:collapse;">
	        <thead><tr style="text-align:left;color:#64748b;"><th>Company</th><th>Tier</th><th>ICP</th><th>Status</th><th>Gap</th><th>Fit</th></tr></thead>
	        <tbody>{''.join(prospect_row(row) for row in top_priority) or "<tr><td colspan='6' style='color:#64748b;'>No prospects yet.</td></tr>"}</tbody>
	      </table>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Recovery Queue</div>
	        {badge(f"{no_email} open", "amber")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'research_task', '') or 'No task')} · {html.escape(row.contact_gap_status or 'Needs Research')}</span></div>"
				for row in recovery_rows
			) or "<div style='color:#64748b;'>No contact recovery items.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Social Outreach Queue</div>
	        {badge(f"{social_queue} queued", "blue")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(row.source_channel or 'Social')} · {html.escape(getattr(row, 'social_outreach_task', '') or getattr(row, 'research_task', '') or 'No task')}</span><br><span style='color:#94a3b8;'>{html.escape(getattr(row, 'social_stage', '') or 'Queued')} · {html.escape(getattr(row, 'social_next_step', '') or 'Review social prospect')}</span></div>"
				for row in social_rows
			) or "<div style='color:#64748b;'>No social outreach items.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Delivery / Expansion</div>
	        {badge(f"{customer_live} live", "green")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(row.project or 'No project')} · {html.escape(getattr(row, 'sales_order', '') or 'No sales order')} · {html.escape(row.upsell_status or '-')}</span></div>"
				for row in customer_rows
			) or "<div style='color:#64748b;'>No won customers yet.</div>"}
	      </div>
	    </div>
	  </div>

	  <div style="display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:16px;">
	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Queued Social</div>
	        {badge(str(queued_social), "blue")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(row.source_channel or 'Social')} · {html.escape(getattr(row, 'social_next_step', '') or 'Send DM via social profile')}</span></div>"
				for row in queued_social_rows
			) or "<div style='color:#64748b;'>No queued social items.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">DM Sent Waiting</div>
	        {badge(str(dm_sent), "amber")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'social_outreach_task', '') or 'No task')} · {html.escape(getattr(row, 'social_next_step', '') or 'Wait for reply')}</span></div>"
				for row in dm_sent_rows
			) or "<div style='color:#64748b;'>No sent social items waiting.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Follow-Up Due</div>
	        {badge(str(follow_up_due), "red")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'social_follow_up_task', '') or getattr(row, 'social_outreach_task', '') or 'No task')} · {html.escape(getattr(row, 'social_next_step', '') or 'Send follow-up DM')}</span></div>"
				for row in follow_up_due_rows
			) or "<div style='color:#64748b;'>No overdue social follow-ups.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Social Replied</div>
	        {badge(str(social_replied), "green")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'latest_response_summary', '') or 'Reply logged')} · {html.escape(getattr(row, 'social_next_step', '') or 'Review reply')}</span></div>"
				for row in social_replied_rows
			) or "<div style='color:#64748b;'>No social replies yet.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Proposal Follow-Up Due</div>
	        {badge(str(proposal_follow_up_due), "amber")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'proposal_follow_up_task', '') or getattr(row, 'quotation', '') or 'No artifact')} · {html.escape(getattr(row, 'proposal_subject', '') or 'Proposal sent')}</span></div>"
				for row in proposal_follow_up_rows
			) or "<div style='color:#64748b;'>No proposal follow-ups due.</div>"}
	      </div>
	    </div>

	    <div style="padding:14px;border:1px solid #e5e7eb;border-radius:12px;">
	      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
	        <div style="font-weight:700;">Ready For Email Conversion</div>
	        {badge(str(ready_for_email), "green")}
	      </div>
	      <div style="display:flex;flex-direction:column;gap:8px;font-size:12px;">
	        {''.join(
				f"<div style='padding:8px;border:1px solid #f1f5f9;border-radius:10px;'><b>{html.escape(row.company_name or '')}</b><br><span style='color:#64748b;'>{html.escape(getattr(row, 'email_handoff_task', '') or row.email or 'No email')} · {html.escape(getattr(row, 'social_next_step', '') or 'Move into email outreach')}</span></div>"
				for row in ready_for_email_rows
			) or "<div style='color:#64748b;'>No social prospects ready for email conversion.</div>"}
	      </div>
	    </div>
	  </div>
	</div>
	"""


def run_remolda_automation():
	run_due_campaigns()
	for name in frappe.get_all("Remolda Campaign", pluck="name"):
		try:
			doc = frappe.get_doc("Remolda Campaign", name)
			logs: list[str] = []
			doc.process_workflow(logs)
			if logs:
				doc.run_log = ((doc.run_log or "") + "\n" + "\n".join(logs)).strip()[-100000:]
			save_doc(doc)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Remolda workflow failed: {name}")


def parse_row_names(row_names: list[str] | str | None) -> list[str]:
	if not row_names:
		return []
	if isinstance(row_names, str):
		row_names = json.loads(row_names) if row_names.strip().startswith("[") else [row_names]
	return [row_name for row_name in row_names if row_name]


def get_prospect_row(doc: RemoldaCampaign, row_name: str):
	for row in doc.prospects:
		if row.name == row_name:
			return row
	raise frappe.DoesNotExistError(f"Prospect row not found: {row_name}")


def get_prospect_rows(doc: RemoldaCampaign, row_names: list[str] | str | None):
	names = parse_row_names(row_names)
	if not names:
		raise frappe.ValidationError("Select at least one prospect row.")
	return [get_prospect_row(doc, row_name) for row_name in names]


def finalize_campaign_action(doc: RemoldaCampaign, logs: list[str], count: int) -> dict[str, Any]:
	if logs:
		doc.run_log = ((doc.run_log or "") + "\n" + "\n".join(logs)).strip()[-100000:]
	doc.generated_count = len(doc.prospects)
	save_doc(doc)
	return {"name": doc.name, "count": count, "status": doc.status, "prospects": len(doc.prospects)}


def build_queries(search_terms: str, city: str, region: str | None, country: str | None) -> list[str]:
	location = " ".join(part for part in [city, region, country] if part).strip()
	terms = [line.strip() for line in (search_terms or "").splitlines() if line.strip()]
	if not terms:
		terms = ["HVAC contractor"]
	return [f"{term} {location}".strip() for term in terms]


def seed_candidates_from_text(seed_prospects: str | None, campaign: RemoldaCampaign, logs: list[str]) -> list[ProspectCandidate]:
	candidates: list[ProspectCandidate] = []
	for raw_line in (seed_prospects or "").splitlines():
		line = raw_line.strip()
		if not line:
			continue
		candidate = parse_seed_line(line, campaign)
		if not candidate:
			continue
		candidate.icp_score = score_candidate(candidate, campaign)
		candidate.priority_tier = priority_tier(candidate.icp_score)
		candidate.service_fit = infer_service_fit(candidate, campaign)
		candidate.contact_gap_status = infer_contact_gap_status(candidate)
		candidates.append(candidate)
		logs.append(f"Seeded {candidate.company_name} from {candidate.source_channel}.")
	return rank_candidates(candidates, max(len(candidates), int(campaign.max_results or 5)))


def parse_seed_line(line: str, campaign: RemoldaCampaign) -> ProspectCandidate | None:
	parts = [part.strip() for part in line.split("|")]
	if len(parts) >= 5:
		company_name, url, email, phone, source_channel = parts[:5]
		profile_url = parts[5].strip() if len(parts) > 5 else url
		normalized_url = normalize_seed_url(url or "")
		normalized_profile_url = normalize_seed_url(profile_url or "")
		source_channel = source_channel or classify_seed_channel(normalized_profile_url or normalized_url or line)
		website = normalized_url if normalized_url and not is_social_profile_url(normalized_url) else ""
		return ProspectCandidate(
			company_name=company_name or infer_company_name("", normalized_url or normalized_profile_url or email),
			website=website,
			source_url=normalized_profile_url or normalized_url or "",
			source_query=f"seed:{source_channel or 'Manual Seed'}",
			source_channel=source_channel or "Manual Seed",
			source_profile_url=normalized_profile_url if is_social_profile_url(normalized_profile_url) else "",
			location=campaign.target_city,
			email=email,
			phone=phone,
			summary=f"Seeded prospect from {source_channel or 'Manual Seed'}.",
		)

	if "linkedin.com" in line.lower():
		return ProspectCandidate(
			company_name=infer_company_name("", line),
			website="",
			source_url=normalize_seed_url(line),
			source_query="seed:LinkedIn",
			source_channel="LinkedIn",
			source_profile_url=normalize_seed_url(line),
			location=campaign.target_city,
			summary="Seeded from LinkedIn profile/company URL.",
		)
	if "facebook.com" in line.lower():
		return ProspectCandidate(
			company_name=infer_company_name("", line),
			website="",
			source_url=normalize_seed_url(line),
			source_query="seed:Facebook",
			source_channel="Facebook",
			source_profile_url=normalize_seed_url(line),
			location=campaign.target_city,
			summary="Seeded from Facebook page URL.",
		)
	if "@" in line and " " not in line:
		email = line.lower()
		return ProspectCandidate(
			company_name=email.split("@")[0].replace(".", " ").title(),
			website="",
			source_url=email,
			source_query="seed:Manual Seed",
			source_channel="Manual Seed",
			location=campaign.target_city,
			email=email,
			summary="Seeded from direct email input.",
		)
	if line.startswith(("http://", "https://")):
		return ProspectCandidate(
			company_name=infer_company_name("", line),
			website=normalize_seed_url(line),
			source_url=normalize_seed_url(line),
			source_query="seed:Manual Seed",
			source_channel=classify_seed_channel(line),
			source_profile_url=normalize_seed_url(line),
			location=campaign.target_city,
			summary="Seeded from direct URL input.",
		)
	return ProspectCandidate(
		company_name=line,
		website="",
		source_url=line,
		source_query="seed:Manual Seed",
		source_channel="Manual Seed",
		location=campaign.target_city,
		summary="Seeded from company name input.",
	)


def normalize_seed_url(url: str) -> str:
	url = (url or "").strip()
	if not url:
		return ""
	if url.startswith(("http://", "https://")):
		return normalize_website_url(url)
	return url


def classify_seed_channel(value: str) -> str:
	low = value.lower()
	if "linkedin.com" in low:
		return "LinkedIn"
	if "facebook.com" in low:
		return "Facebook"
	return "Manual Seed"


def search_duckduckgo(query: str, limit: int) -> list[dict[str, str]]:
	response = requests.get(
		"https://html.duckduckgo.com/html/",
		params={"q": query},
		headers=SEARCH_HEADERS,
		timeout=20,
	)
	response.raise_for_status()

	results: list[dict[str, str]] = []
	for match in DDG_RESULT_RE.finditer(response.text):
		url = resolve_duckduckgo_url(html.unescape(match.group("href")))
		title = strip_html(match.group("title"))
		if not url or not title or should_skip_result(url):
			continue
		results.append({"url": url, "title": title})
		if len(results) >= limit * 3:
			break
	return results


def expand_result_targets(result: dict[str, str]) -> list[dict[str, str]]:
	url = result["url"]
	title = result["title"]
	if not looks_like_directory_result(url, title):
		return [result]

	try:
		page = fetch_page(url)
	except Exception:
		return []

	expanded = []
	for target_url in extract_external_company_links(page, url):
		expanded.append({"url": target_url, "title": infer_company_name("", target_url)})
	return expanded


def resolve_duckduckgo_url(href: str) -> str:
	for _ in range(3):
		parsed = urlparse(href)
		query = parse_qs(parsed.query)
		if "uddg" in query and query["uddg"]:
			href = unquote(query["uddg"][0])
			continue
		if "u3" in query and query["u3"]:
			href = unquote(query["u3"][0])
			continue
		break
	if href.startswith("//"):
		href = f"https:{href}"
	if href.startswith("/"):
		parsed = urlparse(href)
		query = parse_qs(parsed.query)
		if "uddg" in query and query["uddg"]:
			return unquote(query["uddg"][0])
		return urljoin("https://duckduckgo.com", href)
	return href


def should_skip_result(url: str) -> bool:
	domain = canonical_domain(url)
	if not domain:
		return True
	blocked_domains = {"duckduckgo.com", "www.duckduckgo.com", "bing.com", "www.bing.com"}
	if domain in blocked_domains:
		return True
	lowered = url.lower()
	return any(token in lowered for token in ["/y.js", "/aclick", "javascript:void", "msclkid="])


def looks_like_directory_result(url: str, title: str) -> bool:
	combined = f"{url} {title}".lower()
	patterns = [
		"best ",
		"top ",
		"review",
		"contractors",
		"services in ",
		"what the data says",
		"bestin",
		"furnaceprices",
	]
	return any(token in combined for token in patterns)


def extract_external_company_links(page: str, base_url: str) -> list[str]:
	base_domain = canonical_domain(base_url)
	links: list[str] = []
	for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
		if href.startswith(("mailto:", "tel:", "#")):
			continue
		absolute = urljoin(base_url, html.unescape(href))
		domain = canonical_domain(absolute)
		if not domain or domain == base_domain or should_skip_result(absolute):
			continue
		low = absolute.lower()
		if any(
			token in low
			for token in [
				"facebook.com",
				"instagram.com",
				"youtube.com",
				"linkedin.com",
				"x.com",
				"twitter.com",
				"reddit.com",
				"whatsapp.com",
				"pinterest.com",
				"shortpixel",
				"/wp-content/",
				".png",
				".jpg",
				".jpeg",
				".svg",
				".webp",
				"quotes.",
			]
		):
			continue
		if not any(token in low for token in ["hvac", "heating", "cooling", "furnace", "air"]):
			continue
		if absolute not in links:
			links.append(absolute)
		if len(links) >= 5:
			break
	return links


def enrich_candidate(result: dict[str, str], query: str) -> ProspectCandidate:
	url = result["url"]
	title = result["title"]
	page = fetch_page(url)
	body_text = strip_html(page)
	email = pick_contact_email(body_text)
	phone = pick_phone(body_text)
	description = extract_meta_description(page)
	company_name = infer_company_name(title, url)
	location = infer_location(body_text)
	if not email:
		for contact_url in extract_contact_page_links(page, url):
			try:
				contact_page = fetch_page(contact_url)
			except Exception:
				continue
			email = pick_contact_email(contact_page)
			phone = phone or pick_phone(contact_page)
			if email:
				break
	summary = truncate(description or body_text, 280)

	return ProspectCandidate(
		company_name=company_name,
		website=normalize_website_url(url),
		source_url=normalize_website_url(url),
		source_query=query,
		location=location,
		email=email,
		phone=phone,
		summary=summary,
	)


def fetch_page(url: str) -> str:
	response = requests.get(url, headers=SEARCH_HEADERS, timeout=20, allow_redirects=True)
	response.raise_for_status()
	return response.text


def pick_contact_email(text: str) -> str:
	seen = []
	for email in EMAIL_RE.findall(text or ""):
		clean = email.strip(".,;:()[]<>").lower()
		if clean.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".css", ".js")):
			continue
		if clean.endswith("@example.com") or clean.endswith("@example.org") or clean.endswith("@domain.com"):
			continue
		if clean not in seen:
			seen.append(clean)
	if not seen:
		return ""
	for preferred in seen:
		if any(token in preferred for token in ["info@", "contact@", "office@", "service@", "hello@", "sales@"]):
			return preferred
	return seen[0]


def pick_phone(text: str) -> str:
	match = PHONE_RE.search(text or "")
	return match.group(0).strip() if match else ""


def extract_contact_page_links(page: str, base_url: str) -> list[str]:
	links: list[str] = []
	for href in re.findall(r'href=["\']([^"\']+)["\']', page, re.I):
		if not re.search(r"(contact|about|reach-us|get-in-touch)", href, re.I):
			continue
		absolute = urljoin(base_url, html.unescape(href))
		if canonical_domain(absolute) != canonical_domain(base_url):
			continue
		if absolute not in links:
			links.append(absolute)
		if len(links) >= 5:
			break
	return links


def infer_company_name(title: str, url: str) -> str:
	if title:
		parts = [part.strip() for part in re.split(r"[|\-–—]", title) if part.strip()]
		if parts:
			return parts[0][:140]
	social_name = infer_company_name_from_profile_url(url)
	if social_name:
		return social_name[:140]
	domain = canonical_domain(url).replace("www.", "")
	return domain.split(".")[0].replace("-", " ").title()[:140]


def infer_company_name_from_profile_url(url: str) -> str:
	if not is_social_profile_url(url):
		return ""
	parsed = urlparse(url)
	parts = [part for part in parsed.path.split("/") if part]
	if not parts:
		return ""
	if parts[0] == "company" and len(parts) > 1:
		return prettify_slug(parts[1])
	return prettify_slug(parts[-1])


def prettify_slug(value: str) -> str:
	slug = re.sub(r"[_\-]+", " ", (value or "").strip(" /"))
	slug = re.sub(r"\s+", " ", slug).strip()
	return slug.title()


def is_social_profile_url(url: str) -> bool:
	domain = canonical_domain(url)
	return any(token in domain for token in ["linkedin.com", "facebook.com", "instagram.com"])


def normalize_website_url(url: str) -> str:
	parsed = urlparse(url)
	path = parsed.path.rstrip("/")
	return f"{parsed.scheme}://{parsed.netloc}{path}" if path else f"{parsed.scheme}://{parsed.netloc}"


def infer_location(text: str) -> str:
	for token in ["Ottawa", "Ontario", "Toronto", "Montreal", "Gatineau"]:
		if token.lower() in (text or "").lower():
			return token
	return ""


def score_candidate(candidate: ProspectCandidate, campaign: RemoldaCampaign) -> int:
	score = 0
	text = " ".join(
		part
		for part in [
			candidate.company_name,
			candidate.summary,
			candidate.website,
			candidate.personalization_notes,
			candidate.pain_hypothesis,
		]
		if part
	).lower()
	if any(token in text for token in ["hvac", "heating", "cooling", "furnace", "air conditioning"]):
		score += 30
	if candidate.email:
		score += 20
	if candidate.phone:
		score += 10
	if candidate.location and candidate.location.lower() == (campaign.target_city or "").lower():
		score += 15
	elif candidate.location:
		score += 5
	if any(token in text for token in ["commercial", "24/7", "emergency", "maintenance", "installation", "service"]):
		score += 10
	if candidate.summary and len(candidate.summary) > 80:
		score += 5
	if any(token in text for token in ["financing", "rebate", "blog"]):
		score -= 5
	return max(score, 0)


def priority_tier(score: int) -> str:
	if score >= 60:
		return "A"
	if score >= 40:
		return "B"
	return "C"


def infer_service_fit(candidate: ProspectCandidate, campaign: RemoldaCampaign) -> str:
	text = " ".join([candidate.summary or "", candidate.pain_hypothesis or "", candidate.website or ""]).lower()
	if any(token in text for token in ["dispatch", "quote", "scheduling", "after-hours", "service call"]):
		return campaign.service_offer
	return "HVAC AI Workflow Audit"


def infer_contact_gap_status(candidate: ProspectCandidate) -> str:
	if candidate.email:
		return "Ready"
	if candidate.source_channel in {"LinkedIn", "Facebook"} and candidate.source_profile_url:
		return "Needs Decision Maker"
	if candidate.phone and candidate.website:
		return "Needs Email"
	if candidate.website:
		return "Needs Decision Maker"
	return "Needs Research"


def is_deadlock_error(error: Exception) -> bool:
	text = f"{type(error).__name__}: {error}"
	return "deadlock" in text.lower() or "lock wait timeout" in text.lower()


def save_doc(doc: Document, retries: int = 4, delay_seconds: float = 0.5) -> None:
	for attempt in range(retries):
		try:
			doc.save(ignore_permissions=True)
			return
		except Exception as exc:
			if isinstance(exc, frappe.TimestampMismatchError) and attempt < retries - 1:
				frappe.db.rollback()
				latest_modified = frappe.db.get_value(doc.doctype, doc.name, "modified")
				if latest_modified:
					doc.modified = latest_modified
				time.sleep(delay_seconds * (attempt + 1))
				continue
			if not is_deadlock_error(exc) or attempt >= retries - 1:
				raise
			frappe.db.rollback()
			time.sleep(delay_seconds * (attempt + 1))


def rank_candidates(candidates: list[ProspectCandidate], limit: int) -> list[ProspectCandidate]:
	ranked = sorted(
		candidates,
		key=lambda candidate: (
			int(candidate.icp_score or 0),
			1 if candidate.email else 0,
			1 if candidate.phone else 0,
			len(candidate.summary or ""),
		),
		reverse=True,
	)
	deduped: list[ProspectCandidate] = []
	seen = set()
	for candidate in ranked:
		key = candidate.website or candidate.email or candidate.company_name
		if key in seen:
			continue
		seen.add(key)
		deduped.append(candidate)
		if len(deduped) >= limit:
			break
	return deduped


def extract_meta_description(page: str) -> str:
	match = re.search(
		r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
		page,
		re.I,
	)
	return html.unescape(match.group("content")).strip() if match else ""


def truncate(value: str, limit: int) -> str:
	value = re.sub(r"\s+", " ", (value or "")).strip()
	return value[:limit].rstrip() if len(value) > limit else value


def strip_html(value: str) -> str:
	return re.sub(r"\s+", " ", TAG_RE.sub(" ", value or "")).strip()


def canonical_domain(url: str) -> str:
	try:
		return (urlparse(url).netloc or "").lower()
	except Exception:
		return ""


def draft_outreach(candidate: ProspectCandidate, campaign: RemoldaCampaign) -> dict[str, str]:
	try:
		return generate_outreach_with_ollama(candidate, campaign)
	except Exception:
		return fallback_outreach(candidate, campaign)


def generate_outreach_with_ollama(
	candidate: ProspectCandidate, campaign: RemoldaCampaign
) -> dict[str, str]:
	prompt = f"""
You are Remolda, an AI transformation consultancy.

Write a concise cold outreach email for an HVAC company.
Goal: book a short call for a paid HVAC AI Workflow Audit.

Company:
- Name: {candidate.company_name}
- Website: {candidate.website}
- Location: {candidate.location or campaign.target_city}
- Public summary: {candidate.summary}
- Search query: {candidate.source_query}

Service offer:
- {campaign.service_offer}

Constraints:
- Professional and credible
- 110 to 170 words
- Mention one concrete HVAC workflow hypothesis like dispatching, quoting, service intake, maintenance scheduling, CSR load, after-hours lead capture
- No hype, no fake claims, no spammy urgency
- CTA is a short discovery call

Return strict JSON with keys:
subject, body, personalization_notes, pain_hypothesis
""".strip()

	response = requests.post(
		f"{(campaign.ollama_base_url or 'http://172.17.0.1:11434').rstrip('/')}/api/generate",
		json={
			"model": campaign.ollama_model or "qwen2.5:14b",
			"prompt": prompt,
			"stream": False,
			"format": "json",
		},
		timeout=120,
	)
	response.raise_for_status()
	payload = response.json()
	raw = payload.get("response", "{}")
	data = json.loads(raw)
	if not data.get("subject") or not data.get("body"):
		raise ValueError("Incomplete Ollama response")
	return {
		"subject": truncate(data.get("subject", ""), 140),
		"body": data.get("body", "").strip(),
		"personalization_notes": truncate(data.get("personalization_notes", ""), 280),
		"pain_hypothesis": truncate(data.get("pain_hypothesis", ""), 280),
	}


def fallback_outreach(candidate: ProspectCandidate, campaign: RemoldaCampaign) -> dict[str, str]:
	location = candidate.location or campaign.target_city
	pain = (
		"manual dispatching, quoting delays, and missed after-hours lead capture"
		if location
		else "manual service intake, dispatching, and quoting"
	)
	body = (
		f"Hi {candidate.company_name} team,\n\n"
		f"I came across your business while reviewing HVAC operators in {location or campaign.target_city}. "
		f"Based on your public presence, I suspect there may be room to tighten workflows around {pain}.\n\n"
		f"Remolda helps service businesses identify where AI can reduce admin load and improve response speed. "
		f"Our entry offer is a focused HVAC AI Workflow Audit: we review intake, dispatch, quoting, follow-up, and customer communication, then map the highest-impact automation opportunities.\n\n"
		f"If useful, I can share a short audit outline and discuss whether it fits your operation.\n\n"
		f"Best,\nRemolda"
	)
	return {
		"subject": f"{candidate.company_name}: HVAC workflow audit idea",
		"body": body,
		"personalization_notes": f"Located via query '{candidate.source_query}' and public website summary.",
		"pain_hypothesis": pain,
	}


def ensure_lead(candidate: ProspectCandidate, campaign: RemoldaCampaign) -> str:
	existing = find_existing_lead(candidate)
	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Lead",
			"company_name": candidate.company_name,
			"email_id": candidate.email,
			"website": candidate.website,
			"phone": candidate.phone,
			"territory": pick_territory(campaign),
			"qualification_status": "Qualified",
			"industry": "HVAC Services",
			"status": "Interested",
			"company": campaign.company,
			"title": candidate.company_name,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def find_existing_lead(candidate: ProspectCandidate) -> str | None:
	if candidate.email:
		existing = frappe.db.get_value("Lead", {"email_id": candidate.email}, "name")
		if existing:
			return existing
	if candidate.website:
		existing = frappe.db.get_value("Lead", {"website": candidate.website}, "name")
		if existing:
			return existing
	if candidate.company_name:
		return frappe.db.get_value("Lead", {"company_name": candidate.company_name}, "name")
	return None


def ensure_deal(candidate: ProspectCandidate, campaign: RemoldaCampaign, lead_name: str) -> str:
	existing = frappe.db.get_value(
		"Opportunity",
		{
			"opportunity_from": "Lead",
			"party_name": lead_name,
			"opportunity_type": campaign.service_offer,
		},
		"name",
	)
	if existing:
		return existing

	default_currency = frappe.db.get_value("Company", campaign.company, "default_currency") or "CAD"
	doc = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Lead",
			"party_name": lead_name,
			"status": "Open",
			"opportunity_type": campaign.service_offer,
			"sales_stage": "Target Identified",
			"company": campaign.company,
			"transaction_date": now_datetime().date(),
			"expected_closing": add_days(now_datetime().date(), 21),
			"currency": default_currency,
			"opportunity_amount": 2500,
			"probability": 15,
			"industry": "HVAC Services",
			"territory": pick_territory(campaign),
			"title": f"{candidate.company_name} - {campaign.service_offer}",
			"contact_email": candidate.email,
			"phone": candidate.phone,
			"website": candidate.website,
			"city": campaign.target_city,
			"state": campaign.target_region,
			"country": campaign.target_country,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def pick_territory(campaign: RemoldaCampaign) -> str | None:
	for value in [campaign.target_country, campaign.target_region, campaign.target_city, "Canada", "All Territories"]:
		if value and frappe.db.exists("Territory", value):
			return value
	return None


def classify_email_status(email: str | None) -> str:
	if not email:
		return "Unknown"
	low = email.lower()
	if low.endswith("@example.com") or low.endswith("@example.org") or low.endswith("@domain.com"):
		return "Placeholder"
	if low.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg")) or "@" not in low:
		return "Invalid"
	return "Valid"


def backfill_row_operational_fields(campaign: RemoldaCampaign, row) -> None:
	candidate = ProspectCandidate(
		company_name=row.company_name,
		website=row.website or "",
		source_url=row.source_url or row.website or "",
		source_query=row.source_query or "",
		location=row.location or "",
		email=row.email or "",
		phone=row.phone or "",
		summary=row.summary or "",
		personalization_notes=row.personalization_notes or "",
		pain_hypothesis=row.pain_hypothesis or "",
	)
	row.icp_score = int(row.icp_score or score_candidate(candidate, campaign))
	row.priority_tier = row.priority_tier or priority_tier(int(row.icp_score or 0))
	row.service_fit = row.service_fit or infer_service_fit(candidate, campaign)
	row.contact_gap_status = row.contact_gap_status or infer_contact_gap_status(candidate)
	if (row.source_channel or "") in {"LinkedIn", "Facebook"}:
		if not getattr(row, "social_stage", None):
			if row.response_status in {"Interested", "Won", "Not Interested"}:
				row.social_stage = row.response_status
			elif row.response_status == "Sent":
				row.social_stage = "DM Sent"
			elif row.email:
				row.social_stage = "Decision Maker Found"
			else:
				row.social_stage = "Queued"
		if not getattr(row, "social_next_step", None):
			if row.social_stage == "DM Sent":
				row.social_next_step = "Wait for reply or identify decision maker email"
			elif row.social_stage == "Decision Maker Found":
				row.social_next_step = "Move into email outreach"
			elif row.social_stage == "Interested":
				row.social_next_step = "Prepare proposal and continue deal"
			elif row.social_stage == "Won":
				row.social_next_step = "Kick off delivery"
			elif row.social_stage == "Not Interested":
				row.social_next_step = "Stop outreach"
			else:
				row.social_next_step = "Send DM via social profile"
		if row.social_stage == "DM Sent" and row.next_action_on and row.next_action_on <= now_datetime():
			row.social_next_step = "Send follow-up DM or escalate to email research"


def process_prospect_workflow(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if row.status == "Failed" and not (row.last_error or "").strip():
		row.status = "Drafted" if row.email else "No Email Found"

	if row.status in {"Failed", "Not Interested", "Unresponsive"}:
		return

	campaign_max_follow_ups = int(campaign.max_follow_ups or 0)
	row_outreach_attempts = int(row.outreach_attempts or 0)
	backfill_row_operational_fields(campaign, row)
	row.email_status = classify_email_status(row.email)
	sync_mailhog_replies(campaign, row, logs)

	sync_received_responses(campaign, row, logs)

	if row.response_status == "Won":
		ensure_customer_success_motion(campaign, row, logs)
		process_post_sale_motion(campaign, row, logs)
		return

	if row.response_status == "Interested":
		ensure_proposal(campaign, row, logs)
		if campaign.auto_send_proposals and row.status != "Proposal Sent":
			maybe_send_proposal(campaign, row, logs)
		if row.status == "Proposal Sent" and row.next_action_on and row.next_action_on <= now_datetime():
			row.proposal_follow_up_task = ensure_proposal_follow_up_task(row, campaign)
			if campaign.auto_send_proposals:
				maybe_send_proposal_follow_up(campaign, row, logs)
			if (row.source_channel or "") in {"LinkedIn", "Facebook"}:
				row.social_next_step = "Follow up on proposal and move to close"
		return

	if row.response_status in {"Not Interested", "Unresponsive"}:
		mark_deal_closed(row, row.response_status, logs)
		return

	if (row.source_channel or "") in {"LinkedIn", "Facebook"} and row.response_status == "Sent":
		if row.next_action_on and row.next_action_on <= now_datetime():
			row.social_stage = "DM Sent"
			row.social_next_step = "Send follow-up DM or escalate to email research"
			row.social_follow_up_task = ensure_social_follow_up_task(row, campaign)
		else:
			row.social_stage = "DM Sent"
			row.social_next_step = "Wait for reply or identify decision maker email"

	if not row.email:
		if row.response_status in (None, "", "Awaiting Outreach", "Ready To Send"):
			row.response_status = "No Email Found"
		row.status = "No Email Found"
		row.research_task = ensure_research_task(row, campaign)
		if (row.source_channel or "") in {"LinkedIn", "Facebook"} and getattr(row, "source_profile_url", None):
			row.social_outreach_body = build_social_outreach_body(campaign, row)
			row.social_outreach_task = ensure_social_outreach_task(row, campaign)
			if row.response_status == "Sent" and row.next_action_on and row.next_action_on <= now_datetime():
				row.social_stage = "DM Sent"
				row.social_next_step = "Send follow-up DM or escalate to email research"
				row.social_follow_up_task = ensure_social_follow_up_task(row, campaign)
		row.contact_gap_status = row.contact_gap_status or "Needs Email"
		return

	if row.response_status == "Blocked - No Outgoing Email":
		return

	if not campaign.auto_send_outreach:
		if row.response_status in (None, "", "Awaiting Outreach"):
			row.response_status = "Ready To Send"
		if row.email and row.status in (None, "", "Drafted", "Failed"):
			row.status = "Ready To Send"
		return

	if row.next_action_on and row.next_action_on > now_datetime():
		return

	if row_outreach_attempts > campaign_max_follow_ups:
		row.response_status = "Unresponsive"
		row.status = "Unresponsive"
		row.lifecycle_stage = "Lost"
		mark_deal_closed(row, "Unresponsive", logs)
		return

	maybe_send_touch(campaign, row, logs)
	process_post_sale_motion(campaign, row, logs)


def add_outreach_comment(doctype: str, name: str, candidate: ProspectCandidate) -> None:
	doc = frappe.get_doc(doctype, name)
	doc.add_comment(
		"Comment",
		(
			f"<b>Remolda Outreach Draft</b><br><br>"
			f"<b>Subject:</b> {html.escape(candidate.outreach_subject)}<br><br>"
			f"<pre>{html.escape(candidate.outreach_body)}</pre>"
		),
	)


def add_social_outreach_comment(doctype: str, name: str, row) -> None:
	doc = frappe.get_doc(doctype, name)
	doc.add_comment(
		"Comment",
		(
			f"<b>Remolda Social Outreach</b><br><br>"
			f"<b>Channel:</b> {html.escape(row.source_channel or 'Social')}<br>"
			f"<b>Profile:</b> {html.escape(row.source_profile_url or row.source_url or '')}<br><br>"
			f"<pre>{html.escape(row.social_outreach_body or '')}</pre>"
		),
	)


def add_social_reply_comment(row, reply_text: str, classification: str) -> None:
	content = (
		f"<b>Remolda Social Reply</b><br><br>"
		f"<b>Classification:</b> {html.escape(classification)}<br><br>"
		f"<pre>{html.escape(reply_text or '')}</pre>"
	)
	if row.lead:
		frappe.get_doc("Lead", row.lead).add_comment("Comment", content)
	if row.deal:
		frappe.get_doc("Opportunity", row.deal).add_comment("Comment", content)


def maybe_send_touch(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	subject, body = build_touch_content(campaign, row)
	if not subject or not body:
		return

	if not get_outgoing_sender(campaign):
		row.response_status = "Blocked - No Outgoing Email"
		row.status = "Ready To Send"
		row.last_error = "No default outgoing Email Account configured."
		logs.append(f"Blocked send for {row.company_name}: no outgoing Email Account.")
		return

	try:
		dispatch_email(campaign, row, subject, body, logs)
	except Exception:
		row.response_status = "Blocked - No Outgoing Email"
		row.status = "Ready To Send"
		row.last_error = frappe.get_traceback()
		logs.append(f"Send failed for {row.company_name}: {row.last_error}")
		return
	row.outreach_subject = subject
	row.outreach_body = body
	row.outreach_attempts = int(row.outreach_attempts or 0) + 1
	row.last_contact_on = now_datetime()
	row.next_action_on = add_days(now_datetime(), int(campaign.follow_up_delay_days or 3))
	row.response_status = "Sent"
	row.status = "Sent"
	row.lifecycle_stage = "Outreach" if row.outreach_attempts == 1 else "Follow Up"
	update_deal_after_touch(row)
	logs.append(f"Sent outreach attempt {row.outreach_attempts} to {row.company_name} <{row.email}>.")


def build_touch_content(campaign: RemoldaCampaign, row) -> tuple[str, str]:
	stage = int(row.outreach_attempts or 0)
	candidate = ProspectCandidate(
		company_name=row.company_name,
		website=row.website,
		source_url=row.source_url or row.website,
		source_query=row.source_query or "",
		location=row.location or campaign.target_city,
		email=row.email or "",
		phone=row.phone or "",
		summary=row.summary or "",
		personalization_notes=row.personalization_notes or "",
		pain_hypothesis=row.pain_hypothesis or "",
	)

	if stage == 0:
		return row.outreach_subject or "", row.outreach_body or ""

	if stage <= int(campaign.max_follow_ups or 0):
		return generate_follow_up(campaign, candidate, stage)

	return "", ""


def generate_follow_up(campaign: RemoldaCampaign, candidate: ProspectCandidate, stage: int) -> tuple[str, str]:
	try:
		return generate_follow_up_with_ollama(campaign, candidate, stage)
	except Exception:
		subject = f"Following up on {candidate.company_name}'s HVAC workflow audit"
		body = (
			f"Hi {candidate.company_name} team,\n\n"
			f"I wanted to follow up on my earlier note about a focused HVAC AI Workflow Audit. "
			f"We typically uncover quick wins around dispatching, quoting, maintenance scheduling, and after-hours lead capture.\n\n"
			f"If it helps, I can send over a short audit outline tailored to your operation and the likely bottlenecks we see for HVAC firms in {candidate.location or campaign.target_city}.\n\n"
			f"Best,\nRemolda"
		)
		return subject, body


def generate_follow_up_with_ollama(
	campaign: RemoldaCampaign, candidate: ProspectCandidate, stage: int
) -> tuple[str, str]:
	prompt = f"""
You are Remolda.
Write follow-up email #{stage} for an HVAC company that has not yet replied.

Company:
- Name: {candidate.company_name}
- Website: {candidate.website}
- Location: {candidate.location or campaign.target_city}
- Pain hypothesis: {candidate.pain_hypothesis or 'dispatching, quoting, and service coordination inefficiency'}

Constraints:
- concise
- professional
- 80 to 140 words
- mention one HVAC workflow problem
- no guilt-tripping
- ask for a short call or permission to send an audit outline

Return strict JSON with keys: subject, body
""".strip()
	response = requests.post(
		f"{(campaign.ollama_base_url or 'http://172.17.0.1:11434').rstrip('/')}/api/generate",
		json={
			"model": campaign.ollama_model or "qwen2.5:14b",
			"prompt": prompt,
			"stream": False,
			"format": "json",
		},
		timeout=120,
	)
	response.raise_for_status()
	data = json.loads(response.json().get("response", "{}"))
	return truncate(data.get("subject", ""), 140), data.get("body", "").strip()


def get_outgoing_sender(campaign: RemoldaCampaign) -> str | None:
	if campaign.sender_email:
		return campaign.sender_email
	email = frappe.db.get_value(
		"Email Account",
		{"enable_outgoing": 1, "default_outgoing": 1},
		"email_id",
	)
	if email:
		return email
	return frappe.db.get_value("Email Account", {"enable_outgoing": 1}, "email_id")


def get_outgoing_account(campaign: RemoldaCampaign):
	filters = {"enable_outgoing": 1}
	if campaign.sender_email:
		filters["email_id"] = campaign.sender_email
	name = frappe.db.get_value("Email Account", filters | {"default_outgoing": 1}, "name")
	if not name and campaign.sender_email:
		name = frappe.db.get_value("Email Account", {"enable_outgoing": 1, "email_id": campaign.sender_email}, "name")
	if not name:
		name = frappe.db.get_value("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}, "name")
	if not name:
		name = frappe.db.get_value("Email Account", {"enable_outgoing": 1}, "name")
	return frappe.get_doc("Email Account", name) if name else None


def get_mailhog_api_url(account) -> str | None:
	if not account or not account.smtp_server:
		return None
	server = (account.smtp_server or "").strip()
	if server == "erpnext-mailhog":
		return "http://erpnext-mailhog:8025"
	if server in {"127.0.0.1", "localhost"} and str(account.smtp_port or "") == "1025":
		return "http://172.17.0.1:8025"
	return None


def fetch_mailhog_messages(campaign: RemoldaCampaign) -> list[dict[str, Any]]:
	account = get_outgoing_account(campaign)
	api_url = get_mailhog_api_url(account)
	if not api_url:
		return []
	cache_key = f"_mailhog_messages_cache_{campaign.name}"
	cached = getattr(frappe.flags, cache_key, None)
	if cached is not None:
		return cached
	response = requests.get(f"{api_url.rstrip('/')}/api/v2/messages", timeout=20)
	response.raise_for_status()
	items = response.json().get("items", [])
	setattr(frappe.flags, cache_key, items)
	return items


def sync_mailhog_replies(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if not row.email or not row.lead:
		return
	try:
		items = fetch_mailhog_messages(campaign)
	except Exception:
		return

	sender_email = (get_outgoing_sender(campaign) or "").lower()
	prospect_email = (row.email or "").lower()
	for item in items:
		message_id = (
			item.get("Content", {}).get("Headers", {}).get("Message-ID", [item.get("ID")])[0] or item.get("ID")
		)
		if not message_id or frappe.db.exists("Communication", {"message_id": message_id}):
			continue
		from_header = item.get("Content", {}).get("Headers", {}).get("From", [""])[0].lower()
		to_headers = [value.lower() for value in item.get("Content", {}).get("Headers", {}).get("To", [])]
		if prospect_email not in from_header:
			continue
		if not any(sender_email in value for value in to_headers):
			continue
		body = decode_mailhog_body(item.get("Content", {}).get("Body", ""))
		subject = item.get("Content", {}).get("Headers", {}).get("Subject", ["Reply"])[0]
		create_received_communication(row, subject, body, message_id, prospect_email, sender_email)
		logs.append(f"Ingested MailHog reply for {row.company_name} from {prospect_email}.")


def dispatch_email(campaign: RemoldaCampaign, row, subject: str, body: str, logs: list[str]) -> None:
	account = get_outgoing_account(campaign)
	if not account:
		raise frappe.ValidationError("No outgoing Email Account configured.")
	send_via_smtp(account, row.email, subject, body)
	record_sent_email(row, account.email_id, subject, body)
	candidate = ProspectCandidate(
		company_name=row.company_name,
		website=row.website,
		source_url=row.source_url or row.website,
		source_query=row.source_query or "",
		location=row.location or "",
		email=row.email or "",
		phone=row.phone or "",
		outreach_subject=subject,
		outreach_body=body,
	)
	if row.lead:
		add_outreach_comment("Lead", row.lead, candidate)
	if row.deal:
		add_outreach_comment("Opportunity", row.deal, candidate)


def decode_mailhog_body(body: str) -> str:
	try:
		return quopri.decodestring(body.encode()).decode("utf-8", errors="replace")
	except Exception:
		return body


def send_via_smtp(account, recipient: str, subject: str, body: str) -> None:
	message = EmailMessage()
	message["From"] = account.email_id
	message["To"] = recipient
	message["Subject"] = subject
	message.set_content(body)

	port = int(account.smtp_port or 25)
	if account.use_ssl_for_outgoing:
		server = smtplib.SMTP_SSL(account.smtp_server, port, timeout=30)
	else:
		server = smtplib.SMTP(account.smtp_server, port, timeout=30)

	try:
		server.ehlo()
		if account.use_tls:
			server.starttls()
			server.ehlo()
		if not account.no_smtp_authentication:
			password = account.get_password("password")
			login_id = account.login_id if account.login_id_is_different else account.email_id
			server.login(login_id, password)
		server.send_message(message)
	finally:
		server.quit()


def record_sent_email(row, sender: str, subject: str, body: str) -> None:
	if not row.lead:
		return
	frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Sent",
			"email_status": "Open",
			"status": "Linked",
			"subject": subject,
			"sender": sender,
			"recipients": row.email,
			"content": body.replace("\n", "<br>"),
			"reference_doctype": "Lead",
			"reference_name": row.lead,
		}
	).insert(ignore_permissions=True)


def create_received_communication(
	row, subject: str, body: str, message_id: str, sender: str, recipient: str
) -> None:
	frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Received",
			"email_status": "Open",
			"status": "Linked",
			"subject": subject,
			"sender": sender,
			"recipients": recipient,
			"content": body.replace("\n", "<br>"),
			"text_content": body,
			"message_id": message_id,
			"reference_doctype": "Lead",
			"reference_name": row.lead,
		}
	).insert(ignore_permissions=True)


def update_deal_after_touch(row) -> None:
	if not row.deal:
		return
	doc = frappe.get_doc("Opportunity", row.deal)
	if row.outreach_attempts == 1:
		doc.sales_stage = "Qualified HVAC Lead"
		doc.probability = max(float(doc.probability or 0), 20)
	else:
		doc.sales_stage = "Discovery Booked" if doc.sales_stage == "Target Identified" else doc.sales_stage
		doc.probability = max(float(doc.probability or 0), 25)
	save_doc(doc)


def sync_received_responses(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if not row.lead or row.response_status in {"Won", "Not Interested"}:
		return
	comms = frappe.get_all(
		"Communication",
		filters={
			"reference_doctype": "Lead",
			"reference_name": row.lead,
			"sent_or_received": "Received",
			"communication_medium": "Email",
		},
		fields=["name", "content", "creation", "sender", "subject"],
		order_by="creation desc",
		limit=1,
	)
	if not comms:
		return
	latest = comms[0]
	if row.last_contact_on and latest.creation <= row.last_contact_on:
		return

	classification, summary = classify_response(campaign, latest.get("content") or "")
	row.latest_response_summary = summary
	row.response_status = classification
	row.status = classification if classification in {"Interested", "Won", "Not Interested"} else "Replied"
	if classification == "Interested":
		row.lifecycle_stage = "Proposal"
	elif classification == "Won":
		row.lifecycle_stage = "Won"
	logs.append(f"Classified reply from {row.company_name} as {classification}.")

	if row.deal:
		doc = frappe.get_doc("Opportunity", row.deal)
		if classification == "Interested":
			doc.sales_stage = "Discovery Booked"
			doc.probability = max(float(doc.probability or 0), 45)
			doc.status = "Replied"
		elif classification == "Won":
			doc.sales_stage = "Audit Won"
			doc.status = "Converted"
			doc.probability = max(float(doc.probability or 0), 100)
		elif classification == "Not Interested":
			doc.status = "Lost"
			doc.order_lost_reason = "Prospect replied not interested."
		save_doc(doc)


def classify_response(campaign: RemoldaCampaign, content: str) -> tuple[str, str]:
	text = strip_html(content or "").strip()
	low = text.lower()
	if any(
		token in low
		for token in [
			"go ahead",
			"approved",
			"approve this",
			"looks good",
			"lets proceed",
			"please proceed",
			"we are in",
			"we're in",
			"accepted",
			"accept the proposal",
			"ready to start",
			"ready to move forward",
			"confirm the kickoff",
			"lets do it",
		]
	):
		return "Won", truncate(text, 280)
	if any(token in low for token in ["not interested", "no thanks", "remove me", "unsubscribe", "stop"]):
		return "Not Interested", truncate(text, 280)
	if any(token in low for token in ["yes", "interested", "let's talk", "lets talk", "book", "call", "audit", "send details"]):
		return "Interested", truncate(text, 280)
	if not campaign.classify_responses:
		return "Replied", truncate(text, 280)
	try:
		return classify_response_with_ollama(campaign, text)
	except Exception:
		return "Replied", truncate(text, 280)


def classify_response_with_ollama(campaign: RemoldaCampaign, text: str) -> tuple[str, str]:
	prompt = f"""
Classify this HVAC prospect reply for Remolda.

Reply:
{text}

Return strict JSON with keys:
classification, summary

Allowed classification values:
Interested, Won, Not Interested, Replied
""".strip()
	response = requests.post(
		f"{(campaign.ollama_base_url or 'http://172.17.0.1:11434').rstrip('/')}/api/generate",
		json={
			"model": campaign.ollama_model or "qwen2.5:14b",
			"prompt": prompt,
			"stream": False,
			"format": "json",
		},
		timeout=120,
	)
	response.raise_for_status()
	data = json.loads(response.json().get("response", "{}"))
	classification = data.get("classification", "Replied")
	if classification not in {"Interested", "Won", "Not Interested", "Replied"}:
		classification = "Replied"
	return classification, truncate(data.get("summary", text), 280)


def ensure_proposal(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	proposal_created = False
	if not row.proposal_body:
		subject, body = generate_proposal(campaign, row)
		row.proposal_subject = subject
		row.proposal_body = body
		row.status = "Proposal Drafted"
		row.lifecycle_stage = "Proposal"
		proposal_created = True
	quotation_name = ensure_sales_quotation(campaign, row)
	if quotation_name:
		row.quotation = quotation_name
	if row.deal:
		doc = frappe.get_doc("Opportunity", row.deal)
		doc.sales_stage = "Audit Scoped"
		doc.probability = max(float(doc.probability or 0), 55)
		save_doc(doc)
	if proposal_created:
		logs.append(f"Proposal drafted for {row.company_name}.")
	if quotation_name:
		logs.append(f"Quotation {quotation_name} is linked to {row.company_name}.")


def generate_proposal(campaign: RemoldaCampaign, row) -> tuple[str, str]:
	try:
		return generate_proposal_with_ollama(campaign, row)
	except Exception:
		subject = f"{row.company_name}: HVAC AI Workflow Audit proposal"
		body = (
			f"Hi {row.company_name} team,\n\n"
			f"Based on your interest, here is the outline for a focused HVAC AI Workflow Audit.\n\n"
			f"Scope:\n"
			f"- review service intake, dispatching, quoting, and follow-up workflows\n"
			f"- identify bottlenecks and manual handoffs\n"
			f"- prioritize 3 to 5 AI automation opportunities\n"
			f"- deliver a roadmap for implementation and ROI hypotheses\n\n"
			f"Typical duration: 2 weeks.\n"
			f"Deliverables: current-state map, quick wins, recommended AI workflow stack, implementation roadmap.\n\n"
			f"If this fits, I can send a final commercial proposal and schedule the kickoff call.\n\n"
			f"Best,\nRemolda"
		)
		return subject, body


def generate_proposal_with_ollama(campaign: RemoldaCampaign, row) -> tuple[str, str]:
	prompt = f"""
Write a concise commercial proposal email for an HVAC AI Workflow Audit.

Company:
- Name: {row.company_name}
- Website: {row.website}
- Pain hypothesis: {row.pain_hypothesis}
- Latest response summary: {row.latest_response_summary}

Constraints:
- 160 to 240 words
- include scope, deliverables, duration, and next step
- tone: consulting, professional, not hype

Return strict JSON with keys: subject, body
""".strip()
	response = requests.post(
		f"{(campaign.ollama_base_url or 'http://172.17.0.1:11434').rstrip('/')}/api/generate",
		json={
			"model": campaign.ollama_model or "qwen2.5:14b",
			"prompt": prompt,
			"stream": False,
			"format": "json",
		},
		timeout=120,
	)
	response.raise_for_status()
	data = json.loads(response.json().get("response", "{}"))
	return truncate(data.get("subject", ""), 140), data.get("body", "").strip()


def maybe_send_proposal(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if not row.email or not row.proposal_body:
		return
	if row.status == "Proposal Sent":
		return
	if not row.quotation:
		row.quotation = ensure_sales_quotation(campaign, row)
	if not get_outgoing_sender(campaign):
		row.response_status = "Blocked - No Outgoing Email"
		row.last_error = "No default outgoing Email Account configured for proposal send."
		return
	try:
		dispatch_email(campaign, row, row.proposal_subject, row.proposal_body, logs)
	except Exception:
		row.response_status = "Blocked - No Outgoing Email"
		row.last_error = frappe.get_traceback()
		logs.append(f"Proposal send failed for {row.company_name}: {row.last_error}")
		return
	row.status = "Proposal Sent"
	row.response_status = "Interested"
	row.lifecycle_stage = "Proposal"
	row.last_contact_on = now_datetime()
	row.next_action_on = add_days(now_datetime(), int(campaign.follow_up_delay_days or 3))
	if row.deal:
		doc = frappe.get_doc("Opportunity", row.deal)
		doc.sales_stage = "Audit Proposal Sent"
		doc.probability = max(float(doc.probability or 0), 65)
		save_doc(doc)
	logs.append(f"Proposal sent to {row.company_name}.")


def maybe_send_proposal_follow_up(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if not row.email or (row.status or "") != "Proposal Sent":
		return
	attempt = int(getattr(row, "proposal_follow_up_attempts", 0) or 0)
	if attempt >= int(campaign.max_follow_ups or 0):
		return
	subject, body = generate_proposal_follow_up(campaign, row, attempt + 1)
	if not subject or not body:
		return
	if not get_outgoing_sender(campaign):
		row.last_error = "No default outgoing Email Account configured for proposal follow-up."
		return
	try:
		dispatch_email(campaign, row, subject, body, logs)
	except Exception:
		row.last_error = frappe.get_traceback()
		logs.append(f"Proposal follow-up failed for {row.company_name}: {row.last_error}")
		return
	row.proposal_follow_up_attempts = attempt + 1
	row.last_contact_on = now_datetime()
	row.next_action_on = add_days(now_datetime(), int(campaign.follow_up_delay_days or 3))
	row.social_next_step = "Proposal follow-up sent, wait for reply"
	logs.append(f"Proposal follow-up {row.proposal_follow_up_attempts} sent to {row.company_name}.")


def generate_proposal_follow_up(campaign: RemoldaCampaign, row, stage: int) -> tuple[str, str]:
	try:
		return generate_proposal_follow_up_with_ollama(campaign, row, stage)
	except Exception:
		subject = f"Following up on the HVAC AI Workflow Audit proposal for {row.company_name}"
		body = (
			f"Hi {row.company_name} team,\n\n"
			f"I wanted to follow up on the HVAC AI Workflow Audit proposal I sent over. "
			f"The main outcome is a clear implementation roadmap around dispatching, quoting, intake, and follow-up workflows.\n\n"
			f"If it helps, I can answer any scope or pricing questions and suggest the fastest kickoff path.\n\n"
			f"Best,\nRemolda"
		)
		return truncate(subject, 140), body


def generate_proposal_follow_up_with_ollama(
	campaign: RemoldaCampaign, row, stage: int
) -> tuple[str, str]:
	prompt = f"""
Write follow-up email #{stage} for a sent HVAC AI Workflow Audit proposal.

Company:
- Name: {row.company_name}
- Website: {row.website}
- Proposal subject: {row.proposal_subject}
- Latest response summary: {row.latest_response_summary or 'No reply yet'}

Constraints:
- concise
- professional
- 90 to 150 words
- mention the proposal and offer to answer scope/pricing questions
- ask for a short reply or call

Return strict JSON with keys: subject, body
""".strip()
	response = requests.post(
		f"{(campaign.ollama_base_url or 'http://172.17.0.1:11434').rstrip('/')}/api/generate",
		json={
			"model": campaign.ollama_model or "qwen2.5:14b",
			"prompt": prompt,
			"stream": False,
			"format": "json",
		},
		timeout=120,
	)
	response.raise_for_status()
	data = json.loads(response.json().get("response", "{}"))
	return truncate(data.get("subject", ""), 140), data.get("body", "").strip()


def ensure_sales_quotation(campaign: RemoldaCampaign, row) -> str | None:
	if getattr(row, "quotation", None) and frappe.db.exists("Quotation", row.quotation):
		return row.quotation
	if row.deal:
		existing_rows = frappe.get_all(
			"Quotation",
			filters={"opportunity": row.deal, "docstatus": ["!=", 2]},
			pluck="name",
			limit=1,
		)
		existing = existing_rows[0] if existing_rows else None
		if existing:
			return existing

	party_type, party_name = get_quotation_party(row)
	if not party_name:
		return None

	service_item = ensure_remolda_service_item(campaign, row)
	selling_price_list = get_default_selling_price_list()
	default_currency = (
		frappe.db.get_value("Price List", selling_price_list, "currency")
		or frappe.db.get_value("Company", campaign.company, "default_currency")
		or "CAD"
	)
	rate = get_default_offer_amount(row)
	quotation = frappe.get_doc(
		{
			"doctype": "Quotation",
			"quotation_to": party_type,
			"party_name": party_name,
			"company": campaign.company,
			"transaction_date": now_datetime().date(),
			"valid_till": add_days(now_datetime().date(), 14),
			"order_type": "Sales",
			"territory": pick_territory(campaign),
			"currency": default_currency,
			"selling_price_list": selling_price_list,
			"opportunity": row.deal,
			"contact_email": row.email,
			"contact_mobile": row.phone,
			"terms": row.proposal_body or "",
			"items": [
				{
					"item_code": service_item,
					"item_name": campaign.service_offer,
					"description": row.proposal_body or f"{campaign.service_offer} for {row.company_name}",
					"qty": 1,
					"uom": frappe.db.get_value("Item", service_item, "stock_uom") or "Nos",
					"conversion_factor": 1,
					"rate": rate,
				}
			],
		}
	)
	quotation.insert(ignore_permissions=True)
	add_sales_artifact_comment(row, "Quotation", quotation.name)
	return quotation.name


def get_quotation_party(row) -> tuple[str, str | None]:
	if row.customer:
		return "Customer", row.customer
	if row.lead:
		return "Lead", row.lead
	return "Lead", None


def service_item_code(service_offer: str) -> str:
	slug = re.sub(r"[^A-Z0-9]+", "-", (service_offer or "REMOLDA SERVICE").upper()).strip("-")
	slug = slug[:32] or "REMOLDA-SERVICE"
	return f"REM-{slug}"


def ensure_remolda_service_item(campaign: RemoldaCampaign, row) -> str:
	item_code = service_item_code(campaign.service_offer or "Remolda Service")
	if frappe.db.exists("Item", item_code):
		ensure_item_price(item_code, get_default_selling_price_list(), get_default_offer_amount(row))
		return item_code

	existing = frappe.db.get_value("Item", {"item_name": campaign.service_offer}, "name")
	if existing:
		ensure_item_price(existing, get_default_selling_price_list(), get_default_offer_amount(row))
		return existing

	item_group = (
		frappe.db.get_value("Item Group", {"is_group": 0}, "name")
		or frappe.db.get_value("Item Group", {}, "name")
		or "All Item Groups"
	)
	uom = frappe.db.get_value("UOM", {"enabled": 1}, "name") or frappe.db.get_value("UOM", {}, "name") or "Nos"
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": campaign.service_offer,
			"description": f"Remolda offer: {campaign.service_offer}",
			"item_group": item_group,
			"stock_uom": uom,
			"is_stock_item": 0,
			"is_sales_item": 1,
			"include_item_in_manufacturing": 0,
			"standard_rate": get_default_offer_amount(row),
		}
	)
	item.insert(ignore_permissions=True)
	ensure_item_price(item.name, get_default_selling_price_list(), get_default_offer_amount(row))
	return item.name


def get_default_selling_price_list() -> str:
	return (
		frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		or frappe.db.get_value("Price List", {"selling": 1}, "name")
		or "Standard Selling"
	)


def get_default_offer_amount(row) -> float:
	if row.deal and frappe.db.exists("Opportunity", row.deal):
		return float(frappe.db.get_value("Opportunity", row.deal, "opportunity_amount") or 2500)
	return 2500.0


def ensure_item_price(item_code: str, price_list: str, rate: float) -> None:
	if not item_code or not price_list:
		return
	existing = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		"name",
	)
	currency = frappe.db.get_value("Price List", price_list, "currency") or "CAD"
	if existing:
		frappe.db.set_value(
			"Item Price",
			existing,
			{"price_list_rate": rate, "currency": currency},
			update_modified=True,
		)
		return
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": price_list,
			"price_list_rate": rate,
			"currency": currency,
			"selling": 1,
		}
	).insert(ignore_permissions=True)


def add_sales_artifact_comment(row, artifact_type: str, artifact_name: str) -> None:
	content = (
		f"<b>Remolda {html.escape(artifact_type)}</b><br><br>"
		f"<b>Reference:</b> {html.escape(artifact_name)}<br>"
		f"<b>Company:</b> {html.escape(row.company_name or '')}<br>"
		f"<b>Status:</b> {html.escape(row.status or row.response_status or '-')}"
	)
	if row.lead:
		frappe.get_doc("Lead", row.lead).add_comment("Comment", content)
	if row.deal:
		frappe.get_doc("Opportunity", row.deal).add_comment("Comment", content)


def ensure_proposal_follow_up_task(row, campaign: RemoldaCampaign) -> str:
	subject = f"Follow up on proposal for {row.company_name}"
	if getattr(row, "proposal_follow_up_task", None) and frappe.db.exists("Task", row.proposal_follow_up_task):
		task_name = row.proposal_follow_up_task
	else:
		task_name = frappe.db.get_value("Task", {"subject": subject}, "name")
	description = (
		f"Proposal follow-up is due.\n\n"
		f"Company: {row.company_name}\n"
		f"Email: {row.email or 'n/a'}\n"
		f"Lead: {row.lead or 'n/a'}\n"
		f"Deal: {row.deal or 'n/a'}\n"
		f"Quotation: {getattr(row, 'quotation', '') or 'n/a'}\n"
		f"Last contact: {row.last_contact_on or 'n/a'}\n"
		f"Next action on: {row.next_action_on or 'n/a'}\n\n"
		f"Recommended next step: follow up on the sent proposal, answer commercial questions, and move the deal to close."
	)
	if task_name:
		frappe.db.set_value(
			"Task",
			task_name,
			{"description": description, "priority": "High"},
			update_modified=True,
		)
		return task_name
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"status": "Open",
			"priority": "High",
			"description": description,
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), 1),
			"company": campaign.company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_customer_success_motion(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	customer_name = ensure_customer(row, campaign)
	sales_order_name = ensure_sales_order(row, campaign, customer_name)
	project_name = ensure_project(row, campaign, customer_name)
	onboarding_task = ensure_project_task(
		project_name,
		"Audit Kickoff and Stakeholder Interviews",
		campaign.company,
		description=(
			f"Kick off the Remolda Cycle for {row.company_name}: confirm objectives, collect materials, "
			"and schedule stakeholder interviews."
		),
		days_to_due=3,
	)
	qbr_task = ensure_project_task(
		project_name,
		"Quarterly AI Value Review and Expansion Plan",
		campaign.company,
		description=(
			f"Review delivered value for {row.company_name}, identify next automation wave, "
			"and open expansion path if justified."
		),
		days_to_due=45,
	)
	support_issue = ensure_support_issue(row, campaign, customer_name, project_name)

	row.customer = customer_name
	row.sales_order = sales_order_name
	row.project = project_name
	row.onboarding_task = onboarding_task
	row.qbr_task = qbr_task
	row.support_issue = support_issue
	row.status = "Customer Live"
	row.response_status = "Won"
	row.lifecycle_stage = "Won"
	row.delivery_status = row.delivery_status or "Program Created"
	row.support_status = row.support_status or "Support Desk Open"
	row.upsell_status = row.upsell_status or "Monitoring"

	if row.deal:
		doc = frappe.get_doc("Opportunity", row.deal)
		doc.sales_stage = "Audit Won"
		doc.status = "Converted"
		doc.probability = max(float(doc.probability or 0), 100)
		save_doc(doc)

	logs.append(
		f"Customer-success motion created for {row.company_name}: {customer_name}, {sales_order_name}, {project_name}."
	)


def ensure_customer(row, campaign: RemoldaCampaign) -> str:
	if row.customer and frappe.db.exists("Customer", row.customer):
		return row.customer
	if row.deal:
		existing = frappe.db.get_value("Customer", {"opportunity_name": row.deal}, "name")
		if existing:
			return existing
	if row.lead:
		existing = frappe.db.get_value("Customer", {"lead_name": row.lead}, "name")
		if existing:
			return existing
	existing = frappe.db.get_value("Customer", {"customer_name": row.company_name}, "name")
	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_type": "Company",
			"customer_name": row.company_name,
			"customer_group": frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups",
			"territory": frappe.db.get_value("Territory", {"name": "Canada"}, "name")
			or frappe.db.get_value("Territory", {}, "name"),
			"default_currency": frappe.db.get_value("Company", campaign.company, "default_currency") or "CAD",
			"lead_name": row.lead,
			"opportunity_name": row.deal,
			"industry": "HVAC Services",
			"website": row.website,
			"email_id": row.email,
			"mobile_no": row.phone,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_project(row, campaign: RemoldaCampaign, customer_name: str) -> str:
	if row.project and frappe.db.exists("Project", row.project):
		return row.project
	project_name = f"Remolda Cycle - {row.company_name}"
	existing = frappe.db.get_value("Project", {"project_name": project_name}, "name")
	if existing:
		return existing

	doc = frappe.get_doc(
		{
			"doctype": "Project",
			"project_name": project_name,
			"status": "Open",
			"project_type": "External",
			"percent_complete_method": "Task Completion",
			"priority": "Medium",
			"is_active": "Yes",
			"expected_start_date": now_datetime().date(),
			"expected_end_date": add_days(now_datetime().date(), 90),
			"company": campaign.company,
			"customer": customer_name,
			"notes": (
				f"Remolda Cycle delivery for {row.company_name}. Phases: Audit, Strategy, Implement, "
				f"Empower, Evolve."
			),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_sales_order(row, campaign: RemoldaCampaign, customer_name: str) -> str:
	if getattr(row, "sales_order", None) and frappe.db.exists("Sales Order", row.sales_order):
		return row.sales_order
	existing = frappe.db.get_value("Sales Order", {"customer": customer_name, "po_no": row.deal}, "name")
	if existing:
		return existing

	service_item = ensure_remolda_service_item(campaign, row)
	selling_price_list = get_default_selling_price_list()
	default_currency = (
		frappe.db.get_value("Price List", selling_price_list, "currency")
		or frappe.db.get_value("Company", campaign.company, "default_currency")
		or "CAD"
	)
	rate = get_default_offer_amount(row)
	quotation_item = None
	if getattr(row, "quotation", None) and frappe.db.exists("Quotation", row.quotation):
		quotation_item = frappe.db.get_value(
			"Quotation Item", {"parent": row.quotation, "item_code": service_item}, "name"
		)

	item_row = {
		"item_code": service_item,
		"item_name": campaign.service_offer,
		"description": row.proposal_body or f"{campaign.service_offer} for {row.company_name}",
		"qty": 1,
		"uom": frappe.db.get_value("Item", service_item, "stock_uom") or "Nos",
		"delivery_date": add_days(now_datetime().date(), 14),
		"rate": rate,
	}
	if getattr(row, "quotation", None):
		item_row["prevdoc_docname"] = row.quotation
	if quotation_item:
		item_row["quotation_item"] = quotation_item

	doc = frappe.get_doc(
		{
			"doctype": "Sales Order",
			"customer": customer_name,
			"company": campaign.company,
			"transaction_date": now_datetime().date(),
			"delivery_date": add_days(now_datetime().date(), 14),
			"order_type": "Sales",
			"territory": pick_territory(campaign),
			"currency": default_currency,
			"selling_price_list": selling_price_list,
			"po_no": row.deal or f"Remolda-{row.company_name}",
			"items": [item_row],
		}
	)
	doc.insert(ignore_permissions=True)
	add_sales_artifact_comment(row, "Sales Order", doc.name)
	return doc.name


def ensure_project_task(
	project_name: str, subject: str, company: str, description: str = "", days_to_due: int = 7
) -> str:
	existing = frappe.db.get_value("Task", {"project": project_name, "subject": subject}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"project": project_name,
			"status": "Open",
			"priority": "Medium",
			"description": description,
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), days_to_due),
			"company": company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_research_task(row, campaign: RemoldaCampaign) -> str:
	if getattr(row, "research_task", None) and frappe.db.exists("Task", row.research_task):
		task_name = row.research_task
	elif (existing := frappe.db.get_value("Task", {"subject": f"Research contact path for {row.company_name}"}, "name")):
		task_name = existing
	else:
		task_name = ""
	subject = f"Research contact path for {row.company_name}"
	if (row.source_channel or "") in {"LinkedIn", "Facebook"}:
		subject = f"Social outreach and contact path for {row.company_name}"
		existing_social = frappe.db.get_value("Task", {"subject": subject}, "name")
		task_name = existing_social or task_name
	description = (
		f"Prospect needs contact recovery.\n\n"
		f"Company: {row.company_name}\n"
		f"Website: {row.website or 'n/a'}\n"
		f"Phone: {row.phone or 'n/a'}\n"
		f"Priority: {row.priority_tier or 'C'} / ICP {row.icp_score or 0}\n"
		f"Service fit: {row.service_fit or campaign.service_offer}\n"
		f"Gap: {row.contact_gap_status or 'Needs Research'}\n"
	)
	if (row.source_channel or "") in {"LinkedIn", "Facebook"}:
		description += (
			f"Source channel: {row.source_channel}\n"
			f"Profile: {row.source_profile_url or row.source_url or 'n/a'}\n\n"
			f"Recommended DM draft:\n{row.social_outreach_body or build_social_outreach_body(campaign, row)}\n\n"
			f"Goal: send a direct social message, identify the decision-maker, and update the campaign row with any reply path."
		)
	else:
		description += "\nGoal: find decision-maker email or alternate outreach path and update the campaign row."
	if task_name:
		doc = frappe.get_doc("Task", task_name)
		doc.subject = subject
		doc.description = description
		doc.priority = "High" if row.priority_tier == "A" else "Medium"
		save_doc(doc)
		return doc.name
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"status": "Open",
			"priority": "High" if row.priority_tier == "A" else "Medium",
			"description": description,
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), 2),
			"company": campaign.company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def build_social_outreach_body(campaign: RemoldaCampaign, row) -> str:
	profile = row.source_profile_url or row.source_url or "n/a"
	channel = row.source_channel or "Social"
	pain = row.pain_hypothesis or "dispatching, quoting, and service coordination"
	return (
		f"Hi {row.company_name},\n\n"
		f"I came across your {channel} presence while mapping HVAC operators in {row.location or campaign.target_city}. "
		f"We help HVAC teams identify where AI can reduce admin load around {pain}.\n\n"
		f"Remolda's entry offer is a focused HVAC AI Workflow Audit. We usually look at intake, dispatch, quoting, after-hours lead capture, and follow-up, then turn that into a practical automation roadmap.\n\n"
		f"If it makes sense, I can send a short audit outline tailored to your operation.\n\n"
		f"Best,\nRemolda\n"
		f"Profile source: {profile}"
	)


def ensure_social_outreach_task(row, campaign: RemoldaCampaign) -> str:
	if getattr(row, "social_outreach_task", None) and frappe.db.exists("Task", row.social_outreach_task):
		task_name = row.social_outreach_task
	else:
		subject = f"Send {row.source_channel or 'social'} outreach to {row.company_name}"
		task_name = frappe.db.get_value("Task", {"subject": subject}, "name")
	if task_name:
		frappe.db.set_value(
			"Task",
			task_name,
			{
				"description": (
			f"Prospect needs direct {row.source_channel or 'social'} outreach.\n\n"
			f"Company: {row.company_name}\n"
			f"Profile: {row.source_profile_url or row.source_url or 'n/a'}\n"
			f"Lead: {row.lead or 'n/a'}\n"
			f"Deal: {row.deal or 'n/a'}\n"
			f"Priority: {row.priority_tier or 'C'} / ICP {row.icp_score or 0}\n"
			f"Gap: {row.contact_gap_status or 'Needs Decision Maker'}\n\n"
			f"DM draft:\n{row.social_outreach_body or build_social_outreach_body(campaign, row)}"
				),
				"priority": "High" if row.priority_tier == "A" else "Medium",
			},
			update_modified=True,
		)
		return task_name

	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": f"Send {row.source_channel or 'social'} outreach to {row.company_name}",
			"status": "Open",
			"priority": "High" if row.priority_tier == "A" else "Medium",
			"description": (
				f"Prospect needs direct {row.source_channel or 'social'} outreach.\n\n"
				f"Company: {row.company_name}\n"
				f"Profile: {row.source_profile_url or row.source_url or 'n/a'}\n"
				f"Lead: {row.lead or 'n/a'}\n"
				f"Deal: {row.deal or 'n/a'}\n"
				f"Priority: {row.priority_tier or 'C'} / ICP {row.icp_score or 0}\n"
				f"Gap: {row.contact_gap_status or 'Needs Decision Maker'}\n\n"
				f"DM draft:\n{row.social_outreach_body or build_social_outreach_body(campaign, row)}"
			),
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), 2),
			"company": campaign.company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_social_follow_up_task(row, campaign: RemoldaCampaign) -> str:
	subject = f"Follow up on {row.source_channel or 'social'} outreach to {row.company_name}"
	if getattr(row, "social_follow_up_task", None) and frappe.db.exists("Task", row.social_follow_up_task):
		task_name = row.social_follow_up_task
	else:
		task_name = frappe.db.get_value("Task", {"subject": subject}, "name")
	description = (
		f"Social follow-up is due.\n\n"
		f"Company: {row.company_name}\n"
		f"Channel: {row.source_channel or 'Social'}\n"
		f"Profile: {row.source_profile_url or row.source_url or 'n/a'}\n"
		f"Lead: {row.lead or 'n/a'}\n"
		f"Deal: {row.deal or 'n/a'}\n"
		f"Last contact: {row.last_contact_on or 'n/a'}\n"
		f"Next action was due: {row.next_action_on or 'n/a'}\n\n"
		f"Recommended next step: {row.social_next_step or 'Send follow-up DM'}\n\n"
		f"Use the original social task and DM draft as context."
	)
	if task_name:
		frappe.db.set_value(
			"Task",
			task_name,
			{"description": description, "priority": "High"},
			update_modified=True,
		)
		return task_name
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"status": "Open",
			"priority": "High",
			"description": description,
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), 1),
			"company": campaign.company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_email_handoff(campaign: RemoldaCampaign, row) -> str:
	subject = f"Launch email outreach to {row.company_name}"
	task_name = getattr(row, "email_handoff_task", None) if getattr(row, "email_handoff_task", None) and frappe.db.exists("Task", row.email_handoff_task) else None
	if not task_name:
		task_name = frappe.db.get_value("Task", {"subject": subject}, "name")
	if not row.outreach_subject or not row.outreach_body:
		candidate = ProspectCandidate(
			company_name=row.company_name,
			website=row.website or "",
			source_url=row.source_url or row.website or "",
			source_query=row.source_query or "",
			source_channel=row.source_channel or "Manual Seed",
			source_profile_url=row.source_profile_url or "",
			location=row.location or campaign.target_city,
			email=row.email or "",
			phone=row.phone or "",
			summary=row.summary or "",
			personalization_notes=row.personalization_notes or "",
			pain_hypothesis=row.pain_hypothesis or "",
		)
		draft = draft_outreach(candidate, campaign)
		row.outreach_subject = draft.get("subject", "")
		row.outreach_body = draft.get("body", "")
		row.personalization_notes = draft.get("personalization_notes", "") or row.personalization_notes
		row.pain_hypothesis = draft.get("pain_hypothesis", "") or row.pain_hypothesis
	description = (
		f"Decision-maker email is available and the prospect is ready to move from social discovery into email outreach.\n\n"
		f"Company: {row.company_name}\n"
		f"Email: {row.email}\n"
		f"Phone: {row.phone or 'n/a'}\n"
		f"Source channel: {row.source_channel or 'n/a'}\n"
		f"Profile: {row.source_profile_url or row.source_url or 'n/a'}\n\n"
		f"Recommended next step: {row.social_next_step or 'Review or send email outreach'}\n\n"
		f"Suggested subject:\n{row.outreach_subject or 'n/a'}\n\n"
		f"Suggested body:\n{row.outreach_body or 'n/a'}"
	)
	if task_name:
		frappe.db.set_value("Task", task_name, {"description": description, "priority": "High"}, update_modified=True)
		return task_name
	doc = frappe.get_doc(
		{
			"doctype": "Task",
			"subject": subject,
			"status": "Open",
			"priority": "High",
			"description": description,
			"exp_start_date": now_datetime(),
			"exp_end_date": add_days(now_datetime(), 1),
			"company": campaign.company,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_support_issue(row, campaign: RemoldaCampaign, customer_name: str, project_name: str) -> str:
	if row.support_issue and frappe.db.exists("Issue", row.support_issue):
		return row.support_issue
	subject = f"Remolda Support Desk - {row.company_name}"
	existing = frappe.db.get_value("Issue", {"subject": subject}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Issue",
			"subject": subject,
			"customer": customer_name,
			"customer_name": row.company_name,
			"project": project_name,
			"company": campaign.company,
			"status": "Open",
			"priority": "Medium",
			"issue_type": frappe.db.get_value("Issue Type", {}, "name"),
			"description": (
				f"Persistent support desk for {row.company_name}. Use this to track adoption blockers, "
				f"training needs, and expansion signals after kickoff."
			),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def process_post_sale_motion(campaign: RemoldaCampaign, row, logs: list[str]) -> None:
	if not row.project or not frappe.db.exists("Project", row.project):
		return
	project = frappe.get_doc("Project", row.project)

	if float(project.percent_complete or 0) >= 80:
		row.delivery_status = "Evolve Active"
		row.support_status = "Expansion Signal"
		if not row.upsell_deal:
			row.upsell_deal = ensure_upsell_deal(row, campaign)
			row.upsell_status = "Deal Opened"
			row.status = "Upsell Opened"
			logs.append(f"Upsell deal opened for {row.company_name}: {row.upsell_deal}.")
	elif float(project.percent_complete or 0) >= 60:
		row.delivery_status = "Empower Active"
		row.support_status = row.support_status or "Monitoring"
		row.upsell_status = row.upsell_status or "Monitoring"
	elif float(project.percent_complete or 0) >= 35:
		row.delivery_status = "Implementation Active"
	elif float(project.percent_complete or 0) >= 15:
		row.delivery_status = "Strategy Active"
	else:
		row.delivery_status = row.delivery_status or "Audit Active"


def ensure_upsell_deal(row, campaign: RemoldaCampaign) -> str:
	if row.upsell_deal and frappe.db.exists("Opportunity", row.upsell_deal):
		return row.upsell_deal
	existing = frappe.db.get_value(
		"Opportunity",
		{
			"opportunity_from": "Customer",
			"party_name": row.customer,
			"opportunity_type": "HVAC AI Support & Optimization",
		},
		"name",
	)
	if existing:
		return existing

	default_currency = frappe.db.get_value("Company", campaign.company, "default_currency") or "CAD"
	doc = frappe.get_doc(
		{
			"doctype": "Opportunity",
			"opportunity_from": "Customer",
			"party_name": row.customer,
			"customer_name": row.company_name,
			"status": "Open",
			"opportunity_type": "HVAC AI Support & Optimization",
			"sales_stage": "Implementation Proposal",
			"company": campaign.company,
			"transaction_date": now_datetime().date(),
			"expected_closing": add_days(now_datetime().date(), 30),
			"currency": default_currency,
			"opportunity_amount": 5000,
			"probability": 55,
			"industry": "HVAC Services",
			"territory": pick_territory(campaign),
			"title": f"{row.company_name} - HVAC AI Support & Optimization",
			"contact_email": row.email,
			"phone": row.phone,
			"website": row.website,
			"city": campaign.target_city,
			"state": campaign.target_region,
			"country": campaign.target_country,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def mark_deal_closed(row, reason: str, logs: list[str]) -> None:
	if not row.deal:
		return
	doc = frappe.get_doc("Opportunity", row.deal)
	if reason == "Not Interested":
		doc.status = "Lost"
		doc.order_lost_reason = "Prospect replied not interested."
		row.lifecycle_stage = "Lost"
	elif reason == "Unresponsive":
		doc.status = "Lost"
		doc.order_lost_reason = "No reply after automated outreach sequence."
		row.lifecycle_stage = "Lost"
	save_doc(doc)
	logs.append(f"Closed deal {row.deal} as {reason}.")
