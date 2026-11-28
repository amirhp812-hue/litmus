# LITMUS

**Rules that must pass their own test before they are allowed to rule.**

Litmus is a GenLayer Intelligent Contract (GenVM **v0.4**, built for **Studionet** on Studio v0.123 / Consensus v0.6) for communities that
enforce written rules with money at stake. Most on-chain "AI court" contracts let any text become a rule and
then trust the model to interpret it. Litmus turns that around:

1. A **rule author** writes the rule, up to three *aggravating factors*, and 4-6 **golden probes**: short
   scenarios with the verdict (and factor flags) the author expects.
2. The validator network has to **reproduce every golden probe under consensus**. The share of probes it
   gets exactly right is the rule's **clarity score**. Below the author's threshold (75-100 %) the rule can
   not be certified. Vague rules die at the gate, before anybody's money is bound by them.
3. Only a **certified rule** can enlist members (who post a stake), accept cases (plaintiff posts a deposit)
   and punish breaches. Every ruling is appealable once, with a fresh-eyes re-judgement.
4. Rulings feed back into the rule: an appeal that **overturns** a ruling slashes the author's bond and two
   overturns **suspend** the rule. Authors are paid in reputation and bond for writing rules the validators
   read the same way twice.

It is deliberately **not** another dispute-resolution toy: the model never decides money directly. It only
fills in a closed, tiny form (`verdict` plus one boolean per aggravating factor); everything else - severity,
penalty, strikes, expulsion, slashing, refunds - is deterministic contract arithmetic on that form.

## The exact-equality law

> Every value that is stored, changes a counter, or decides the contract path or a payout (statuses,
> booleans, scores, levels, severities, penalties) must be **identical** between leader and validator.
> No tolerance. No adjacent level. No "one step stricter". Only the free-text `reason` is compared loosely.

How the code enforces it (details in [docs/CONSENSUS.md](docs/CONSENSUS.md)):

