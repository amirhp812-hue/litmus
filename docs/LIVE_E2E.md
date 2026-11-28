# Live end-to-end run

```bash
npm ci
node scripts/live_e2e.mjs                 # deploys a fresh contract on Studionet and runs everything
node scripts/live_e2e.mjs --skip-slow     # omit the timeout case that waits for the 3-minute defense and 4-minute appeal windows
node scripts/live_e2e.mjs --address=0x... # reuse a FRESH deployment (rules and cases must be 0)
node scripts/live_e2e.mjs --strict        # warnings also fail the run
node scripts/live_e2e.mjs --dry-run       # no network: in-process model with a virtual clock
node scripts/live_e2e.mjs --dry-run --retain-rejected             # model: rejected payable calls keep their value for good (seen 2026-11-18)
node scripts/live_e2e.mjs --dry-run --refund-rejected-late        # model: the value is returned after finalization (seen 2026-11-26 and 2026-11-28)
node scripts/live_e2e.mjs --dry-run --late-transfers              # model: withdraw transfers are applied only on finalization
node scripts/live_e2e.mjs --dry-run --lost-transfers              # model: withdraw finalizes but the transfer never arrives (must FAIL)
node scripts/live_e2e.mjs --dry-run --flip-appeals                # model: every appeal reverses the first ruling (reversal, bond slash, suspension)
node scripts/live_e2e.mjs --dry-run --transcript=run.json         # also write the transcript that tests/direct/test_dryrun_replay.py replays
node scripts/live_e2e.mjs --dry-run --retain-rejected --flaky-rpc # ... and inject a rate-limit refusal and a lost receipt
node scripts/verify_withdrawals.mjs reports/live_e2e_studionet_<stamp>.json   # re-check wallet credits after finalization
```

Options: `--llm-attempts=3`, `--finality-timeout-min=10` (wait for the withdraw transactions to finalize),
`--payout-wait-min=5` (extra wait for a wallet credit after finalization), `--refund-wait-sec=180` (how long value of a
rejected payable call may stay in the contract before the audit calls it retained), `--payouts-warn-only` (downgrade
"finalized but not credited" from FAIL to WARN), `--out-dir=reports`, `--rpc=<url>`.
Environment: `GENLAYER_RPC` (default `https://studio.genlayer.com/api`), `LITMUS_KEYS` (five pre-funded
private keys: author, plaintiff, defendant, observer, outsider; if absent the script creates five accounts
and funds them with the Studio RPC method `sim_fundAccount`; if that is unavailable it stops and tells you
which addresses to fund).

Duration on Studionet: the `--skip-slow` run of 2026-11-28 took 15 minutes 18 seconds (10:22:17 to 10:37:35 UTC); its model-backed
transactions took 14-25 s each. The full run adds the timeout case, whose two windows (3 + 4 minutes) run in the background of the
other cases; its duration on the v0.4 contract has not been measured yet.

## What it does

| Stage | Checks |
|---|---|
| Setup | five funded accounts; contract source LF-only and BOM-free |
| Deploy | deployed address; fresh state; **deployed bytes equal the committed source** |
| Forge | three rejected forges leave state untouched; the real forge escrows the exact bond (what happens to the value attached to the rejected calls is settled by the audits) |
| Litmus test | five golden probes are judged by the validators under exact consensus; each result is compared with the author's expectation; certification only if the clarity threshold holds; the stored digest equals the digest the script computes independently in JavaScript |
| Members | a one-wei-short stake is rejected; exact stakes escrowed; double enlist rejected |
| Case T (timeout) | filed early; ruled with **no defense** once its window closed; settled with **no waiver** after the appeal window; reaches the strike limit and the defendant is expelled |
| Case A | wrong-deposit / self / non-member filings rejected; early ruling rejected; non-defendant defense rejected; ruling; early settle rejected; winner cannot waive; waive; settle |
| Case B | compliant path: deposit forfeited to the defendant |
| Case C | appeal path: winner cannot appeal, wrong deposit rejected, appeal judged afresh; reversal flag and bond slash (if any) verified |
| Every settlement | an independent oracle recomputes penalty, severity, each wallet's credit, defendant stake, strikes, released reservation, rule counters, bond and reversals **from the on-chain verdict** and compares |
| Audits | after every stage `escrow_total` equals the recomputed sum of every liability; the native balance equals the escrow once the value of rejected payable calls has been returned |
| Exit | members leave (expelled members get their remaining stake), rule retired, bond reclaimed, everyone withdraws, the withdraw transactions are waited to FINALIZED, every wallet must then be credited (net of the transaction fee), escrow and contract balance end at zero |

## Reading the report

