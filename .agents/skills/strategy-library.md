name: Strategy Library
description: Strategy cataloging, categorization, version control, and DNA tagging.

# Goal
Organize and maintain a registry of institutional option templates, user strategies, and AI-generated configurations[cite: 1, 2].

# Strategy Categories
- `Built-in`: Immutable production templates (Iron Condor, Iron Fly, Jade Lizard, Bull Call Spread, Bear Put Spread, Long Straddle)[cite: 1, 2].
- `User`: Custom structures created via the visual builder or manual DSL definitions[cite: 1, 2].
- `AI Generated`: Strategies compiled by the Suggestor module based on market regimes[cite: 1, 2].
- `Imported`: External configurations ingested via JSON schema imports.
- `Archived`: Deprecated or invalidated strategies preserved for historical audit trails.

# Strategy Record Schema
Every strategy entry must conform to the following schema[cite: 1]:
```json
{
  "id": "uuid-v4",
  "name": "Nifty Weekly Iron Condor",
  "version": "1.2.0",
  "category": "Built-in",
  "creator": "System",
  "created_at": "2026-09-06T10:30:00Z",
  "validation_score": 94,
  "dna": {
    "directionality": "Delta-Neutral",
    "theta_exposure": "High Positive",
    "vega_exposure": "Negative",
    "gamma_risk": "Low",
    "margin_efficiency": "High",
    "style": "Positional",
    "target_regime": "Low IV Sideways"
  },
  "dsl_definition": {
    "underlying": "NIFTY",
    "legs": []
  }
} ```

# Rules

- Semantic Versioning: Any change to legs, conditions, or thresholds requires a version increment (1.0.0 -> 1.1.0)[cite: 1]. Never overwrite existing version records.
- DNA Vector Indexing: Strategies must be queryable by their calculated DNA profile (e.g., filtering for "High Positive Theta" and "Low IV Sideways")[cite: 1].
