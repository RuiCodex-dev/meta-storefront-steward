# Data plan

Written 2026-10-18. **Nothing in this file has been run.** Exports start only after the Official Rules confirm that
building may begin (expected at the kickoff, 2026-10-26 ~17:00 CET). Linear RUI-268.

## 1. Which data we may use, and why

All data comes from **Rui Codex's own apps**, read through the official developer APIs with Rui Codex's own
credentials. We are the controller of this data (GDPR); the reviewers are the data subjects.

| Data | Source | Personal data? | Lawful basis and limits |
|---|---|---|---|
| Review text, star rating, language, device, app version, dates | Google Play (API + monthly CSV), App Store Connect API | yes: reviewer display name / nickname; free text may contain names, e-mails, health or payment details | Legitimate interest (Art. 6(1)(f)): answering users and fixing our apps, which is exactly why reviews exist and why the stores expose them to developers. Used only to operate our own apps. Never sold, never shared, never used to profile individuals |
| Developer replies we already posted | same | no (ours) | style examples |
| Crash and ANR clusters, stack traces | Play Developer Reporting API; ASC diagnostic signatures | normally no; device model and OS only. Stack traces may contain file paths, never user content (check) | operating our apps |
| Releases: version codes, dates, release notes | Play edits/tracks; ASC appStoreVersions | no | |
| Store-review rejection notes | Play policy e-mails and App Review messages to info@ruicodex.com | no (about our apps) | manual import only |
| App screenshots and screen recordings | our own emulator captures and existing store-refresh captures | no (no real user data on screen; test accounts only) | our assets |
| Changelogs | git logs of our app repos, read locally | no | **only commit subjects are used; app source code is never uploaded anywhere** |

Not used: third-party competitors' reviews, scraped data, any data of apps we do not own, Gmail content beyond
messages the owner explicitly exports.

### Store terms

- Google Play: the Developer API gives developers access to their own reviews to read and reply. We use them for that
  purpose and for improving the apps; we do not republish identifiable reviews.
- App Store Connect: customer reviews and responses are provided to the developer of the app. Same use.
- Re-check both terms on day 1 for any clause about sending review content to third-party AI processors; if a clause
  forbids it, triage runs only on the self-hosted open-weights student (Glimmer/Llama on our rented GPU) and Spark sees
  only aggregated, pseudonymised clusters.

### Meta as processor

- Model API calls use **Standard mode only**. Meta's pricing page: in Standard mode "your content is not used to train
  Meta models". **Contributor mode is never used** for anything derived from reviews.
- Check on day 1 whether the Model API offers zero data retention for text models and whether a Data Processing
  Addendum applies to API customers; record the answer in `docs/04-BUILD-PLAN.md` day-1 notes.
- Data minimisation: Spark sees pseudonymised text, rating, language, version and date. No device ids, no reviewer ids,
  no names.

### Sensitive apps (special-category data, GDPR Art. 9)

DietSEM (diet and nutrition) and, if they have Play reviews, Juju (cycle tracker), Serena Care (pill reminder) and
FitLife can receive reviews that mention health. Proposal: include them in triage with an extra local scrub for health
terms, **exclude them from training data, from the gold set shown to any model, and from the demo video.**
Owner decision (see `05-OWNER-DECISIONS.md`).

## 2. Pseudonymisation (runs before any model sees a record)

1. **Identity fields:** `authorName` (Play), `reviewerNickname` (ASC), `reviewId` and any user id are replaced by
   `R-<first 10 hex of HMAC-SHA256(secret, store:app:review_id)>` and `user-<HMAC(...)>`. The secret is generated once
   and stored at `C:\Users\Admin\.ruicodex-keys\storefront-steward\pseudonym.key` (never in the repo).
2. **Free text scrub (local, deterministic):** e-mail addresses, phone numbers, URLs with query strings, order and
   transaction ids (GPA.xxxx, Apple order ids), IBAN/card-like digit runs, @handles, and the reviewer's own display name
   wherever it reappears in the text -> typed placeholders (`[EMAIL]`, `[PHONE]`, `[ORDER_ID]`, `[NAME]`).
   A second pass uses a local multilingual NER (spaCy `xx_ent_wiki_sm`, CPU) for person names in the text.
