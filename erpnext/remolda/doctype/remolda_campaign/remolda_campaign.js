frappe.ui.form.on("Remolda Campaign", {
	async refresh(frm) {
		frm.set_df_property(
			"seed_prospects",
			"description",
			__("One per line. Use raw URL/email or `company|url|email|phone|source channel|profile url`.")
		);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Queue Selected"), async () => {
				await run_social_action(frm, "queue_social_outreach", __("Queueing social outreach..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Mark DM Sent"), async () => {
				await run_social_action(frm, "mark_social_dm_sent", __("Marking social DMs as sent..."));
			}, __("Social Queue"));
			frm.add_custom_button(__("Mark Not Interested"), async () => {
				await run_social_action(frm, "mark_social_not_interested", __("Marking prospects as not interested..."));
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
