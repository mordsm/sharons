# Implementation Status

## Last Completed
- Executive Overview and task pages are verified. Draft Next Spec and Plan Next Build say why they cannot run, including when a spec or contract exists but is not READY. Review Evidence opens the task and says the work was not accepted. A finished task says it is finished and offers no further status move.
- Executive Overview Create Brief opens the new brief, and Open Review opens the finance page. Open Review stays available when records are already marked needs review.
- Marketing phase 2 records a content calendar, an experiment register, and a claims review. Calendar acknowledgement does not publish or send. Experiments cannot spend or store a significance claim. A claim stays unsupported until an evidence note is supplied.
- The marketing agent is operative. It is seeded, the runner is on, and one assigned Mental Trainer task completed a draft run with publishing and spending off. The task remains `DELIVERED_UNVERIFIED` until a person verifies it.
- Mental Trainer launch review is on the weekly report. It lists what to approve or hold, that no O1 task is blocked, and the open offer, price, and payment questions. A 30-day Israel marketing draft does not publish or spend. The task `Record the Mental Trainer launch decision list` is `COMPLETED` with verified evidence.
- Marketing Manager is a draft-only agent. It creates strategy, audience, positioning, campaign brief, and decision-bundle artifacts, reviews them by version, and can hand a milestone proposal to Project Manager. Publishing, sending, CRM access, and ad spending stay off. Page: `/marketing/`.
- Google accepted a new read-only Gmail refresh token. It is stored in `.env` as `SHARONS_GMAIL_REFRESH_TOKEN`, with the existing OAuth client id and secret. A live read-only fetch ingested 3 messages. Sending stays off.
- Provider HTTPS calls run in a separate Python process because the uv Python build on this machine aborts on TLS.
- Registered secret references `gmail-access`, `gmail-refresh`, and `github-issues`. Values stay in environment variables. The local Gmail sync config points at the Gmail references.
- Gmail read-only fetch can refresh an access token from `SHARONS_GMAIL_REFRESH_TOKEN` plus `SHARONS_GMAIL_CLIENT_ID` and `SHARONS_GMAIL_CLIENT_SECRET`. If refresh is not configured, it still uses `SHARONS_GMAIL_TOKEN`.
- `POST /api/v1/agents/execute/` runs an assigned Product Manager, Project Manager, or Executive Assistant task internally, records artifact evidence, and moves the task `ASSIGNED` → `IN_PROGRESS` → `DELIVERED_UNVERIFIED`. `POST /api/v1/agents/invoke/` is unchanged and still only records a started run.
- Added an approval-backed GitHub adapter whose only action is creating an issue on a write-approved `github_issues` connection.
- Added a secret-reference store. It records an environment variable name and never stores the token.
- Approved read-only Gmail, Outlook, and calendar connectors can fetch when that secret is set. Dry-run still does not contact a provider. Sending and scheduling stay off.
- Added internal user-research contracts, interviews, findings, and open questions bound to a product spec. Customer contact and direct contact channels are refused.
- Linked product milestones to an active objective that is already linked to the same project.
- Added internal competitive-analysis drafts with review, still with no customer contact and no external write.
- Project Manager milestone proposals can be accepted or dismissed once.
- Blocker reviews now open either an unblock approval request or an internal follow-up task. They do not change the blocked task by themselves.
- Execution reviews create draft follow-up tasks for blocker review and delivery verification.
- Added a project coordination page at `/project-manager/`.

## Current State
- Sharons remains an internal orchestration/proposal system.
- Email sending, calendar scheduling, repository writes, and publishing remain disabled.
- GitHub access is limited to creating one approved issue. Read-only provider fetch runs only when an environment variable named by a secret reference is set.
- Gmail refresh uses the Google token endpoint and keeps the new access token in memory for that fetch. Send and calendar scheduling stay off.
- The agent runner does not send email, schedule events, create GitHub issues, or write to a repository.
- Provider sync configs still cannot store OAuth tokens or secrets.
- Local Postgres for this workspace is running through Docker with dynamic host-port mapping. Current `.env` points at the assigned port from `docker compose port postgres 5432` (currently `53134`).

## Next Step
- A live GitHub issue still needs an approval bound to one exact payload. `SHARONS_GITHUB_TOKEN` is present. Do not create an issue until the title, body, and repository are chosen.
- Read-only marketing analytics only after a scoped connector exists. Do not add publishing or ad spending.

