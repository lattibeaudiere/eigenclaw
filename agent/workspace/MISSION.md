# Mission

## Primary Objective

To perform **Truth-Seeker** audits on the **DeFEyes Intelligence Product**.

## Core Task

Cross-reference DeFEyes API labels against Arbiscan RPC receipts to ensure semantic integrity.

## The Conflict

To identify **Ontology Drift**—cases where a complex "Journey" (swaps, hops, aggregator routing) causes the system to mislabel the "Destination" (the final economic action). The journey describes *how* the user got there; the destination defines *what* happened.

## The Outcome

- **Real Distortions:** Flagged when `outcome_asset` in the database does not match the Aave Pool `reserve`, or when `action_type` does not match the emitted event.
- **False Positives:** Avoided by anchoring on protocol pool events, not on intermediate routing.
- **Healing Reports:** Delivered to Bread for review before any harmonization is considered final.
