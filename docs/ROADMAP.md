# Roadmap

Planned improvements, roughly in order of difficulty. Each one teaches something specific.

- [ ] **Require HTTPS on the bucket.** Add a bucket policy that denies any request where `aws:SecureTransport` is false.
  *Learn:* bucket policies and explicit deny.
- [ ] **Enforce upload size at upload time.** Replace the presigned `PUT` with a presigned `POST` whose policy has a `content-length-range` condition.
  *Learn:* POST policies, and why a `PUT` URL cannot limit size.
- [ ] **Mark abandoned jobs.** A job whose file never arrives stays `PENDING_UPLOAD`. Have `GET /jobs/{id}` report it as expired once the upload URL has lapsed.
  *Learn:* deriving state from timestamps instead of running a cleanup job.
- [ ] **Download the rejected rows.** Write a CSV of rejected rows to `errors/<job_id>.csv` and return a presigned `GET` URL for it in the job.
  *Learn:* presigned downloads, writing to S3 from Lambda.
- [ ] **Operations dashboard.** A CloudWatch dashboard showing queue depth, message age, processor duration and API errors.
  *Learn:* metrics and `aws_cloudwatch_dashboard`.
- [ ] **List recent jobs.** Add a global secondary index and a `GET /jobs` endpoint.
  *Learn:* GSIs, and what single-table design cannot answer without one.
- [ ] **Authentication.** A JWT authorizer backed by Cognito, with each job tied to the user who created it.
  *Learn:* Cognito, authorizers, per-user authorization.
- [ ] **Remote state and deploys from CI.** An S3 backend with state locking, then GitHub Actions with OIDC: plan on pull requests, apply on merge.
  *Learn:* team workflows, short-lived credentials.
- [ ] **Bigger files.** Stream the file instead of reading it into memory, and split very large files across invocations with Step Functions.
  *Learn:* Lambda memory and time limits, orchestration.
- [ ] **React to finished jobs.** Publish a "job finished" event to EventBridge so other systems can subscribe.
  *Learn:* event buses and decoupling producers from consumers.
