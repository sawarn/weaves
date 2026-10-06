# GCP deployment

Production runs in `asia-south1` with a Cloud Run API, a one-instance Cloud Run
worker pool, a public static frontend, and a small zonal Cloud SQL PostgreSQL
instance. Runtime passwords, the database URL, encryption key, one-time
onboarding token, and owner credentials are generated directly into Secret
Manager. They do not belong in repository files or GitHub settings.

## First deployment

Prerequisites: authenticated `gcloud`, `gh` authenticated to both repositories,
Docker, Python 3, OpenSSL, and permission to configure project IAM and billing.

From the backend repository root, run:

```sh
bash infra/gcp/bootstrap.sh
```

This creates the Cloud SQL instance, Artifact Registry repository, runtime and
deployment identities, Secret Manager secrets, and GitHub OIDC trust. It writes
only nonsecret GCP identifiers as GitHub Actions repository variables. GitHub
Actions authenticates through Workload Identity Federation; no service-account
key is created.

For the first deploy, clone `sawarn/weaves-app` beside this repository as
`../weaves-app`, then run:

```sh
bash infra/gcp/deploy-initial.sh
```

The script builds and pushes both containers, starts the frontend and API,
creates the initial owner using a short-lived Secret Manager token, disables
public organization onboarding, removes the API's access to that token, starts
the background worker, and runs the API smoke test. Owner credentials stay in
Secret Manager and are loaded into the current process only when the workflows
run their end-to-end checks.

The first run can take several minutes while Cloud SQL is created. Later
deployments happen from pushes to `main` after CI passes. Backend CI runs the
Python test, lint, type checks and container build; frontend CI runs the
JavaScript check and container build. Successful main-branch builds deploy the
service and worker or frontend, then run the API smoke test or Playwright
browser test.

## URLs and domains

The first deploy prints the Cloud Run `run.app` URLs for the UI and API. Custom
domain routing is intentionally a separate step because it requires editing
the domains' DNS records. The intended production hosts are
`app.weave-studio.in` and `api.weave-studio.in`.
