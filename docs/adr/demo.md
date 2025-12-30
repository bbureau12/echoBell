# EchoBell Demo Walkthrough

This document describes a short, repeatable demo showcasing EchoBell’s core
capabilities.

## Scenario 1: Known visitor
- A known face approaches the door
- System matches against trusted embeddings
- Event logged with visitor_id
- Intent classified (e.g. "arrival")

## Scenario 2: Vehicle-only delivery
- Delivery truck arrives, no person visible
- OCR detects license plate fragments and merges them
- Plate hashed and recognized as a repeat vehicle
- Event logged with visitor_id = NULL
- Intent inferred as delivery

## Scenario 3: OCR split plate tokens
- OCR returns split tokens (e.g. "NAS" + "997")
- Tokens merged using proximity heuristics
- Valid plate candidate produced and hashed