3. **Re-identification map** (`pseudonym -> store review id`) is kept only in `data/private/reidmap.sqlite` and is
   used by exactly one function: posting an approved reply. Nothing else imports it.
4. **Tests:** a fixture of 40 synthetic reviews in 8 languages with planted PII; the scrubber must remove 100% of
   planted e-mails/phones/order ids and >= 95% of planted names, and must leave a known-clean control text unchanged.
5. **Outbound scan:** every text leaving the machine (model prompt, reply draft, video caption) passes the same
   scanner; a hit blocks the call and is logged.

## 3. Storage, retention and repo hygiene

- `data/raw/` (store exports) and `data/private/` (re-id map) are git-ignored and live on C: in the project folder.
- `data/clean/steward.db` holds pseudonymised records; also git-ignored.
- The repo contains code, docs, label guides and **aggregate** evaluation results only. The frozen test set is stored
  as pseudonymised ids + labels with a committed SHA-256, but its text stays local.
- Retention: raw exports deleted 30 days after the hackathon unless the owner keeps the tool in production; the
  pseudonymised DB is kept for the product.
- Secret scan (gitleaks if installed, otherwise a regex scan for keys, `-----BEGIN`, `client_email`, `AIza`, `sk-`)
  before every commit.

## 4. Volume check (first thing on day 1)

Indie apps may have few written reviews. On day 1 we count, per package: reviews with text in the CSV history, last 7
days via API, and languages. Decision rule for training data:

- >= 3,000 own items with text: train on own data only (teacher-labelled), test on the owner-labelled gold set.
- 800-3,000: add Spark-generated **synthetic** reviews (Standard mode, generated from category descriptions and app
  descriptions, never from real reviews), flagged `synthetic=1`, train-only, max 50% of training data.
- < 800: same plus public app-review corpora **only if** the licence is CC0 or CC-BY and allows ML use (verify the
  exact licence file); otherwise synthetic only. The headline metric always uses our real test set.

## 5. Exact export calls (to run only after the rules allow building)