`reports/live_e2e_<mode>_<timestamp>.md` (human) and `.json` (machine) list every check and every
transaction with its explorer link.

* **PASS / FAIL** are hard results. The process exits 1 on any FAIL.
* **WARN** means the run is correct but something is worth reading: a model-backed step needed a retry; the
  validators' ruling differed from the designed expectation (this is *information about the model*, the
  accounting is still verified against what they agreed); a rejection was not proven by a receipt (see below);
  the contract balance is only explained with submissions whose receipt was lost; a wallet was not credited
  while the withdraw transaction was still not FINALIZED. A wallet that is **not credited although its withdraw
  transaction FINALIZED is a FAIL**: the contract already zeroed the ledger, so the money is owed and not delivered.
* **INFO** is neutral context.

Language-model steps are retried up to `--llm-attempts` times because the exact-equality law can make the
validators legitimately fail to agree; each retry is a WARN and nothing is hidden.

## Why it trusts state, not receipts

Receipt shapes differ between SDK versions and networks. Every step is accepted only if the **contract
state read back through the views** shows the expected effect (for example a probe's `result` is no longer
`PENDING`).

A **rejection** check needs both: the state is unchanged *and* there is a transaction hash whose execution result
is a contract error (`exec=false`). "State unchanged" alone proves nothing, because a request that never reached the
chain (rate limit, gateway page) leaves the state unchanged too. Without a receipt the step is repeated and
reported as a WARN; a call that was expected to fail but executed successfully is a FAIL.

Transport errors are handled in `scripts/lib/real_chain.mjs`: a transaction is submitted once (only an explicit
rate-limit refusal is repeated, because nothing was accepted then); after that, transient polling errors (rate limit,
HTML gateway pages) are retried against the **same hash**, so a rate-limited poll can no longer turn an accepted
transaction into a send error. The public Studio RPC allows 30 requests per minute, so polling runs every 5 s.

## Dry run and the differential test

`--dry-run` runs the identical script against `scripts/lib/mock_chain.mjs`, a JavaScript model of the
contract with a deterministic stand-in for the validators and a virtual clock. It records a transcript.
`tests/direct/test_dryrun_replay.py` replays that transcript against the real Python contract in Direct Mode
and requires the final stats, rules, cases, members and ledgers to be identical, which keeps the model, the
script's accounting oracle and the contract from drifting apart. The test replays four variants: the default run, `--flip-appeals`,
`--skip-slow` and `--refund-rejected-late --late-transfers`.

Recorded result of the full dry run (`reports/live_e2e_dryrun_2026-11-28T11-32-43-002Z.*`, no flags, so the timeout case is included):
**174 PASS, 0 FAIL, 0 WARN, 4 INFO**. The timeout case is case 1 (the defendant is EXPELLED at the strike limit, final membership
status in the INFO check); cases A, B and C are cases 2, 3 and 4 (BREACH [true,true], COMPLIANT, BREACH [false,false]). The dry run has
no network, so its `retainedValue.mode` stays `unknown`.

## Value attached to rejected payable calls

When the contract rejects a payable call (`forge_rule`, `enlist`, `file_case`, `appeal_case` with a wrong amount, on
a retired rule, twice ...), the call is rolled back and the contract cannot refund inside a call it reverts. What the
network then does with the attached value was seen in two ways over three runs:

* **2026-11-26: held, then returned.** Right after a rejected call the contract's native balance is higher than its
  escrow by that value; once the rejected transaction finalizes the balance is back at the escrow. The senders' wallets
  confirm it: the author spent 7.34e15 wei in total (the 6e15 bond plus fees) although 15e15 wei had been attached to
  three rejected forges, and the plaintiff, who attached 9e15 wei to each of two rejected `enlist` calls, spent 10.4e15
  wei in total (the 9e15 stake, 0.3e15 of filing deposits and fees).
* **2026-11-28 (v0.4 contract): held, then returned.** After the three rejected forges the balance was 14999999999999999 wei above its
  earlier level (C014); after the rejected `enlist twice` it was 9e15 wei above the escrow (C048) and after the rejected `enlist` on the
  retired rule again 9e15 wei above (C145). Each audit waited for finalization and the balance came back to the escrow (C023, C049,
  C146). The report records `retainedValue.mode = refunded`: 42499999999999996 wei was attached to rejected calls in total and all of it
  returned (C163).
* **2026-11-18: kept.** That run's final balance equalled the value of all rejected calls. That run did not wait for
  finalization before reading the balance.

