# Creator Analytics

Creator analytics include total and active installations, trusted runtime
executions, success rate, error count, reviews, and average rating. Metrics are
aggregated per creator and package; an API key can read only its own creator
namespace.

Execution counters accept only internal `agent_runner` and `workflow_engine`
sources. Clients cannot submit or rewrite usage. No raw user context, Telegram
identifier, secret, or payment information is stored.