## Blockers
- Outlook and calendar still have no live credentials. Gmail refresh is configured for read-only fetch. Sending and scheduling stay off.
- A GitHub issue is not created until a specific approval is executed.

## Verification
- `uv run pytest core\tests\test_executive_dashboard.py operations\tests\test_task_dashboard.py -q` passed: 21 passed. Postgres had stopped; `docker compose up -d postgres` started it on `127.0.0.1:53134`, and `.env` was pointed at that port. `.env` is not committed.
- Browser check of `http://127.0.0.1:8765/`: Product Manager and Developer showed that their records are completed, cancelled, or delivered, so Draft Next Spec and Plan Next Build stayed off. Review Evidence opened `Draft the 30-day Israel Mental Trainer launch plan` and said QA did not accept it. The task stayed `DELIVERED_UNVERIFIED`, and the status choices were Cancelled, In Progress, and Verifying. The completed task `Record the Mental Trainer launch decision list` said it is finished and had no status move.
- `uv run pytest marketing\tests\test_marketing_api.py operations\tests\test_agent_runner.py -q` passed: 20 passed. This covers the content calendar, experiment register, and claims review.
- Local Postgres was down. `docker compose up -d postgres` started it on `127.0.0.1:63870`, and `.env` was pointed at that port. `.env` is not committed.
- `uv run python manage.py migrate` applied `marketing.0002_content_calendar_experiment_claims` and `product.0007_pricingexperimentbrief`.
- Browser check of `http://127.0.0.1:8765/marketing/`: added a calendar draft, registered an experiment, registered a claim, and acknowledged that claim as unsupported. Publish, send, and spend stayed off.
- `uv run python manage.py check` passed with no issues.
- `uv run pytest core\tests\test_cos_objective_health_api.py product\tests\test_product_spec_contract_api.py executive_assistant\tests\test_executive_brief_api.py -q` was attempted and blocked during test database setup by PostgreSQL authentication failure.
- After moving the project Postgres container to dynamic port mapping and updating `.env`, `uv run pytest core\tests\test_cos_objective_health_api.py product\tests\test_product_spec_contract_api.py executive_assistant\tests\test_executive_brief_api.py -q` passed: 94 passed.
- `uv run pytest product\tests\test_product_spec_contract_api.py -q` passed: 19 passed.
- `uv run pytest operations\tests\test_agent_runner.py executive_assistant\tests\test_gmail_refresh.py executive_assistant\tests\test_read_only_fetch.py -q` passed: 9 passed.
- `uv run python manage.py migrate governance` applied `governance.0011_secretreference_oauth_refresh`.
- `uv run python manage.py register_connector_secrets` registered the three references and the Gmail sync config.
- Restarted `manage.py runserver` on `127.0.0.1:8765`. `POST /api/v1/executive-assistant/provider-sync-configs/24ed49e9-2de6-40c1-984c-216ef9f8c17d/fetch/` returned 200: 3 messages ingested, `will_send_email` false, `will_schedule_calendar` false.
- `uv run pytest executive_assistant\tests\test_gmail_refresh.py executive_assistant\tests\test_read_only_fetch.py -q` passed: 6 passed.
- `uv run pytest marketing\tests\test_marketing_api.py operations\tests\test_agent_runner.py -q` passed: 15 passed.
- `uv run pytest core\tests\test_weekly_review.py -q` passed: 4 passed.
- `uv run pytest operations\tests\test_agent_runner.py::test_runner_creates_a_marketing_draft_without_publishing marketing\tests\test_marketing_api.py::test_market_share_without_a_source_creates_no_figure marketing\tests\test_marketing_api.py::test_marketing_page_shows_disabled_connectors -q` passed: 3 passed.
- Live `execute_assigned_agent` for marketing returned `COMPLETED`, task status `DELIVERED_UNVERIFIED`, publish false, spend false. `/marketing/` shows Registered yes, runner On, last run COMPLETED.
- `uv run python manage.py prepare_o1_launch_review` recorded the research questions, execution review, marketing draft, and completed the launch-list task.
- `GET /api/v1/reports/weekly/` returned O1 launch decisions: 5 to approve or hold, 0 blocked, 5 assumptions.
- `uv run python manage.py migrate marketing` applied `marketing.0001_initial`.
- Browser check of `http://127.0.0.1:8765/marketing/`: the page shows connectors as not connected, and submitting a draft plan listed that objective under recent requests.

## Important Decisions
- Preserve safety boundary: no external provider contact and no external actions without approval-backed adapters.
- Prefer derived operational artifacts before adding new persistence models.