The old script assumed the second behaviour from one early reading and then demanded
`balance = escrow + (all rejected value so far)` forever, which is why seven audits of the 2026-11-26 run warned. The
script now makes no assumption: an audit that finds the balance above the escrow **waits up to `--refund-wait-sec`**
for it to return. If it returns, the audit passes and the network is recorded as `refunded`; if it does not and the
excess equals the value attached to every rejected call, the network is recorded as `kept` and later audits expect
`balance = escrow + retained`; any other excess is a WARN with its difference. The mode is stored in the JSON report
(`retainedValue.mode`). Practical rule for users: attach exactly the required amount; the value of a rejected call is
at best returned late.

## Wallet credits and finalization

`withdraw` zeroes the ledger and emits the transfer. Studionet applies emitted transfers when the withdraw transaction
**finalizes**, on the contract side (the contract's native balance falls) and on the wallet side (the recipient is
credited) together. The script therefore

1. waits for every withdraw transaction to reach FINALIZED (`--finality-timeout-min`);
2. then waits up to `--payout-wait-min` for each wallet to rise by the withdrawn amount **minus a fee allowance of
   0.0005 GEN**: the withdraw transaction's own fee leaves the wallet at the same time (about 0.00013 GEN), so an exact
   `+amount` is never observable and the old comparison could not pass even for a correct payout;
3. fails a wallet whose withdraw FINALIZED without a credit, and fails a contract that still holds the withdrawn money
   after wind-down. A withdraw that is not FINALIZED yet is a WARN; re-check it with
   `node scripts/verify_withdrawals.mjs <report.json>`.

For `withdraw` the adapter first asks the node for a fee estimate that carries the message allocation of the emitted
transfer (`estimateTransactionFeesForWrite`) and writes into the report notes whether that estimate worked
(`fees(withdraw): estimated, N message allocation(s)`) or fell back to the default fee config (`fees(withdraw): fell back ...
WITHOUT message allocations`).

**What the real network did (2026-11-28):** the estimate never succeeded. Every attempt failed with `Missing or invalid parameters`
(14 failed attempts, 7 fallbacks, no `estimated` note), so every withdraw was sent **without** message allocations, and Studionet still
applied every emitted transfer when the transaction finalized: the wallets were credited and the contract balance went to zero.
On this network and contract the allocations were therefore not needed for the payout. Two things stay open: whether other networks or
Studio versions require them, and why `estimateTransactionFeesForWrite` of genlayer-js 2.1.0 rejects the parameters the adapter sends
(a script/SDK matter, not a contract matter). If a future run shows the fallback line **and** unpaid wallets, suspect the missing
allocations first.

## The Studionet run of 2026-11-28 (`reports/live_e2e_studionet_2026-11-28T10-22-17-258Z.*`, `--skip-slow`)

First live run of the v0.4 contract (chain id 61999, Studio v0.123 / Consensus v0.6, 20 validators). Contract
`0x7942816B0D37Cb141aAd46527692c6bff9F42Eea`, deployed fresh by the script; the deployed bytes equal `contracts/Litmus.py` (36275 bytes,
sha256 `2449db5590d94b3d521d9fffe0f6c677f026a79786033ff31d23613847707088`, C005/C008). **156 PASS, 0 FAIL, 0 WARN, 6 INFO, 1 SKIP.**
The skip is the timeout case T (`--skip-slow`, C050). Every transaction was accepted on its first attempt.

| Area | Result |
|---|---|
| Rule lifecycle | three rejected forges left state untouched; the real forge escrowed the 6e15 bond; five golden probes, all agreed and equal to the author's expectation; clarity 100; stored digest equals the digest computed in JavaScript; revision of a certified rule rejected |
| Members and cases | three members enlisted (9e15 stake each); case A BREACH [true,true] severity 3 (waived), case B COMPLIANT (waived), case C BREACH [false,false] severity 1 appealed and upheld; every figure the oracle recomputed (penalty, credits, stake, strikes, reservation, counters, bond, reversals) matched the chain |
| Rejections | every one of them has a receipt with `exec=false`; no `SEND_ERROR`, no rejection accepted on "state unchanged" alone |
| Books | `escrow_total` equalled the recomputed liabilities after every stage; the contract balance equalled the escrow once the value of rejected payable calls had returned (see above) |
| Exit | members left, rule retired, bond reclaimed, four withdrawals FINALIZED, escrow, claimable and contract balance all zero |
| Transport | 16 rate-limit refusals (30 requests per minute) were retried on the same transaction; none was lost |

Observations worth knowing:

* **The fee estimate for `withdraw` failed and the payouts still arrived** (see "Wallet credits and finalization").
* **Wallet credits.** The plaintiff, defendant and observer wallets rose by exactly the withdrawn amount minus 126305250000823 wei, the
  same transaction fee each time. The **author's** wallet rose by 405795041750008471 wei for 6000000000000000 withdrawn. The author's
  balance had been measured about 0.4 GEN below the other wallets before the withdrawals, which is consistent with fee budgets of the
  author's earlier transactions being returned at finalization, but the report does not prove that. The credit check only demands a rise of
  at least the amount minus the fee allowance, so C156 proves that the author's withdrawal arrived, not that the whole rise comes from it.
