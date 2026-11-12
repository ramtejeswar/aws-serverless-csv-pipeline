# Runbook

## Before the first deploy

1. **Use an IAM user, not the root account.** Check with `aws sts get-caller-identity`.
2. **Set a billing alarm** (Billing console → Budgets → a $5 budget).
3. **Install the tools:** Terraform 1.5 or newer, Python 3.13, and `make`.

## Deploy

```bash
make install         # once
make test            # unit tests, no AWS needed
make plan            # read it: expect about 40 to add, 0 to change, 0 to destroy
make deploy          # tests + terraform apply; type "yes" when asked
make smoke           # uploads samples/orders.csv and checks the outcome
```

To receive alarm emails:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars   # set alert_email
make deploy
```

AWS then emails a confirmation link. No notifications arrive until you click it.

## Try it by hand

```bash
API=$(terraform -chdir=infra output -raw api_url)

curl -s -X POST "$API/uploads" -d '{"filename": "orders.csv"}'    # copy job_id and upload_url
curl -s -X PUT --upload-file samples/orders.csv "<upload_url>"    # quote the URL: it contains &
curl -s "$API/jobs/<job_id>"                                      # repeat until status is final
curl -s "$API/jobs/<job_id>/records?limit=3"
```

## Logs

```bash
aws logs tail /aws/lambda/csv-pipeline-dev-processor --follow
aws logs tail /aws/apigateway/csv-pipeline-dev-access --follow
```

Useful **CloudWatch Logs Insights** queries on the processor log group:

```
# Outcome of every job in the time range
filter message in ["job_finished", "job_failed"]
| fields @timestamp, job_id, status, valid_rows, error_rows, reason
| sort @timestamp desc

# Messages that raised an error and will be retried
filter message = "message_failed"
| fields @timestamp, message_id, errorMessage
| sort @timestamp desc
```

## Follow one upload through the system

| Step | Where to look | Healthy sign |
|---|---|---|
| Job created | `GET /jobs/<id>` | `PENDING_UPLOAD` |
| File arrived | `aws s3 ls s3://<bucket>/uploads/` | `<job_id>.csv` is listed |
| Event queued | SQS console → the uploads queue → Monitoring | "Messages received" ticks up |
| Worker ran | Processor log group | A `job_finished` or `job_failed` line with the job id |
| Result stored | `GET /jobs/<id>` | A final status with counts |

## The dead-letter queue

The `dlq-not-empty` alarm means a file failed processing three times.

1. **Read the message** without deleting it:
   ```bash
   aws sqs receive-message --queue-url "$(terraform -chdir=infra output -raw dead_letter_queue_url)" \
     --max-number-of-messages 1 --visibility-timeout 0
   ```
   The body holds the S3 object key, and the key holds the job id.
2. **Find the cause** in the processor log group: search for `message_failed`.
3. **Fix it**, deploy, then **redrive**: in the SQS console open the dead-letter queue and choose "Start DLQ redrive" to send the messages back to the uploads queue. Processing is idempotent, so replaying is safe.
4. A job whose message is in the dead-letter queue stays in `PROCESSING` until it is redriven.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `PUT` to the upload URL returns 403 | URL expired (5 minutes), or it was altered when copied | Request a new one; keep it inside quotes |
| `PUT` returns 403 `SignatureDoesNotMatch` | A different HTTP method was used | Use `PUT` |
| Job stays `PENDING_UPLOAD` after uploading | The object key does not match `uploads/<job_id>.csv`, or the notification is missing | Check the bucket's event notifications in the S3 console |
| Job stays `PROCESSING` | The worker is failing and retrying | Read the processor logs; check the dead-letter queue |
| Job is `FAILED` | The file was rejected | Read `failure_reason` in the job; fix the file and upload again as a new job |
| `AccessDenied` in a function log | That function's role lacks an action | Add it to the function's `statements` in `infra/locals.tf` |
| `terraform apply` fails on the bucket notification | The queue policy was not in place yet | Run `make deploy` again |
| No alarm emails | Subscription not confirmed | Click the link in the AWS confirmation email |

## Tear down

```bash
make destroy
```

This deletes the bucket **including any files in it** (`force_destroy`), the table and both queues. Confirm nothing is left:

```bash
aws resourcegroupstaggingapi get-resources \
  --tag-filters Key=Project,Values=csv-pipeline --query 'ResourceTagMappingList[].ResourceARN'
```

An empty list `[]` means everything is gone.
