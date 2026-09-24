# Lenso Jobs Plugin

`lenso-jobs-plugin` is the first-party durable single-step Jobs Plugin for Lenso applications.

It owns:

- durable enqueue and scheduled availability;
- an explicit bounded queue set per keyed Plugin Instance;
- caller-scoped idempotency keys;
- fenced, expiring worker leases;
- bounded retry and terminal failure policy;
- success, failure, and inspection evidence; and
- an operator-managed PostgreSQL schema.

It deliberately does not own business payload meaning, handler implementation, external-effect idempotency, multi-step workflow orchestration, or Kernel scheduling. Disabling or removing the Plugin removes its runtime surface without changing Kernel and does not implicitly delete its operator-managed PostgreSQL data.

## First tracer slice

One authorized producer enqueues a typed job. One authorized worker claims it under an opaque lease and either completes it or reports a retryable/non-retryable failure. An expired lease can never complete a job and may be safely reclaimed with a new fencing token. An observer can inspect the durable state.

The portable `lenso.jobs@1` Capability provides:

- `enqueue`
- `claim`
- `renew`
- `complete`
- `fail`
- `inspect`

Workflow graphs, recurring schedules, priorities, cancellation, progress streams, and a Web/Console surface are intentionally deferred until a real consumer requires them.

The Descriptor and Schemas in this repository are the authoritative Capability
Interface. Rust bindings are published by `lenso-capability-jobs`; the supported
Bun projection is delivered through `@lenso/bun/capabilities/jobs` instead of
being embedded in this Rust crate.

## Ownership

The Jobs Plugin owns job identity, queue placement, availability time, attempt count, lease generation, lease expiry, retry schedule, terminal status, and the last stable failure code. A consuming business Plugin owns the schema and meaning of `payload`, selects the job kind, and makes every external effect idempotent because execution is at-least-once.

Each keyed Jobs Instance declares its allowed queues and caller Instances. Use separate Jobs Instances when queues cross trust or operational boundaries.

PostgreSQL is a private persistence Adapter. The Plugin uses `lenso-postgres-kit` to verify its schema during activation; setup and upgrades are explicit operator workflows.

From the Plugin source package, run that workflow without putting the database
URL in an argument or Plugin configuration:

```sh
LENSO_JOBS_DATABASE_URL='postgres://...' \
  cargo run -p lenso-jobs-plugin --example jobs-operator -- setup jobs_email
LENSO_JOBS_DATABASE_URL='postgres://...' \
  cargo run -p lenso-jobs-plugin --example jobs-operator -- check jobs_email
```

Use `upgrade` in place of `setup` when an existing managed schema needs the
pending migrations. App startup only checks the installed schema and never
creates or upgrades it.

One Instance uses immutable configuration validated again by the factory before preparation:

```json
{
  "schema": "jobs_email",
  "database_url_secret": "jobs/database-url",
  "lease_seconds": 30,
  "retry_base_seconds": 5,
  "retry_max_seconds": 300,
  "queues": ["email"],
  "producer_instances": ["accounts", "organization"],
  "worker_instances": ["email-worker"],
  "observer_instances": ["operations"]
}
```

The schema is [`crates/lenso-jobs-plugin/config.schema.json`](crates/lenso-jobs-plugin/config.schema.json). The database URL itself remains behind the explicitly bound Secrets Capability.

## App adoption

The package is a linked native Rust Plugin with identity `lenso.jobs` and root
Slot `jobs`. Its generated descriptor and factory become available when a Host
links the crate; availability does not activate an Instance. An App adopts and
configures one Instance under `plugins/lenso.jobs/<instance>.toml`, while the
Host-derived Plan binds its exact Secrets, producer, worker, and observer
edges. The legacy public `JobsFactory` remains available for embedding Hosts
that construct a registry explicitly.

## Development

```sh
cargo fmt --all -- --check
cargo check --locked --workspace --all-targets
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
```

PostgreSQL acceptance additionally requires a disposable database whose name starts with `lenso_jobs_test`:

```sh
LENSO_JOBS_TEST_DATABASE_URL=postgres://... \
  cargo test --locked --workspace --features postgres-acceptance
```

## Release

Both workspace crates are candidates for a separately authorized release from
an exact landed `main` SHA. `.github/workflows/release-plz.yml` requires that
SHA, the single-package `release_set` for the next dependency-first phase,
and a successful `quality` job in the candidate push CI run for the same SHA.
The current source declares `lenso-capability-jobs@0.1.6` and
`lenso-jobs-plugin@0.1.6`. When both are unpublished, only the Capability
phase is allowed. After its exact version is visible on crates.io, run the
Plugin phase separately. The workflow selects a config that enables only the
approved package. It refuses a combined release set or a Plugin release before
Capability visibility.

Before the Plugin dry-run and again before publication, the workflow packages
the Jobs Plugin and checks the archive's `Cargo.lock` for a registry-sourced,
checksummed Capability. It then extracts that exact archive and runs
`cargo metadata --locked` without allowing lock changes. The same check can
be run locally after the Capability is available with
`python3 .github/scripts/package-consumer-gate.py`. The postcondition downloads
the published Plugin archive and repeats the check on those registry bytes.
Neither gate replaces a signed App consumer test.

For each phase, run the workflow from `main` with `mode=dry-run` first and
inspect its result. Live publication is a separate manual dispatch with the
same exact SHA and phase-specific release set, `mode=publish`, and
`confirmation=publish`. The live job rechecks that the SHA is still the current
remote `main`, plus registry and CI evidence, immediately before publishing.
If `main` advanced after the dry-run, repeat
candidate review and release planning for the new SHA. Publication uses
crates.io Trusted Publishing with owner `LioRael`, repository
`lenso-jobs-plugin`, workflow `release-plz.yml`, and no GitHub environment.
The workflow has no registry-token fallback. After the live action, a read-only
postcondition compares its release records with the approved set and checks
crates.io visibility, GitHub Releases, and tags pointing to the exact source
SHA. For the Plugin phase it also checks the downloaded `.crate`. A failed or
partial publication must be reconciled from those receipts; do not blindly
repeat the publish dispatch. Neither a local package nor the
dry-run proves a registry upload, signed catalog release, or consumer adoption.
