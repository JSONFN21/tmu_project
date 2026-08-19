# Google Cloud deployment

The production design uses two Cloud Run workloads and one BigQuery table:

```text
Cloud Scheduler → Cloud Run Job → ServiceNow API → BigQuery
                                               ↓
Authorized TMU users → IAP → Streamlit on Cloud Run
```

The Streamlit service only reads BigQuery. The scheduled job is the only
workload that receives the ServiceNow credentials and permission to replace the
incident table.

## 1. Choose the project and region

Use the TMU-approved Google Cloud project and data location. The Toronto region
is shown as an example; confirm organizational data-residency requirements
before creating the dataset because its location cannot be changed later.

```bash
export BST_PROJECT_ID="your-project-id"
export BST_REGION="northamerica-northeast2"
export BST_DATASET="ccs_analytics"
export BST_TABLE="incidents"
export BST_IMAGE_REPOSITORY="ccs-apps"
export BST_IMAGE="$BST_REGION-docker.pkg.dev/$BST_PROJECT_ID/$BST_IMAGE_REPOSITORY/business-service-trends:latest"

gcloud config set project "$BST_PROJECT_ID"
gcloud services enable \
  artifactregistry.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  cloudscheduler.googleapis.com \
  iap.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com
```

## 2. Create the dataset and service identities

```bash
bq --location="$BST_REGION" mk --dataset \
  --description="CCS ServiceNow incident reporting snapshots" \
  "$BST_PROJECT_ID:$BST_DATASET"

gcloud iam service-accounts create bst-dashboard \
  --display-name="BST dashboard BigQuery reader"
gcloud iam service-accounts create bst-sync \
  --display-name="BST ServiceNow BigQuery sync"

export BST_DASHBOARD_SA="bst-dashboard@$BST_PROJECT_ID.iam.gserviceaccount.com"
export BST_SYNC_SA="bst-sync@$BST_PROJECT_ID.iam.gserviceaccount.com"
```

In the BigQuery console, select the `ccs_analytics` dataset, open **Sharing →
Permissions**, and add these dataset-level grants:

- `$BST_DASHBOARD_SA`: **BigQuery Data Viewer**
- `$BST_SYNC_SA`: **BigQuery Data Editor**

The sync identity also needs permission to start a BigQuery load job at the
project level:

```bash
gcloud projects add-iam-policy-binding "$BST_PROJECT_ID" \
  --member="serviceAccount:$BST_SYNC_SA" \
  --role="roles/bigquery.jobUser"
```

The dashboard reads table rows directly and does not need BigQuery Job User.

## 3. Store ServiceNow credentials

Create these secrets in Secret Manager using the Cloud Console, or create an
empty secret and add each value through standard input so the value is not
placed in shell history:

```bash
gcloud secrets create SN_USERNAME --replication-policy=automatic
gcloud secrets versions add SN_USERNAME --data-file=-

gcloud secrets create SN_PASSWORD --replication-policy=automatic
gcloud secrets versions add SN_PASSWORD --data-file=-

gcloud secrets create SN_ENDPOINT --replication-policy=automatic
gcloud secrets versions add SN_ENDPOINT --data-file=-
```

Enter one value, then finish standard input with `Ctrl-D`. Grant access only to
the sync identity:

```bash
for BST_SECRET_NAME in SN_USERNAME SN_PASSWORD SN_ENDPOINT; do
  gcloud secrets add-iam-policy-binding "$BST_SECRET_NAME" \
    --member="serviceAccount:$BST_SYNC_SA" \
    --role="roles/secretmanager.secretAccessor"
done
```

## 4. Build the container

```bash
gcloud artifacts repositories create "$BST_IMAGE_REPOSITORY" \
  --repository-format=docker \
  --location="$BST_REGION" \
  --description="CCS internal applications"

gcloud builds submit --tag "$BST_IMAGE" .
```

## 5. Deploy and run the sync job

```bash
gcloud run jobs deploy bst-servicenow-sync \
  --image="$BST_IMAGE" \
  --region="$BST_REGION" \
  --service-account="$BST_SYNC_SA" \
  --command=python \
  --args=sync_servicenow_to_bigquery.py \
  --set-env-vars="BQ_PROJECT=$BST_PROJECT_ID,BQ_DATASET=$BST_DATASET,BQ_TABLE=$BST_TABLE" \
  --set-secrets="SN_USERNAME=SN_USERNAME:latest,SN_PASSWORD=SN_PASSWORD:latest,SN_ENDPOINT=SN_ENDPOINT:latest" \
  --task-timeout=15m \
  --max-retries=2

gcloud run jobs execute bst-servicenow-sync \
  --region="$BST_REGION" \
  --wait
```

Confirm that the execution reports the expected row count before continuing.
In Cloud Run, open **Jobs → bst-servicenow-sync → Triggers → Add Scheduler
Trigger** and choose the approved refresh schedule, such as once nightly. Cloud
Scheduler invokes the job without exposing a public endpoint.

## 6. Deploy the private dashboard

```bash
gcloud run deploy bst-dashboard \
  --image="$BST_IMAGE" \
  --region="$BST_REGION" \
  --service-account="$BST_DASHBOARD_SA" \
  --set-env-vars="DATA_BACKEND=bigquery,BQ_PROJECT=$BST_PROJECT_ID,BQ_DATASET=$BST_DATASET,BQ_TABLE=$BST_TABLE" \
  --memory=2Gi \
  --session-affinity \
  --no-allow-unauthenticated \
  --iap
```

Grant the IAP-secured Web App User role only to the appropriate TMU Google
Group or named users. Do not make the service public. The Streamlit container
does not need `SN_USERNAME`, `SN_PASSWORD`, or `SN_ENDPOINT`.

## 7. Verify

1. Open the Cloud Run URL as an authorized user.
2. Confirm the sidebar says **BigQuery** and shows the expected incident count.
3. Compare a few totals and incident numbers with ServiceNow.
4. Execute the sync job again and confirm the snapshot timestamp changes within
   five minutes; the dashboard caches BigQuery reads for five minutes.
5. Confirm an unauthorized account cannot open the dashboard.

## Optional local BigQuery check

After installing the project requirements and authenticating Application
Default Credentials, the local dashboard can read the same table without a
service-account key file:

```bash
gcloud auth application-default login
DATA_BACKEND=bigquery \
BQ_PROJECT="$BST_PROJECT_ID" \
BQ_DATASET="$BST_DATASET" \
BQ_TABLE="$BST_TABLE" \
streamlit run app.py
```

To bootstrap the table from the existing local snapshot instead of downloading
ServiceNow again:

```bash
BQ_PROJECT="$BST_PROJECT_ID" \
BQ_DATASET="$BST_DATASET" \
BQ_TABLE="$BST_TABLE" \
python sync_servicenow_to_bigquery.py \
  --from-parquet .data/servicenow_incidents.parquet
```
