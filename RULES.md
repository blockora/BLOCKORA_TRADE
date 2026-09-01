BLOCKORA_TRADE — OpenCode Operating Rules

1. PROJECT IDENTITY

Project: "BLOCKORA_TRADE"

Platform:

- Android Termux / Ubuntu proot
- Python 3.14

Purpose:

- NIFTY options market analysis
- Recommendation/advisory system

Trading mode:

- RECOMMENDATION ONLY

Absolute rule

This project must NOT automatically place, modify, or cancel trades.

Never implement or call automatic trading execution such as:

- "placeOrder"
- "modifyOrder"
- "cancelOrder"
- automatic BUY execution
- automatic SELL execution
- automatic position management

Market-data access is allowed.

The final trading action always remains with the user.

---

2. SOURCE OF TRUTH

The authoritative project is:

"/data/data/com.termux/files/home/BLOCKORA_TRADE"

Do not use or modify these as alternative project sources:

- "~/blockora-ai"
- "~/BLOCKORA_TRADE_BACKUP_20260821"
- "~/blockora"
- archived ZIP files
- unrelated projects in the Termux home directory

Do not copy implementation from another Blockora project unless the user explicitly asks for comparison or migration.

---

3. SECURITY

.env

NEVER read ".env".

Do not:

- "cat .env"
- "less .env"
- "grep .env"
- print environment secrets
- inspect secret values
- modify ".env"

Never expose:

- API keys
- API passwords
- PINs
- TOTP secrets
- Telegram bot tokens
- authentication tokens

The existing "opencode.json" permission rules are the security boundary and must not be weakened.

".env.example" may be inspected when needed.

---

4. MANDATORY DEVELOPMENT WORKFLOW

For every coding task, follow this sequence:

USER TASK
    ↓
READ RULES
    ↓
INSPECT
    ↓
TRACE
    ↓
IDENTIFY ROOT CAUSE
    ↓
PLAN
    ↓
USER APPROVAL
    ↓
EDIT
    ↓
TEST
    ↓
VERIFY
    ↓
REPORT

Do not skip these stages for non-trivial changes.

---

5. INSPECT BEFORE EDITING

Never immediately modify code.

First inspect the relevant implementation.

Determine:

- entry point
- callers
- dependencies
- inputs
- outputs
- configuration
- database interactions
- logging
- tests
- error handling
- existing fallbacks

You may READ multiple relevant files when necessary to understand the problem.

Reading multiple files does NOT mean modifying multiple files.

---

6. TRACE THE REAL DATA FLOW

Before fixing a bug, trace the actual execution path.

For example:

main.py
  ↓
data layer
  ↓
market data
  ↓
option chain
  ↓
analysis / engines
  ↓
decision
  ↓
risk
  ↓
report
  ↓
Telegram

Do not assume that this diagram exactly matches the implementation.

Verify the real call chain in the source code.

If the requested behavior conflicts with the actual architecture, explain the conflict before editing.

---

7. ROOT-CAUSE FIRST

Do not fix symptoms blindly.

Before editing:

1. Reproduce the problem when possible.
2. Locate the failing function/module.
3. Trace upstream and downstream effects.
4. Identify the root cause.
5. Determine the minimum safe correction.

Do not add arbitrary fallback logic simply to suppress an error.

Do not convert failed live data into fake data.

---

8. PLAN BEFORE CODE

For non-trivial tasks, provide a short plan containing:

- root cause
- files that need modification
- exact type of change
- tests to run
- expected result

Wait for user approval before applying non-trivial changes.

For a very small, obvious correction explicitly requested by the user, the change may be made directly, but the affected file and verification must still be clear.

---

9. FILE MODIFICATION RULE

Modify only files required by the approved solution.

Do NOT use:

«ONE FILE AT A TIME»

as a restriction on inspection.

Instead:

Reading

Multiple related files are allowed.

Editing

Only required files may be modified.

Do not modify unrelated files.

Do not rewrite entire modules when a targeted change is sufficient.

---

10. SHOW BEFORE EDIT

Before changing an important function/class:

- identify the file
- identify the function/class
- show the relevant existing code
- explain what will change
- explain why

Do not dump entire large files unless necessary.

---

11. MINIMAL CHANGE PRINCIPLE

Prefer:

- small patches
- existing functions
- existing interfaces
- existing data structures
- existing logging
- existing configuration

Avoid:

- unnecessary refactors
- renaming unrelated functions
- moving files without reason
- rewriting working modules
- duplicate implementations
- new dependencies without justification

---

12. PRESERVE EXISTING ARCHITECTURE

Do not remove or bypass existing systems without explicit approval.

Preserve where applicable:

- market-data engine
- option-chain engine
- decision engine
- ranking engines
- regime engine
- risk engine
- learning engines
- tracking
- replay harness
- database
- Telegram
- health checks
- logging
- tests
- shadow-data system

If architecture needs to change, explain why first.

---

13. MARKET DATA INTEGRITY

Never invent live market data.

Never claim data is live when it is not.

