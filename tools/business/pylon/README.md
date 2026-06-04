# Pylon

Pylon is exposed to Centaur agents as a REST tool, not as an MCP server and not
as the local Typer CLI. In a sandbox, inspect and call it with the `call` helper:

```bash
call discover pylon
call pylon get_issue_context '{"issue_id":"16412"}'
```

Use `get_issue_context` as the first call when a user references a support
thread such as `Pylon Issue #16412`. It returns:

- `issue`: the issue metadata and body from `GET /issues/{id}`
- `messages`: customer-facing messages, replies, and internal notes from
  `GET /issues/{id}/messages`
- `threads`: internal issue threads from `GET /issues/{id}/threads`

Pylon accepts issue numbers for `GET /issues/{id}`, but the messages and threads
endpoints are documented around the canonical issue ID. The client resolves
numeric refs first, so these all work:

```bash
call pylon get_issue_context '{"issue_id":"16412"}'
call pylon get_issue_context '{"issue_id":"#16412"}'
call pylon get_issue_context '{"issue_id":"https://app.usepylon.com/issues/16412"}'
```

Do not call CLI commands through the API helper:

```bash
# Wrong in a sandbox: "issue" is a CLI command, not a tool method.
call pylon issue 16412

# Correct in a sandbox.
call pylon get_issue '{"issue_id":"16412"}'
call pylon get_issue_messages '{"issue_id":"16412"}'
```

For local standalone use after installing the tool package:

```bash
pylon issue-context 16412 --json
pylon issue-messages 16412 --json
pylon issue-threads 16412 --json
```
