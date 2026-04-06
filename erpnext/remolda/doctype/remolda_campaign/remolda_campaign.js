frappe.ui.form.on("Remolda Campaign", {
	async refresh(frm) {
		frm.set_df_property(
			"seed_prospects",
			"description",
			__("One per line. Use raw URL/email or `company|url|email|phone|source channel|profile url`.")
		);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Show All"), async () => {
				apply_prospect_filter(frm, "all");
			}, __("Prospect Views"));
			frm.add_custom_button(__("Queued Social"), async () => {
				apply_prospect_filter(frm, "queued_social");
			}, __("Prospect Views"));
			frm.add_custom_button(__("DM Sent"), async () => {
				apply_prospect_filter(frm, "dm_sent");
			}, __("Prospect Views"));
			frm.add_custom_button(__("Follow-Up Due"), async () => {
				apply_prospect_filter(frm, "follow_up_due");
			}, __("Prospect Views"));
			frm.add_custom_button(__("Social Replied"), async () => {
				apply_prospect_filter(frm, "social_replied");
			}, __("Prospect Views"));
			frm.add_custom_button(__("Ready For Email"), async () => {
				apply_prospect_filter(frm, "ready_for_email");
			}, __("Prospect Views"));
			frm.add_custom_button(__("Queue Selected"), async () => {
				await run_social_action(frm, "queue_social_outreach", __("Queueing social outreach..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Mark DM Sent"), async () => {
				await run_social_action(frm, "mark_social_dm_sent", __("Marking social DMs as sent..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Mark Not Interested"), async () => {
				await run_social_action(frm, "mark_social_not_interested", __("Marking prospects as not interested..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Prepare Email Handoff"), async () => {
				await run_social_action(frm, "prepare_email_handoff", __("Preparing email handoff..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Send Email Now"), async () => {
				await run_social_action(frm, "send_email_now", __("Sending email outreach..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Decision Maker Found"), async () => {
				const selected = get_selected_prospect_rows(frm);
				if (selected.length !== 1) {
					frappe.msgprint(__("Select exactly one prospect row for this action."));
					return;
				}
				const values = await promptValues(
					[
						{ fieldname: "email", fieldtype: "Data", label: __("Email"), reqd: 1 },
						{ fieldname: "phone", fieldtype: "Data", label: __("Phone") },
						{ fieldname: "contact_name", fieldtype: "Data", label: __("Contact Name") },
					],
					__("Decision Maker Found"),
					__("Save")
				);
				if (!values) return;
				await frappe.call({
					method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.mark_decision_maker_found",
					args: { name: frm.doc.name, row_name: selected[0].name, ...values },
					freeze: true,
					freeze_message: __("Saving decision-maker details..."),
				});
				await frm.reload_doc();
			}, __("Social Queue"));
			frm.add_custom_button(__("Log Social Reply"), async () => {
				const selected = get_selected_prospect_rows(frm);
				if (selected.length !== 1) {
					frappe.msgprint(__("Select exactly one prospect row for this action."));
					return;
				}
				const values = await promptValues(
					[{ fieldname: "reply_text", fieldtype: "Small Text", label: __("Reply Text"), reqd: 1 }],
					__("Log Social Reply"),
					__("Save")
				);
				if (!values) return;
				await frappe.call({
					method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.log_social_reply",
					args: { name: frm.doc.name, row_name: selected[0].name, reply_text: values.reply_text },
					freeze: true,
					freeze_message: __("Logging social reply..."),
				});
				await frm.reload_doc();
			}, __("Social Queue"));
			frm.add_custom_button(__("Ingest Seed Prospects"), async () => {
				await frappe.call({
					method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.ingest_seed_prospects",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Ingesting seeded LinkedIn, Facebook, and manual prospects..."),
				});
				await frm.reload_doc();
			});
			frm.add_custom_button(__("Run Autonomous Cycle"), async () => {
				await frappe.call({
					method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.run_campaign",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Running Remolda campaign..."),
				});
				await frm.reload_doc();
			});
			frm.add_custom_button(__("Process Workflow"), async () => {
				await frappe.call({
					method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.process_campaign_workflow",
					args: { name: frm.doc.name },
					freeze: true,
					freeze_message: __("Processing outreach, follow-ups, and proposals..."),
				});
				await frm.reload_doc();
			});
			frm.add_custom_button(__("Refresh Operator Console"), async () => {
				await render_operator_snapshot(frm);
			});
			await render_operator_snapshot(frm);
		}
	},
});

async function render_operator_snapshot(frm) {
	const wrapper = frm.get_field("operator_snapshot")?.$wrapper;
	if (!wrapper) return;
	wrapper.html("<div class='text-muted'>Loading Remolda operator snapshot...</div>");
	const response = await frappe.call({
		method: "erpnext.remolda.doctype.remolda_campaign.remolda_campaign.get_operator_snapshot",
		args: { name: frm.doc.name },
		freeze: false,
	});
	wrapper.html(response.message?.html || "<div class='text-muted'>No operator snapshot.</div>");
}

function get_selected_prospect_rows(frm) {
	const grid = frm.fields_dict.prospects?.grid;
	if (!grid?.get_selected_children) return [];
	return grid.get_selected_children();
}

async function run_social_action(frm, methodName, freezeMessage) {
	const selected = get_selected_prospect_rows(frm);
	if (!selected.length) {
		frappe.msgprint(__("Select one or more prospect rows in the Prospects table first."));
		return;
	}
	await frappe.call({
		method: `erpnext.remolda.doctype.remolda_campaign.remolda_campaign.${methodName}`,
		args: { name: frm.doc.name, row_names: selected.map((row) => row.name) },
		freeze: true,
		freeze_message: freezeMessage,
	});
	await frm.reload_doc();
}

function promptValues(fields, title, primaryLabel) {
	return new Promise((resolve) => {
		frappe.prompt(fields, (values) => resolve(values || null), title, primaryLabel);
	});
}

function apply_prospect_filter(frm, mode) {
	const grid = frm.fields_dict.prospects?.grid;
	if (!grid?.grid_rows?.length) {
		frappe.show_alert({ message: __("Prospect rows are not loaded yet."), indicator: "orange" });
		return;
	}

	let visibleCount = 0;
	for (const gridRow of grid.grid_rows) {
		const row = gridRow.doc || {};
		const show = should_show_prospect_row(row, mode);
		if (gridRow.wrapper) {
			gridRow.wrapper.style.display = show ? "" : "none";
		}
		if (show) visibleCount += 1;
	}

	const labels = {
		all: __("All Prospects"),
		queued_social: __("Queued Social"),
		dm_sent: __("DM Sent Waiting"),
		follow_up_due: __("Follow-Up Due"),
		social_replied: __("Social Replied"),
		ready_for_email: __("Ready For Email Conversion"),
	};
	frappe.show_alert({
		message: __("{0}: {1} rows", [labels[mode] || __("Filtered"), visibleCount]),
		indicator: "blue",
	});
}

function should_show_prospect_row(row, mode) {
	if (mode === "all") return true;

	const sourceChannel = row.source_channel || "";
	const socialStage = row.social_stage || "";
	const isSocial = ["LinkedIn", "Facebook"].includes(sourceChannel);
	if (!isSocial) return false;

	if (mode === "queued_social") return socialStage === "Queued";
	if (mode === "dm_sent") return socialStage === "DM Sent";
	if (mode === "follow_up_due") {
		return socialStage === "DM Sent" && !!row.next_action_on && new Date(row.next_action_on) <= new Date();
	}
	if (mode === "social_replied") return ["Replied", "Interested", "Won", "Not Interested"].includes(socialStage);
	if (mode === "ready_for_email") return socialStage === "Decision Maker Found";
	return true;
}
