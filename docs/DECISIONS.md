# Design decisions

Short records of the choices that shaped this project: what was chosen, what it costs, and when to revisit it.

### 1. Asynchronous processing instead of a synchronous upload endpoint
**Chosen:** The API only creates a job. A background worker does the processing and the client polls for the result.
**Why:** Processing time grows with file size, and API Gateway cuts requests off at 30 seconds. Background work can also be retried without the client resending anything.
**Trade-off:** The client needs a polling loop, and results are not immediate.

### 2. Presigned URL upload, direct to S3
**Chosen:** `POST /uploads` returns a URL signed for one `PutObject` on one key, valid 5 minutes.
**Why:** It avoids the 10 MB API Gateway and 6 MB Lambda payload limits, costs no Lambda time for the transfer, and keeps the bucket private.
**Trade-off:** A presigned `PUT` cannot limit the upload size, so the worker enforces the 5 MB cap after the fact. A presigned `POST` policy can enforce size at upload time and is on the roadmap.

### 3. S3 → SQS → Lambda, not S3 → Lambda directly
**Chosen:** S3 notifies a queue, and Lambda polls the queue.
**Rejected:** S3 invoking the function directly. It works, but Lambda retries a failed event at most twice, there is no batching, and a burst of uploads becomes an equal burst of concurrent functions.
**Why:** The queue gives a configurable retry count, a dead-letter queue to inspect, a concurrency cap (`maximum_concurrency = 2`), and a buffer if the worker is down.
**Trade-off:** One more component, and up to a few seconds of extra latency.

### 4. Standard queue, with idempotent processing
**Chosen:** A standard SQS queue, which delivers at least once and in no guaranteed order.
**Rejected:** A FIFO queue. S3 event notifications cannot target FIFO queues, and files are independent, so ordering is not needed.
**Why it's safe:** Reprocessing overwrites the same records and sets the same counts.

### 5. Visibility timeout of 6x the function timeout
**Chosen:** Function timeout 60 s, visibility timeout 360 s.
**Why:** While a function works on a message, SQS hides it. If the hiding ended first, a second invocation would start the same file in parallel. AWS recommends at least six times the function timeout for Lambda triggers, to leave room for retries of throttled invocations.
**Trade-off:** A failed message waits 6 minutes before its next attempt.

### 6. Partial batch responses
**Chosen:** `ReportBatchItemFailures`: the handler catches errors per message and returns the failed ids.
**Why:** Otherwise one failing file would cause every file in its batch to be reprocessed.
**Trade-off:** The function always returns normally, so the Lambda `Errors` metric stays at zero even when messages fail. That is why the alarms watch the queues instead.

### 7. Permanent failures are recorded, not retried
**Chosen:** A file that can never succeed (wrong columns, not UTF-8, too large) marks the job `FAILED` and the message is deleted.
**Why:** Retrying cannot fix the file. It would waste invocations and fill the dead-letter queue with messages that need no engineer.
**Trade-off:** The line between "bad file" and "bug" must be drawn carefully. Only the explicit `FileRejected` exception counts as permanent; anything unexpected is retried.

### 8. Single-table DynamoDB design
**Chosen:** Jobs and records in one table, sharing the partition key `JOB#<id>`.
**Why:** Both access patterns become a single `GetItem` or `Query`, and one TTL setting and one IAM resource cover everything.
**Trade-off:** There is no way to ask "which jobs exist?" or "find order X across all jobs" without a global secondary index. A partition is also a single unit for throughput, which is why files are capped at 10,000 rows.

### 9. Records keyed by `order_id`
**Chosen:** Sort key `ORDER#<order_id>`.
**Rejected:** Keying by line number. That would also be idempotent, but it would keep duplicate orders.
**Why:** The business identity of a row makes duplicates impossible and retries harmless.

### 10. Report bad rows, keep good rows
**Chosen:** A file with some invalid rows finishes as `COMPLETED_WITH_ERRORS`. The job stores the first 20 errors with line numbers, plus total counts.
**Rejected:** Rejecting the whole file on the first bad row, which forces a full re-upload for one typo.
**Trade-off:** The caller must check the status and decide whether a partial import is acceptable. Only 20 errors are kept because a DynamoDB item is limited to 400 KB.

### 11. Expire everything after 7 days
**Chosen:** An S3 lifecycle rule for files and DynamoDB TTL for items, driven by one Terraform variable.
**Why:** A learning project should not accumulate storage costs or keep email addresses indefinitely.
**Trade-off:** TTL deletion is not instant; items can remain readable for a while after they expire.

### 12. IAM generated from data, with `dynamic` blocks
**Chosen:** Each function lists its permissions as `statements` in `locals.tf`, and a `dynamic "statement"` block turns them into its policy.
**Why:** The whole permission model is readable in one place, and a new function cannot be added without declaring what it may do.
**Trade-off:** `dynamic` blocks are harder to read than literal ones.

### 13. Alarms on queues, optional email
**Chosen:** Alarms on dead-letter queue depth and on the age of the oldest queued message. The email subscription is created only when `alert_email` is set (`count`).
**Why:** These two signals cover "something failed for good" and "something is stuck". Making the email optional keeps the default deploy free of confirmation emails.
