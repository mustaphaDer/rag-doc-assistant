# SSI credential security lab

A small Self-Sovereign Identity system (issuer, holder wallet, verifier) built
to **analyse its security**: 17 attack scenarios, a threat model that turns
threats into requirements per actor, and measurements of what the design does
**not** protect against.

Scenario: a certification body gives a maintenance technician a
`CertifiedTechnicianCredential`. A CNC machine controller lets the technician
open maintenance mode only if they prove *level ≥ 2* and *machine class = CNC*,
without revealing name, birth date or employer.

## What is implemented

| Feature | How |
|---|---|
| Decentralised identifiers | `did:key` with Ed25519 keys (`ssi/crypto.py`), no ledger needed |
| Signed credentials | Ed25519 over canonical JSON (`ssi/issuer.py`, `ssi/canonical.py`) |
| Selective disclosure | SD-JWT-style salted claim digests + decoy digests |
| Holder binding | each presentation is signed by the subject's key (`ssi/holder.py`) |
| Anti-replay | one-time verifier nonce (120 s), audience = verifier DID, freshness window |
| Revocation | issuer-signed, gzip-compressed bitstring status list (16 384 entries) |
| Policy | required claims + value rules; all failures reported, not only the first |

## Results (measured on this machine)

Full table: [`results/attack_results.md`](results/attack_results.md).

- **17 / 17 attacks blocked**, honest presentation accepted, 0 unexpected outcomes.
  Attacks include: changed claim value, extended expiry, rogue issuer, replay,
  forwarding to another verifier, stolen credential, revoked / expired /
  not-yet-valid credential, forged status list, unreachable status list
  (fail closed), injected and duplicated disclosures.
- **2 known limits confirmed** (accepted by design): stolen issuer key and stolen
  holder key.
- **Privacy finding:** selective disclosure hides the personal claims, but two
  colluding verifiers can still link both visits through the shared credential id
  and signature. Mitigations are discussed in the threat model.
- **Speed** (500 runs, Intel i5-1135G7, Python 3.10): issue median 0.13 ms,
  verify median 0.42 ms (p95 0.47 ms).
- `pytest`: 28 tests pass. `ruff`: no findings.

## Threat model

[`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) maps 13 threats (STRIDE) to
requirements for each actor (R-I* issuer, R-H* holder, R-V* verifier), the
code that implements each one, and the scenario that tests it.

## Run it

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m attacks.run_attacks      # prints and writes results/attack_results.md
python -m pytest -q
```

## Limits

This is a learning and analysis project. It follows the ideas of W3C VC 2.0,
did:key and SD-JWT but does not implement those formats byte for byte, uses
simplified JSON canonicalisation, and has not been externally reviewed.

## Why I built it

To prepare for research on SSI security, in particular the Fraunhofer ISST
master thesis topic on deriving actor requirements from the W3C threat model.
It builds on my earlier work with PKI, mTLS, Ed25519 and STRIDE in my 5G/IoT
security labs.