Credentials, read at runtime and never printed:
- Google Play: the existing service account used by `_publish_ops/publish_play.py`
  (`%USERPROFILE%\.claude\mcp-servers\app-publish-mcp\service-account.json`). Note: it is **not** in
  `.ruicodex-keys`; copy-by-reference only. Scopes needed: `androidpublisher` (reviews, tracks) and
  `playdeveloperreporting` (vitals). For the CSV history the service account needs read access to the
  `pubsite_prod_<developer id>` bucket (Play Console > Users and permissions > the service account > "View app
  information and download bulk reports"). Owner action if missing.
- App Store Connect: the existing API key (env `APP_STORE_KEY_ID`, `APP_STORE_ISSUER_ID`, `APP_STORE_P8_PATH`),
  ES256 JWT, read-only methods during export.

Packages (19 Play apps from the store refresh list): `com.ruicodex.IdleFactoryTycoon`, `com.ruicodex.idledefense`,
`com.ruicodex.starharbor`, `com.ruicodex.koidrift`, `com.ruicodex.lumenloop`, `com.ruicodex.gravity_block_flip`,
`com.altinayselman.standbyclock`, `com.ruicodex.dietsem`, `com.ruicodex.florea`, `com.ruicodex.letslearn`,
`com.everytranslate.app`, `com.ruicodex.pixelcut_pro`, `com.ruicodex.posterboost.ai`, `com.ruicodex.ant_empire`,
`com.ruicodex.candychaos`, `com.ruicodex.luckyballoon`, `com.ruicodex.pullplunder`, `com.ruicodex.quiltvale`,
`com.ruicodex.grandmaskitchen`. iOS app ids come from `appstore-all-in-one-mcp/scripts/ios/apps.json` (16 with an
`ascAppId`).

### 5.1 Google Play

```text
# A. Recent reviews with text (7-day window), all languages, paginated
GET https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{pkg}/reviews
    ?maxResults=100&translationLanguage=en&token={nextPageToken}
#    keep: reviewId, authorName (-> pseudonymise immediately), comments[].userComment
#    {text, originalText, reviewerLanguage, starRating, lastModified, appVersionCode, appVersionName,
#     device, androidOsVersion}, comments[].developerComment {text, lastModified}
#    quota: 200 GET/hour -> sleep 20 s between pages when > 150 calls/hour

# B. Review history: monthly CSV export (UTF-16LE) in the developer bucket
gcloud storage ls  gs://pubsite_prod_{developer_id}/reviews/
gcloud storage cp  gs://pubsite_prod_{developer_id}/reviews/reviews_{pkg}_YYYYMM.csv  data/raw/play_csv/
#    (or google-cloud-storage Python client with the same service account)

# C. Releases: version codes, dates, release notes per track
POST .../applications/{pkg}/edits                      -> editId (read-only use)
GET  .../applications/{pkg}/edits/{editId}/tracks      -> releases[]{name, versionCodes, status, releaseNotes}
DELETE .../applications/{pkg}/edits/{editId}           -> always delete the edit (never commit)
#    respect the store-refresh lock: mkdir locks/play-{pkg}.lock before the edit, remove right after

# D. Vitals (Play Developer Reporting API, scope playdeveloperreporting)
POST https://playdeveloperreporting.googleapis.com/v1beta1/apps/{pkg}/crashRateMetricSet:query
     {timelineSpec:{aggregationPeriod:"DAILY", startTime, endTime}, dimensions:["versionCode"],
      metrics:["crashRate","distinctUsers"]}
POST .../apps/{pkg}/anrRateMetricSet:query             (same shape, metrics ["anrRate","distinctUsers"])
GET  .../apps/{pkg}/errorIssues:search?interval.startTime=...&interval.endTime=...&pageSize=50
GET  .../apps/{pkg}/errorReports:search?filter=errorIssueId={id}&pageSize=10    (sample stack traces)
```

### 5.2 App Store Connect

```text
GET https://api.appstoreconnect.apple.com/v1/apps/{ascAppId}/customerReviews
    ?sort=-createdDate&limit=200&include=response
    -> rating, title, body, reviewerNickname (-> pseudonymise), createdDate, territory, response
GET /v1/apps/{ascAppId}/appStoreVersions?fields[appStoreVersions]=versionString,appStoreState,createdDate,earliestReleaseDate
GET /v1/appStoreVersions/{id}/appStoreVersionLocalizations   -> whatsNew per locale
GET /v1/apps/{ascAppId}/builds?limit=50
GET /v1/builds/{buildId}/diagnosticSignatures                 -> HANGS / DISK_WRITES / LAUNCHES clusters
GET /v1/diagnosticSignatures/{id}/logs                        -> sample logs
```

Rejection notes: the Resolution Center text is not reliably exposed by the API. The owner exports the relevant
App Review messages and Play policy e-mails (copy-paste or .eml) into `data/raw/rejections/`; they contain no user
personal data.

### 5.3 Write calls (only after a human click, never during export)

```text
POST https://androidpublisher.googleapis.com/androidpublisher/v3/applications/{pkg}/reviews/{reviewId}:reply
     {"replyText": "<= 350 characters"}
POST https://api.appstoreconnect.apple.com/v1/customerReviewResponses
     {"data":{"type":"customerReviewResponses","attributes":{"responseBody":"..."},
      "relationships":{"review":{"data":{"type":"customerReviews","id":"..."}}}}}
```

Both require the Play "Reply to reviews" permission / an ASC key role that can respond. During the hackathon the
writer runs in dry-run unless the owner approves a specific reply in the queue.

## 6. Labelling

- Label guide (`docs/LABEL_GUIDE.md`, written on day 2): category definitions with 3 examples each in at least four
  languages, severity scale, tie-break rules (a crash report that also asks for a refund is `crash`, severity by user
  impact).
- Owner labels the 600-item gold set in the labelling page (about 2 hours over two sessions). Agreement check: the
  owner relabels 50 items a day later; Cohen's kappa is reported as the human ceiling.
