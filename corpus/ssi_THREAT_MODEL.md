# Threat model: issuer / holder / verifier

This document turns threats to verifiable credentials into **requirements per
actor**, and links each requirement to the code that implements it and to the
attack scenario that tests it (`attacks/run_attacks.py`, results in
`results/attack_results.md`).

The threat list is my own STRIDE analysis, informed by the security and privacy
considerations of the W3C *Verifiable Credentials Data Model 2.0* and the
*Decentralized Identifiers (DIDs) v1.0* specifications. Requirement IDs are my
own numbering, not taken from those documents.

## System and trust boundaries

```
 Issuer (certification body)          Holder (technician wallet)          Verifier (CNC machine controller)
 ─────────────────────────            ──────────────────────────          ─────────────────────────────────
 signs credential (Ed25519) ──VC──▶  stores VC + disclosures
 publishes signed status list                │
            │                                │ ◀── nonce + verifier DID ── challenge()
            │                                └── signed presentation ───▶ verify()
            └──────────── status list (fetched by verifier) ────────────▶
```

Assets: the credential's claims (personal data), the right to open the
machine's maintenance mode, and the three private keys.

Attacker model: a network attacker who can read, copy, replay and change
messages; a malicious holder who wants more privileges; a rogue issuer; an
honest-but-curious verifier, or several verifiers that collude.

## Threats and requirements

| Threat | STRIDE | Requirement | Actor | Code | Tested by |
|---|---|---|---|---|---|
| T-S1 credential created by an unknown party | Spoofing | R-V1 accept only issuers in a trust registry, per credential type | Verifier | `verifier.py` R-V1 | scenario 3 |
| T-T1 claim or validity changed after issuance | Tampering | R-I1 sign the whole canonical credential; R-V2 verify it | Issuer, Verifier | `issuer.py`, `canonical.py`, R-V2 | 2 |
| T-T2 holder changes, adds or repeats a disclosed claim | Tampering | R-I2 sign only salted claim digests; R-V8 each disclosure must hash to a signed digest, once | Issuer, Verifier | R-V8 | 1, 16, 17 |
| T-E1 credential used outside its validity period | Elevation | R-I3 set `validFrom`/`validUntil`; R-V3 check them (30 s clock skew) | Issuer, Verifier | R-V3 | 9, 10 |
| T-S2 stolen credential presented by someone else | Spoofing | R-H1 sign each presentation with the subject key; R-V4 presenter = subject and signature valid | Holder, Verifier | `holder.py`, R-V4 | 6, 7 |
| T-R1 captured presentation replayed | Spoofing (replay) | R-V6 one-time nonce, expires after 120 s; R-V7 presentation at most 120 s old | Verifier | R-V6, R-V7 | 4, 15 |
| T-R2 presentation forwarded to another verifier | Spoofing (relay) | R-H2 include the verifier DID (audience); R-V5 audience = own DID | Holder, Verifier | R-V5 | 5 |
| T-E2 holder hides a claim or does not meet the policy | Elevation | R-V9 required claims and value rules per policy | Verifier | R-V9 | 11, 12 |
| T-E3 revoked credential still used | Elevation | R-I4 publish a signed revocation list; R-V10 check it | Issuer, Verifier | `status_list.py`, R-V10 | 8 |
| T-T3 fake status list hides a revocation | Tampering | R-V10 list must be signed by the credential's issuer | Verifier | R-V10 | 13 |
| T-D1 status list unreachable | Denial of service | R-V10 fail closed (reject) | Verifier | R-V10 | 14 |
| T-I1 verifier learns more than needed | Information disclosure | R-H3 disclose only required claims; R-I5 add decoy digests to hide the claim count | Holder, Issuer | `holder.present`, `Issuer.decoys` | unit tests |
| T-I2 issuer learns where the credential is used | Information disclosure | R-I4 one list covers 16 384 credentials, so fetching it does not reveal which one is checked | Issuer | `status_list.py` | design |

## Known limits (measured, not hidden)

| ID | Limit | Result in this lab | Possible mitigation |
|---|---|---|---|
| T-P1 | **Linkability.** Two colluding verifiers see the same credential id and issuer signature, so they can link two visits to one person. | Confirmed: `linkability_check()` returns `(True, True)` | One single-use credential per verifier (batch issuance), or BBS+ / zero-knowledge proofs |
| T-K1 | **Issuer key compromise.** Credentials forged with the real key are accepted. | Scenario 18 accepted | Keys in an HSM, key rotation, a DID method that supports rotation (did:key cannot rotate) |
| T-K2 | **Holder key compromise.** The thief can present the credential. | Scenario 19 accepted | Device-bound keys (secure element / TPM), user check (PIN / biometric), short validity |
| T-R3 | **Revocation delay.** A verifier with an old cached list accepts a just-revoked credential. | Shown in `test_revocation_takes_effect_after_list_refresh` | Short cache time; list `issued` timestamp checked against a maximum age |
| T-C1 | **Simplified canonicalisation.** Sorted-key JSON, not full RFC 8785 / RDF canonicalisation. | Correct for the value types used | Use a JCS library or the W3C Data Integrity suites |
| T-D2 | **Nonce store in memory.** Nonces are lost on restart and the store can grow. | Not tested | Persistent store with TTL (e.g. Redis), rate limiting on `challenge()` |

## What this lab is not

It does not implement the W3C Data Integrity or SD-JWT VC formats byte for
byte, and it has not been reviewed by anyone else. It is a teaching and
analysis tool for reasoning about actor requirements.