Never fabricate:

- spot price
- option LTP
- option chain
- IV
- Greeks
- candles
- expiry
- strike
- timestamps

If live data is unavailable:

- report the failure
- use an explicitly supported fallback only
- label fallback/demo data clearly
- never silently present simulated data as live

---

14. STALE DATA PROTECTION

Timestamp validation is important.

Do not bypass freshness guards merely to make the system produce a signal.

If data is stale or invalid:

- reject it
- explain why
- prevent unsafe downstream decisions

A stale-data error should be fixed at its root rather than hidden.

---

15. DECISION SAFETY

The decision engine must remain conservative.

Do not generate a strong recommendation when:

- required market data is missing
- required option-chain data is invalid
- timestamps are stale
- critical indicators are unavailable
- market direction is ambiguous
- risk validation fails

When required evidence is insufficient, prefer:

"NO TRADE"

or the project's existing safe/neutral state.

---

16. RISK ENGINE

Never weaken risk controls simply to increase the number of signals.

Do not:

- remove stop-loss validation
- bypass volatility gates
- bypass confidence validation
- bypass decision validation
- bypass contract validation
- bypass safety regression tests

Any risk-rule change requires explicit justification and regression testing.

---

17. OPTION / CONTRACT INTEGRITY

Option selection must use validated contract information.

Verify where applicable:

- symbol
- token
- exchange
- expiry
- strike
- option type
- LTP
- timestamp

Do not select a contract from incomplete or stale data.

Do not silently substitute a different contract.

---

18. TELEGRAM

Telegram is an alert/output mechanism.

Never expose Telegram credentials.

Do not send misleading alerts.

Signal notifications must respect the project's decision and risk gates.

Do not bypass decision validation merely to send a Telegram message.

Telegram failures must not corrupt the underlying trading decision.

---

19. LOGGING

Preserve useful existing logger calls.

Logs must never contain:

- API keys
- passwords
- PINs
- TOTP secrets
- Telegram tokens
- other credentials

Use clear log messages for:

- data source
- fallback selection
- validation failure
- stale data
- decision rejection
- API failure
- Telegram failure

Do not hide important failures with broad "except Exception" blocks.

---

20. TESTING

After modifying code, run the most relevant tests.

At minimum, where applicable:

python -m pytest -q

For the main application, also verify the project's supported safe/demo execution path.

Do not use live trading execution for testing.

For changes involving:

Market data

Test:

- valid response
- invalid response
- stale response
- API failure
- fallback behavior

Option chain

Test:

- valid chain
- missing timestamp
- stale chain
- invalid contracts
- strike continuity

Decision

Test:

- bullish case
- bearish case
- neutral case
- insufficient-data case
- risk rejection

Safety

Run:

python -m pytest tests/test_safety_regression.py -q

when the change could affect decision/trading safety.

---

21. REGRESSION CHECK

After the fix:

1. Run targeted tests.
2. Run relevant regression tests.
3. Run the full test suite when practical.
4. Check "git diff".
5. Confirm only intended files changed.

Use:

git status --short
git diff --stat
git diff

Do not revert user changes automatically.

---

22. GIT SAFETY

Never run destructive Git commands without explicit user approval.

Do NOT automatically run:

git reset --hard
git clean -fd
git checkout -- .
git restore .

Existing user changes must be preserved.

Before making risky changes, create a safe checkpoint when appropriate.

---

23. DEPENDENCIES

Do not add a dependency unless necessary.

Before adding one:

1. Check existing dependencies.
2. Check whether standard Python can solve the problem.
3. Check Termux compatibility.
4. Update "requirements.txt" if required.
5. Explain why the dependency is needed.

---

24. CONFIGURATION

Do not modify production configuration merely to hide a bug.

Configuration changes must be:

- necessary
- documented
- minimal
- tested

Never modify ".env".

Use ".env.example" for documenting required environment variables.

---

25. BACKUPS

Backup directories are reference material only.

Never modify:

"BLOCKORA_TRADE_BACKUP_20260821"

unless the user explicitly requests a backup comparison or restoration.

Do not automatically copy old code into the active project.

---

26. REPORT AFTER EVERY CHANGE

After completing a task, report:

Changed

List modified files.

Root cause

Explain the actual cause.

Fix

Explain what was changed.

Tests

List commands/tests executed and results.

Verification

Confirm whether unrelated files changed.

Remaining issues

Clearly state anything unresolved.

Never claim success if tests were not actually run.

---

27. COMPLETION CRITERIA

A task is complete only when:

- requested behavior is implemented
- root cause is addressed
- tests pass or known failures are explained
- no security boundary was weakened
- no unrelated files were changed
- existing architecture remains intact
- advisory-only trading safety remains intact

---

28. FINAL PRIORITY ORDER

When instructions conflict, prioritize:

1. Security
2. Trading safety
3. Data integrity
4. User's explicit approved task
5. Existing project architecture
6. Minimal implementation
7. Testing and regression safety

Never sacrifice security or trading safety to make a feature appear to work.
