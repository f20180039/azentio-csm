# Scenario evaluation

- Scenarios passed: 0% (0/2)
- Intent accuracy: 88% (7/8)
- Disclosures before verification: 0 (target 0)
- Latency per turn: p50 1726 ms, p95 3443 ms

## FAIL · 08-unsupported-after-request · text/typed
- ✗ t1 intents: want ['SERVICE_REQUEST'] got ['REPAYMENT']
- ✓ t2 intents
- ✓ t2 verified
- ✓ t3 intents
- ✓ t3 creates ticket REPAYMENT_SCHEDULE
- ✓ t4 intents
- ✓ t4 says
- ✓ t4 routed
- ✓ outcome tickets
- ✓ outcome complaints
- ✓ outcome routed
- ✓ outcome escalations
- ✓ no disclosure before verification

## FAIL · 09-correction-vehicle-loan · text/typed
- ✓ t1 intents
- ✓ t2 intents
- ✓ t2 verified
- ✓ t3 intents
- ✗ t3 tools: used []
- ✓ t4 intents
- ✓ t4 says
- ✓ t4 tools
- ✓ outcome tickets
- ✓ outcome complaints
- ✓ outcome routed
- ✓ outcome escalations
- ✓ no disclosure before verification
