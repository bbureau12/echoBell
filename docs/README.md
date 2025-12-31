# EchoBell Documentation

Welcome to the EchoBell documentation. This directory contains comprehensive guides, architectural documentation, and decision records for the system.

---

## Documentation Index

### Getting Started

- **[Architecture Overview](ARCHITECTURE.md)** - Complete system architecture, data flow, and module breakdown. **Start here** for a deep dive into how EchoBell works.

- **[Demo Walkthrough](demo.md)** - 5-minute feature demonstration with example scenarios. Great for understanding what EchoBell does from a user perspective.

### Architecture Decision Records (ADRs)

Located in [`adr/`](adr/) - Documents significant architectural and design decisions:

- **[ADR-00001](adr/ADR-00001-event-without-visitor.md)** - Events without visitor identity  
  *Why visitor_events can exist independently of visitor identity*

- **[ADR-00002](adr/ADR-00002-plate-privacy-hmac.md)** - Plate privacy via HMAC  
  *Privacy-first approach: why we hash plates instead of storing raw text*

- **[ADR-00003](adr/ADR-00003-plates-as-events-not-identity.md)** - Plates as evidence, not identity  
  *Why plates inform intent but don't define visitor identity*

- **[ADR-0004](adr/ADR-0004-vehicle-role-inference.md)** - Vehicle role inference  
  *How vehicle characteristics help classify visitor intent*

- **[ADR-0005](adr/ADR-0005-scene-awareness-temporal-tracking.md)** - Scene awareness & tracking  
  *Temporal tracking of vehicles/people for arrival/departure detection*

---

## Quick Reference

### Key Concepts

| Concept | Description | Where to Learn More |
|---------|-------------|---------------------|
| **Evidence** | Structured observations from sensors | [Architecture: Evidence-Based Architecture](ARCHITECTURE.md#1-evidence-based-architecture) |
| **Intent Classification** | Determining visitor purpose from multimodal evidence | [Architecture: Classification Layer](ARCHITECTURE.md#classification-layer-packagesclassify) |
| **Scene Tracking** | Temporal tracking of objects across frames | [Architecture: Scene Tracker](ARCHITECTURE.md#scene_trackerpy---temporal-object-tracking) |
| **Plate Validation** | Multi-factor license plate confidence boosting | [Architecture: Plate Heuristics](ARCHITECTURE.md#plate_heurysticspy---license-plate-validation) |
| **Privacy Model** | HMAC-based privacy for sensitive data | [ADR-00002](adr/ADR-00002-plate-privacy-hmac.md) |

### Data Flow Overview

```
Image Capture
    ↓
Object Detection (YOLOv8)
    ↓
Evidence Collection (OCR, Face, Color, etc.)
    ↓
Plate Processing (Grouping, Validation, Boosting)
    ↓
Intent Classification (Text + Vision + History + Scene)
    ↓
Event Logging (Persistence, Scene Tracking, Snapshots)
    ↓
Policy Execution (Actions based on intent + context)
```

See [Architecture: Complete Request Lifecycle](ARCHITECTURE.md#complete-request-lifecycle) for details.

---

## For Developers

### Understanding the Codebase

1. **Start with [ARCHITECTURE.md](ARCHITECTURE.md)**  
   Comprehensive overview of system design, modules, and patterns

2. **Review relevant ADRs**  
   Understand why certain decisions were made

3. **Run [vision_harness.py](../tools/vision_harness.py)**  
   See the system in action with test cases

4. **Check [demo.md](demo.md)**  
   Understand expected behaviors and scenarios

### Common Tasks

**Adding a new intent type**:
1. Add to `intent_def` table
2. Create pattern/signal rules
3. Test with vision harness
4. See [Architecture: Extension Points](ARCHITECTURE.md#adding-new-intent-types)

**Tuning plate detection**:
1. Adjust `plate_modifiers` in `config.json`
2. Test with vision harness
3. Review confidence boosts in output
4. See [Architecture: Plate Validation](ARCHITECTURE.md#plate_heurysticspy---license-plate-validation)

**Adding new evidence sources**:
1. Create detector in `packages/perception/`
2. Return `List[Evidence]`
3. Integrate into `snapshot_and_detect()`
4. Create signal rules
5. See [Architecture: Extension Points](ARCHITECTURE.md#adding-new-evidence-sources)

---

## Documentation Maintenance

### When to Update

- **ARCHITECTURE.md**: Major design changes, new modules, significant refactoring
- **ADRs**: Architectural decisions, trade-offs, design choices
- **demo.md**: New features, changed behaviors, updated scenarios

### Documentation Standards

- Keep code examples up-to-date with actual implementation
- Use diagrams for complex flows (ASCII art is fine)
- Link between related documents
- Update "Last Updated" dates
- Add new ADRs for significant decisions

---

## External Resources

- **YOLOv8 Documentation**: https://docs.ultralytics.com/
- **PaddleOCR**: https://github.com/PaddlePaddle/PaddleOCR
- **InsightFace**: https://github.com/deepinsight/insightface
- **SQLite**: https://www.sqlite.org/docs.html

---

**Questions or Suggestions?**

If you find gaps in documentation or have questions about the architecture, please:
1. Check existing ADRs for historical context
2. Review ARCHITECTURE.md for technical details
3. Run vision_harness.py to see the system in action
4. Add new ADRs for decisions that deserve documentation

---

*Last Updated: December 31, 2025*