* the validator accepts a leader proposal only if `verdict ==` and `factors ==` hold against its own
  independent assessment (it never sees the leader's answer, so it cannot be anchored by it);
* a leader answer must already be in canonical form (exact key set, upper-case enum, real booleans, right
  number of flags, flags only on BREACH); a validator never repairs it;
* `reason` is bounded free text and never decides anything;
* the law is locked by an **exhaustive equality matrix**, **20 mutation tests** (tolerances, one-step
  acceptance, adjacent verdicts, skipped checks ...) and **AST guards** that fail if the validator ever uses
  `abs`, ordering comparisons, counting or arithmetic.

## Lifecycle

```
 forge_rule (bond) -> DRAFT --run_probe x N--> certify_rule --> CERTIFIED --retire_rule--> RETIRED
                        |  (clarity >= pass %)                     |  2 overturned appeals
                        +--revise_rule (max 2)                      +--------------------> SUSPENDED

 enlist (stake) -> ACTIVE --3 strikes (configurable)--> EXPELLED          leave -> stake to ledger
 file_case (deposit) -> OPEN --rule_case--> RULED --appeal_case--> SETTLED
                          |                    +--waive_appeal / window ends --settle_case--> SETTLED
                          +--7 days without a quorum ruling--void_case--> SETTLED (VOID, deposit refunded)
 every payout lands on a pull-ledger; withdraw() sends it
```

| Verdict (final) | Plaintiff | Defendant | Counters |
|---|---|---|---|
| BREACH, severity s = 1 + true flags | deposit back + `s x penalty_unit` | stake -= penalty, +1 strike | `breaches` |
| COMPLIANT | filing deposit forfeited | receives the forfeited deposit | `dismissed` |
| INCONCLUSIVE | deposit back | nothing | `inconclusive` |
| VOID (no quorum for 7 days) | deposit back | reservation released | `voided` |
| Appeal, favourable to appellant | appeal deposit back + `penalty_unit` slashed from the author bond | | rule `reversals` +1 |
| Appeal, not favourable | appeal deposit goes to the other party | | |

Each open case reserves the maximum possible penalty from the defendant's stake, so a penalty is always
fully collectable and never partial.

## Contract API

| Write | Who | Notes |
|---|---|---|
| `forge_rule(title, text, aggravators_json, probes_json, penalty_unit, filing_deposit, enlist_stake, strike_limit, pass_percent, defense_minutes, appeal_minutes)` payable | anyone | attached value = author bond (>= 3 penalty units) |
| `revise_rule`, `run_probe`, `certify_rule`, `retire_rule`, `reclaim_bond` | author | probes run once per version; max 2 revisions |
| `enlist` payable, `leave` | member | exact stake; re-enlist keeps strikes; expelled members can only leave |
| `file_case` payable, `submit_defense` | member / defendant | at most 3 open cases per member |
| `rule_case`, `settle_case`, `void_case` | anyone | permissionless once the clock allows |
| `waive_appeal`, `appeal_case` payable | the adversely affected party | appeal = fresh judgement without seeing the first ruling |
| `withdraw` | anyone owed money | pull-payment; ledger zeroed before the transfer is emitted |

Views: `get_stats`, `get_limits`, `get_rule`, `list_rules`, `get_case`, `list_cases`, `get_member`,
`get_claimable`. Amounts are returned as decimal strings, so JavaScript clients never lose wei precision.

Full state machines, record layouts and arithmetic: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt     # genlayer-test 0.30.0, genvm-linter 0.11.1rc2, pytest, cloudpickle
npm ci                                  # genlayer-js 2.1.0 (only needed for the live script)

bash scripts/check.sh                   # lint + static guards + Direct Mode suite + dry run
```

`scripts/check.sh` sets `GENVM_VERSION=v0.6.0-rc14` (the GenVM release Studio v0.123 pins; executor line **v0.4**,
runner `py-genlayer:kzybg95x...`) and pre-downloads it, so the linter and Direct Mode use the real v0.4 SDK, not a mock.
genvm-linter 0.11.0 cannot load that runner, hence the `0.11.1rc2` pin.

### Live end-to-end run on Studionet (GitHub Codespaces friendly)

```bash
node scripts/live_e2e.mjs                 # full run, deploys a fresh contract, writes reports/*.md and *.json
node scripts/live_e2e.mjs --skip-slow     # skip the timeout case (3-minute defense + 4-minute appeal window)
node scripts/live_e2e.mjs --dry-run       # same script, no network, in-process model
```

It deploys the contract, checks the deployed bytes against the source, forges a rule, makes the validators
pass its golden probes, enlists members, runs four cases (waived, compliant, appealed, timed-out), audits
the books after every stage, withdraws everything and ends with a zero-balance contract. Every step is
verified against **contract state**, language-model steps are retried and reported honestly. See
[docs/LIVE_E2E.md](docs/LIVE_E2E.md).

## What was verified

| Gate | Result |
|---|---|
| `genvm-lint check` against the v0.4 runner | passed in the Codespaces run of `bash scripts/check.sh` (`GENVM_VERSION=v0.6.0-rc14`, genvm-linter 0.11.1rc2): 24 methods, 8 views, 16 writes, schema generated |
| Direct Mode suite (real v0.4 SDK) | **146 passed** in `bash scripts/check.sh` (`GENVM_VERSION=v0.6.0-rc14`: lifecycle, validation, payouts, appeals, expulsion, liveness escape, closures pickle like on the real VM) |
| Exact-equality matrix | every (leader, validator) pair of every state for 0-3 factors in PROBE, CASE and APPEAL mode |
| Mutation tests | 20 deliberately broken contracts, all killed (tolerance, one-step, adjacent verdicts, accounting faults) |
| Seeded random walks | 10 walks x 600 steps, books re-audited after every successful call, every outcome reached |
| Differential replay | the live script's model and accounting oracle replayed on the real Python contract: identical final state |
| Static guards (offline, 15 checks) | validator uses `==` only; one model call site; no storage or time inside the nondeterministic block; the v0.4 rules (header, imports, no removed APIs, no `__receive__`, no decorators on special methods, storage types, `gl.chain.Account` transfers only in `withdraw`) |
| Dry run, full (`node scripts/live_e2e.mjs --dry-run`, timeout case included) | **174 PASS, 0 FAIL, 0 WARN**, 4 INFO (`reports/live_e2e_dryrun_2026-11-28T11-32-43-002Z.*`) |
| Live run on Studionet (`--skip-slow`, v0.4 contract) | **156 PASS, 0 FAIL, 0 WARN**, 6 INFO, 1 SKIP (`reports/live_e2e_studionet_2026-11-28T10-22-17-258Z.*`); deployed bytes equal `contracts/Litmus.py` (36275 bytes, sha256 `2449db55...7088`) |

The exact-equality matrix, mutation, random-walk and differential-replay rows are Direct Mode tests and all passed in the 146-test `bash scripts/check.sh` run on v0.4. The two rows just above this note are recorded in `reports/`.

**Live run on Studionet (v0.4 contract, 2026-11-28):** `reports/live_e2e_studionet_2026-11-28T10-22-17-258Z.md`, a `--skip-slow` run of about
15 minutes (chain id 61999, Studio v0.123 / Consensus v0.6). Fresh deployment `0x7942816B0D37Cb141aAd46527692c6bff9F42Eea`; the deployed
bytes equal `contracts/Litmus.py`. Result: 156 PASS, 0 FAIL, 0 WARN, 6 INFO, 1 SKIP (the timeout case, skipped by `--skip-slow`). The five
golden probes and the three case rulings (waived, compliant, appealed) were agreed by the validators on the first attempt and each equals
the designed expectation (clarity 100); every rejected call is proven by a receipt (`exec=false`); the settlement oracle matched the chain
for all three cases; the books balanced after every stage and ended at zero.

What this run settled:

* **`withdraw` pays out.** All four withdraw transactions finalized, three wallets were credited exactly the withdrawn amount minus the
  transaction fee (126305250000823 wei each) and the contract balance fell to zero. That closes the open question of the 2026-11-26 run,
  which used the v0.2 contract.
* **`messageAllocations` were not needed here.** The script asks the node for a fee estimate that carries them (`estimateTransactionFeesForWrite`);
  that estimate never succeeded (`Missing or invalid parameters`, 14 failed attempts, 7 fallbacks) and the withdraws were sent with the
  default fee config, without allocations. Studionet still delivered every transfer on finalization. Whether other networks or Studio versions
  require allocations is not established, and the failing estimate is a script/SDK parameter issue, not a contract issue.
* **Value attached to rejected payable calls is returned after finalization** (42499999999999996 wei in total; see
  [docs/LIVE_E2E.md](docs/LIVE_E2E.md)).

What it did not cover on chain: the timeout case (expulsion at the strike limit, `settle_case` without a waiver) and the overturn of a ruling
on appeal (case C was upheld: reversals 0, bond untouched). Both are covered by the Direct Mode suite and the dry run only; run
`node scripts/live_e2e.mjs` without `--skip-slow` for the first one. Details and one open observation about the author's wallet:
[docs/LIVE_E2E.md](docs/LIVE_E2E.md). Earlier runs on the v0.2 contract (2026-11-18, 2026-11-26) are history, described there.

## Known limits (by design)

* **Exact equality costs liveness.** If the validators cannot agree on a vague statement the call fails and
  can be retried; a case that never reaches a quorum can be voided after 7 days. Write concrete rules and
  concrete probes: the clarity gate exists to teach exactly that.
* Native-token transfers are emitted **on finalization**; `withdraw` therefore credits the wallet after the
  transaction finalizes, not at acceptance. The 2026-11-28 run confirmed it on Studionet: the wallets were credited once the withdraw transactions were FINALIZED.
* The contract trusts the model only for the closed form described above; it does not fetch web pages. The
  evidence is the text parties submit on-chain.
* One appeal per case; appeals do not chain.
* **Attach exactly the required amount to payable calls.** When the contract rejects a payable call (wrong stake or
  deposit, calling `enlist` twice ...) the call is rolled back and a contract cannot refund inside a call it reverts.
  On Studionet the attached value sits in the contract's native balance until the rejected transaction finalizes and is
  then returned to the sender: seen on 2026-11-26 and again on 2026-11-28 (balance back at the escrow, senders only lost
  fees). The run of 2026-11-18 saw it stay, but it read the balance before finalization. It is never part of
  `escrow_total` and nobody is owed it by the contract, so do not depend on getting it back.

## Layout

```
contracts/Litmus.py            the Intelligent Contract
tests/direct/                  Direct Mode suite (rules, cases, equality law, mutation, fuzz, replay)
tests/test_static_guards.py    AST guards for the equality law
scripts/live_e2e.mjs           live Studionet run (+ --dry-run)
scripts/lib/                   real chain adapter, in-process model, helpers
scripts/check.sh               every offline gate in one command
scripts/verify_deployed_source.mjs   byte parity of deployed code vs source
scripts/verify_withdrawals.mjs       re-check wallet credits of a finished live run after finalization
docs/                          CONSENSUS, ARCHITECTURE, LIVE_E2E
reports/                       live and dry-run reports (*.md for people, *.json for scripts/verify_withdrawals.mjs)
.github/workflows/ci.yml       the same gates as scripts/check.sh on every push and pull request
```
