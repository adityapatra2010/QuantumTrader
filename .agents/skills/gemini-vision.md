name: Gemini Vision
description: Chart image parsing, technical pattern recognition, and key level detection.

# Goal
Analyze uploaded chart screenshots to extract structural market features without executing trades[cite: 1, 2].

# Capabilities
- Detect support and resistance zones, swing highs/lows, and trendlines[cite: 1].
- Identify chart structures: Channels, Flags, Wedges, Triangles, Double Tops/Bottoms, and Head & Shoulders[cite: 1].
- Extract candlestick patterns and volume anomalies[cite: 1].

# Interface Contract
- Implement `aditrader.ai.base.VisionEngine`:
  `analyze(image_bytes: bytes, spot_price: float | None = None) -> VisionResult`[cite: 1, 2].
- `is_available() -> bool` must never raise network or runtime exceptions; returns `False` if credentials or service are offline or unconfigured[cite: 2].
- Compute SHA-256 cryptographic hash of source image bytes (`source_image_hash`). Note: `source_image_hash` is an ergonomic top-level mirror of `provenance.input_hash` (both must be the identical 64-character hex digest)[cite: 1].
- Validate all extracted price coordinates against positive bounds[cite: 1].
- Provider must generate non-empty `reasoning`; partial failure or timeout must raise `AIMalformedOutputError` rather than returning blank strings[cite: 1].
- Mandatory attachment of `ProvenanceRecord` (ADR 012).

# Output Schema
Conforms to `aditrader.ai.models.VisionResult` (ADR 012):
```json
{
  "trend": "Bullish | Bearish | Neutral",
  "support": [number],
  "resistance": [number],
  "patterns": [{"name": string, "confidence": number, "description": string | null}],
  "reasoning": string,
  "source_image_hash": "sha256_hex_string",
  "is_empty": boolean,
  "provenance": { ... }
}
```