* **One dissenting vote.** `run_probe 2` was accepted with votes AGREE/IDLE/AGREE/AGREE/DISAGREE; consensus is by majority, the law applies per
  validator, and the stored result is the agreed one (see [CONSENSUS.md](CONSENSUS.md)).
* **Not covered on chain:** the timeout case (expulsion, `settle_case` without a waiver) and an overturned appeal (case C was upheld, so
  reversals stayed 0 and the bond was not slashed). Run without `--skip-slow` for the first; the second is covered by Direct Mode tests and
  by the dry run (`--flip-appeals`).

> The run of 2026-11-26 below was made against the GenVM v0.2 contract that Studio v0.123 still serves for legacy deployments.
> The v0.4 port is a new contract: its first live run writes a new report with the new address.

## The Studionet run of 2026-11-26 (`reports/live_e2e_studionet_2026-11-26T14-41-12-921Z.*`, files no longer in the repository, `--skip-slow`)

Contract `0x57A3125911B84944CBE8148A34e715f98f215F81`, 144 PASS, 0 FAIL, 12 WARN, 6 INFO. Every state check passed
(rule lifecycle, five golden probes, three cases including an appeal, settlement oracle, books). The 12 warnings, by
cause:

| Checks | Cause | Status |
|---|---|---|
| C022, C048, C079, C104, C129, C145, C162 (7) | The script believed the value of rejected payable calls stays in the contract (from one early reading, C013) and demanded `balance = escrow + all rejected value`. The balance was in fact `escrow` or `escrow + the last rejected call` (C048: exactly the 9e15 of the `enlist twice` that had just been rejected; C145: exactly the 9e15 of the rejected `enlist` on a retired rule), i.e. the value is returned after finalization. | Script bug, fixed (audit waits and classifies). The contract was right. |
| C155-C159 (5) | After all four `withdraw` transactions FINALIZED the wallets showed only the fee loss (about -1.3e14 wei) and the contract still held 33.4e15 wei, exactly the withdrawn sum. The check also compared with `balance + amount` and ignored the fee. | **Not reproduced with the v0.4 contract**: in the 2026-11-28 run all four payouts arrived although the fee estimate with message allocations failed and was replaced by the default fee config. Why the legacy v0.2 contract's transfers were not applied in this run was never established. The script now fails a finalized withdraw whose wallet is not credited. |

The 17 `rpc:` notes of the report are rate-limit refusals (30 requests per minute) that the adapter retried; no
transaction was lost.

## The Studionet run of 2026-11-18 (`reports/live_e2e_studionet_2026-11-18T14-18-08-667Z.*`, files no longer in the repository)

Contract `0x259C458f4f12552dcCa28d7751809d391CACbe10`, 162 PASS, 0 FAIL, 15 WARN, 3 INFO. The 15 warnings, by cause:

| Checks | Cause | Status |
|---|---|---|
| C012, C021, C047, C079, C105, C130, C148, C164, C180 (9) | Value attached to rejected payable calls was still in the contract when read (see above; that run did not wait for finalization). Every figure reconciles to the wei: the three rejected forges attached 14999999999999999 wei (C012 says the same); the final balance of 42499999999999996 wei equals the value attached to the 11 rejected payable calls of the run, including the rejected appeal of C113. Escrow and claimable ended at 0. | Explained. Not a bookkeeping error; the old script could not name the cause. |
| C083, C084 (2) | `Rate limit exceeded: 30 requests per minute` from the public RPC while polling `submit_defense B`; the call was repeated and took effect (state verified). | Transport. Fixed by retrying polls on the same hash and polling every 5 s. |
| C174-C177 (4) | The wallets showed +0 after the finalization wait. The contract side did happen: the balance fell from 75999999999999996 to 42499999999999996, exactly the 33500000000000000 wei withdrawn. The old script ignored the result of its finalization wait, so the report cannot say whether the withdraw transactions had finalized. | **Not proven in that run.** Re-check with `scripts/verify_withdrawals.mjs`; later runs report the transaction status in the check. |

Also noted in that run: **C113** (`appeal_case C rejected for the party that won`) passed although it ended as
`SEND_ERROR` with a gateway page (`Unexpected token '<'`) and no receipt; the old check treated "state unchanged" as proof. The balance
arithmetic above shows the call did reach the chain (its 100000000000000 wei deposit is part of the retained
balance), but the report itself does not prove the rejection. The current script requires a receipt for every rejection.
