# Catalog update automation

How `kyuhachi-data` keeps the published onsen catalog in sync with 88onsen.com over time,
with the operator acting as a pure **approver** working only through GitHub.

The pipeline splits into halves with different automation profiles — detection is cheap,
auth-free, and judgement-free; publishing needs Firestore credentials and judgement. So we
automate detection, hand the judgement step to a human-run Claude session, and gate the
live write behind a merge + an environment approval.

```
 monthly cron (catalog-detect, no secrets)
   sample → detect → material change?  ──no──► silent no-op
                              │ yes
   open/refresh a `catalog-drift` issue with a ready-to-paste prep prompt
                              │
   operator launches a Claude session (subscription), pastes the prompt
                              ▼
   session: detect → draft decisions.json → recurate hours → mint ids
            → dry-runs → opens a PR labelled `catalog-publish` (NO --commit)
                              │
   catalog-dry-run check (WIF read-only) posts the authoritative Firestore diff
                              ▼
   operator reviews the PR → MERGE
                              ▼
   catalog-publish: dry_run job → [production environment approval] → publish job
        detect → apply --commit → backfill --commit → promote --commit → tests
        → bot-pushes the advanced snapshot.db baseline to master
```

## The three workflows

| Workflow | Trigger | Auth | What it does |
|---|---|---|---|
| `catalog-detect.yml` | monthly cron + manual | **none** | scrape + diff; opens/refreshes the `catalog-drift` nudge on material change; alerts via `catalog-pipeline-broken` on selector drift / blocked egress / unreachable map seed |
| `catalog-dry-run.yml` | PR touching `decisions.json` / `hours_curated.json` / `onsen-id-map.json` | WIF **read-only** | runs the publish dry-runs + tests, posts the live-Firestore diff as a sticky PR comment |
| `catalog-publish.yml` | push to `master` on those paths + manual | WIF **read-only** (preview) then **write** (gated) | dry-run preview → `production` approval → `apply`/`backfill`/`promote --commit` → push advanced `snapshot.db` |

`catalog-detect` works the moment this is merged — **no setup required**. The other two are
**inert until Workload Identity Federation is configured** (each job is guarded by
`if: vars.WIF_PROVIDER != ''`).

## Operator runbook

1. A `catalog-drift` issue appears (only when something material changed).
2. Open a Claude Code session **on this repo, on your Claude subscription** (not the
   metered `@claude` action), and paste the prompt from the issue body.
3. The session prepares a PR labelled `catalog-publish` and stops — it never writes Firestore.
4. Review the PR. The `catalog-dry-run` comment shows exactly what will change. Tick the
   checklist (identity calls, ADDED-onsen flags) and **merge**.
5. The `catalog-publish` run pauses at the **production** environment — open it, read the
   dry-run preview in the run summary, and **approve**. It writes Firestore and pushes the
   advanced baseline back to `master`.

New onsens are minted + baselined automatically, but creating their live Firestore doc is
still manual (pending the `apply.py add` action); the publish run emits a `::warning::`
listing them. Challenge-pool membership always lives in the app repo.

## One-time setup (Workload Identity Federation)

Needs GCP access (`gcloud` or the Cloud Console) once. Project: `kyuhachi-fddcc`,
repo: `PetrCala/kyuhachi-data`.

```bash
PROJECT=kyuhachi-fddcc
REPO=PetrCala/kyuhachi-data
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')

gcloud services enable iamcredentials.googleapis.com sts.googleapis.com --project "$PROJECT"

# Pool + GitHub OIDC provider, locked to this repo. Map ref + environment for tight binding.
gcloud iam workload-identity-pools create github --project "$PROJECT" \
  --location=global --display-name="GitHub Actions"
gcloud iam workload-identity-pools providers create-oidc github --project "$PROJECT" \
  --location=global --workload-identity-pool=github --display-name="GitHub OIDC" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.environment=assertion.environment" \
  --attribute-condition="assertion.repository=='${REPO}'"

# Two service accounts: read-only for previews/PR checks, publish for the gated write.
gcloud iam service-accounts create catalog-readonly --project "$PROJECT" --display-name="Catalog CI read-only"
gcloud iam service-accounts create catalog-publish  --project "$PROJECT" --display-name="Catalog CI publish"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:catalog-readonly@${PROJECT}.iam.gserviceaccount.com" --role="roles/datastore.viewer"
gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:catalog-publish@${PROJECT}.iam.gserviceaccount.com" --role="roles/datastore.user"

POOL="projects/${NUM}/locations/global/workloadIdentityPools/github"
# read-only: any workflow in the repo may impersonate it.
gcloud iam service-accounts add-iam-policy-binding "catalog-readonly@${PROJECT}.iam.gserviceaccount.com" \
  --project "$PROJECT" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.repository/${REPO}"
# publish: only the `production` environment may impersonate it (GitHub also gates approval).
gcloud iam service-accounts add-iam-policy-binding "catalog-publish@${PROJECT}.iam.gserviceaccount.com" \
  --project "$PROJECT" --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${POOL}/attribute.environment/production"
```

Then, on the GitHub side:

```bash
# Repo VARIABLES (not secrets — none of these are sensitive).
gh variable set WIF_PROVIDER --repo "$REPO" --body "projects/${NUM}/locations/global/workloadIdentityPools/github/providers/github"
gh variable set SA_READONLY  --repo "$REPO" --body "catalog-readonly@${PROJECT}.iam.gserviceaccount.com"
gh variable set SA_PUBLISH   --repo "$REPO" --body "catalog-publish@${PROJECT}.iam.gserviceaccount.com"
```

- **Create the `production` environment** (repo Settings → Environments → New environment
  → `production`) and add yourself under **Required reviewers**. This is the approval gate.
- **Branch protection:** the publish run pushes the advanced `snapshot.db` to `master`. If
  `master` is protected, allow the GitHub Actions bot to bypass, or swap the push to use a
  PAT with bypass. The push uses `[skip ci]` and `snapshot.db` is outside the trigger paths,
  so it never re-triggers the workflow.

### Smoke test (the one real integration risk)

The publisher scripts mint a token with `gcloud auth application-default print-access-token`.
Before relying on the gated write, confirm that resolves under WIF — open a PR editing
`data/hours_curated.json` and check that `catalog-dry-run` authenticates and posts a diff.
If token minting fails under WIF, the fix is a small shim that reads the ADC credential file
(`$GOOGLE_APPLICATION_CREDENTIALS`) instead of shelling out to `gcloud`.

## Labels

- `catalog-drift` — a prep session is needed (the monthly nudge; auto-created/refreshed).
- `catalog-pipeline-broken` — detection itself is failing (auto-created on alert).
- `catalog-publish` — marks a prep PR; merging it is the publish trigger.

## Rollback

`snapshot.db` is git-tracked, so a bad baseline advance is `git revert`-able. Firestore
writes are surgical (field-level PATCH) and bump `catalog_meta/current.version`; re-run a
corrected prep → publish to fix forward. Onsen docs are never deleted (retire = `isActive:false`).
