# EchoBell Documentation Index

**Last Updated:** January 26, 2026

Welcome to the EchoBell documentation! This index will help you find what you need.

---

## 📚 Quick Start

**New to EchoBell?** Start here:

1. **[ARCHITECTURE.md](ARCHITECTURE.md)** - System architecture and component overview
2. **[edge/agent/README.md](../edge/agent/README.md)** - Setting up edge devices (cameras/doorbells)
3. **[central/policy-server/README.md](../central/policy-server/README.md)** - Setting up the policy server
4. **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Development setup and contribution guidelines

---

## 🏗️ Core Documentation

### System Architecture

- **[ARCHITECTURE.md](ARCHITECTURE.md)** - Complete system architecture
  - Edge/Central separation
  - Data flow diagrams
  - Component interactions
  - Deployment patterns

- **[DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)** - Database schema reference
  - All tables and columns
  - Relationships and indices
  - Migration guide

### Edge Devices

- **[guides/EDGE_DEVICES_GUIDE.md](guides/EDGE_DEVICES_GUIDE.md)** - Edge device image serving & storage
  - Network file share setup
  - HTTP image server (recommended)
  - Upload to central
  - Telegram photo integration

- **[edge/agent/README.md](../edge/agent/README.md)** - Unified edge agent
  - Camera mode (passive monitoring)
  - Doorbell mode (interactive)
  - Configuration guide
  - Image server setup

### Central Services

- **[central/policy-server/README.md](../central/policy-server/README.md)** - Policy server
  - REST API endpoints
  - Scene tracking
  - Policy evaluation
  - Action execution

- **[central/scheduler/README.md](../central/scheduler/README.md)** - Camera scheduler daemon
  - Camera orchestration
  - Event scheduling
  - Configuration

---

## 📋 Policy Engine

### Policy Configuration

- **[POLICY_ENGINE.md](POLICY_ENGINE.md)** - Policy engine overview
  - How policies work
  - Evaluation flow
  - Priority system
  - Context and evidence

- **[POLICY_REFERENCE.md](POLICY_REFERENCE.md)** - Complete policy reference
  - All condition operators
  - All action types
  - Variable system
  - Examples for every feature

- **[POLICY_API.md](POLICY_API.md)** - Dynamic policy management API
  - Create/update/delete policies via REST
  - List and query policies
  - Enable/disable policies
  - API reference

- **[CAMERA_SPECIFIC_POLICIES.md](CAMERA_SPECIFIC_POLICIES.md)** - Camera-specific policies
  - Trigger policies based on camera ID
  - Different responses per camera
  - Multi-camera grouping
  - Seasonal/scheduled camera policies

### Action Handlers

- **[guides/ACTION_HANDLERS_GUIDE.md](guides/ACTION_HANDLERS_GUIDE.md)** - Complete action handler guide
  - Built-in handlers (telegram, speak, webhook, log)
  - Creating custom handlers
  - Handler registration
  - Variable substitution
  - Testing handlers

---

## 🔍 Scene & Perception

- **[EVIDENCE_TRACKING.md](EVIDENCE_TRACKING.md)** - Evidence system
  - Evidence sources
  - Evidence features
  - How evidence flows through system
  - Building evidence from observations

- **[TRUST_FLOW.md](TRUST_FLOW.md)** - Trust system (faces, plates)
  - How trust works
  - Adding trusted entities
  - Trust evidence generation

- **[TYPES_REFERENCE.md](TYPES_REFERENCE.md)** - Type definitions
  - Core data structures
  - API models
  - Evidence types

---

## 🧪 Testing

- **[guides/TESTING_GUIDE.md](guides/TESTING_GUIDE.md)** - Complete testing guide
  - Running tests
  - Test structure and organization
  - Writing new tests
  - Unit vs integration tests
  - Test fixtures
  - Debugging tests

- **[TEST_RESULTS.md](TEST_RESULTS.md)** - Latest test results
  - 267 passing tests
  - Known failures (pre-existing)
  - Test categories
  - Recommended fixes

- **[tests/README.md](../tests/README.md)** - Test suite overview
- **[tests/QUICKSTART.md](../tests/QUICKSTART.md)** - Quick test reference

---

## 🔧 Development

- **[CONTRIBUTING.md](../CONTRIBUTING.md)** - Contribution guidelines
  - Development setup
  - Code style
  - Pull request process

- **[ROADMAP.md](ROADMAP.md)** - Future plans and features

- **[RESTRUCTURE.md](../RESTRUCTURE.md)** - Project restructure notes
  - edge/ and central/ separation
  - Migration from old apps/ structure

---

## 🔗 Integrations

- **Telegram Bot** - Alerts and photos (see [POLICY_REFERENCE.md](POLICY_REFERENCE.md))
- **Text-to-Speech (TTS)** - Voice announcements (see [guides/ACTION_HANDLERS_GUIDE.md](guides/ACTION_HANDLERS_GUIDE.md))
- **Home Assistant** - Via webhook action (see [guides/ACTION_HANDLERS_GUIDE.md](guides/ACTION_HANDLERS_GUIDE.md))

---

## 📦 Examples

All working examples are in the [`examples/`](../examples/) directory:

- **[custom_action_handlers.py](../examples/custom_action_handlers.py)** - Custom action handler examples
- **[scene_context_usage.py](../examples/scene_context_usage.py)** - Scene tracking examples
- **[evidence_logging_example.py](../examples/evidence_logging_example.py)** - Evidence system usage
- **[vehicle_first_time_alert.py](../examples/vehicle_first_time_alert.py)** - First-time detection
- **[cross_camera_tracking_usage.py](../examples/cross_camera_tracking_usage.py)** - Multi-camera tracking

See **[examples/README.md](../examples/README.md)** for all examples.

---

## 🗂️ Specialized Topics

- **[MCP_SERVER.md](MCP_SERVER.md)** - Model Context Protocol server
- **[SCHEDULED_EVENTS.md](SCHEDULED_EVENTS.md)** - Scheduled camera events

---

## 🎯 Common Tasks

**Set up a new camera/doorbell:**  
→ [edge/agent/README.md](../edge/agent/README.md)

**Create a new policy:**  
→ [POLICY_REFERENCE.md](POLICY_REFERENCE.md)

**Add a custom action handler:**  
→ [guides/ACTION_HANDLERS_GUIDE.md](guides/ACTION_HANDLERS_GUIDE.md)

**Send photos via Telegram:**  
→ [guides/EDGE_DEVICES_GUIDE.md](guides/EDGE_DEVICES_GUIDE.md)

**Run tests:**  
→ [guides/TESTING_GUIDE.md](guides/TESTING_GUIDE.md)

**Understand the architecture:**  
→ [ARCHITECTURE.md](ARCHITECTURE.md)

**Add a trusted face/vehicle:**  
→ [TRUST_FLOW.md](TRUST_FLOW.md)

**Manage policies via API:**  
→ [POLICY_API.md](POLICY_API.md)

---

## 📁 Documentation Structure

```
docs/
├── README.md                          # This index
├── ARCHITECTURE.md                    # System architecture
├── DATABASE_SCHEMA.md                 # Database reference
├── POLICY_ENGINE.md                   # Policy engine overview
├── POLICY_REFERENCE.md                # Policy configuration reference
├── POLICY_API.md                      # Policy management API
├── EVIDENCE_TRACKING.md               # Evidence system
├── TRUST_FLOW.md                      # Trust system
├── TEST_RESULTS.md                    # Test results
├── ROADMAP.md                         # Future plans
├── TYPES_REFERENCE.md                 # Type definitions
├── MCP_SERVER.md                      # MCP integration
├── SCHEDULED_EVENTS.md                # Event scheduling
│
├── guides/                            # Implementation guides
│   ├── ACTION_HANDLERS_GUIDE.md       # Action handlers (complete)
│   ├── EDGE_DEVICES_GUIDE.md          # Edge device setup (complete)
│   └── TESTING_GUIDE.md               # Testing (complete)
│
├── archive/                           # Old/deprecated docs
│   └── ...                            # Replaced documentation
│
└── adr/                               # Architecture decision records
    ├── 001-vision-service.md
    └── ...

```

---

## 📝 Quick Reference

| Topic | Document |
|-------|----------|
| **System Architecture** | [ARCHITECTURE.md](ARCHITECTURE.md) |
| **Database Schema** | [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) |
| **Edge Devices** | [guides/EDGE_DEVICES_GUIDE.md](guides/EDGE_DEVICES_GUIDE.md) |
| **Policy Engine** | [POLICY_ENGINE.md](POLICY_ENGINE.md) |
| **Policy Reference** | [POLICY_REFERENCE.md](POLICY_REFERENCE.md) |
| **Action Handlers** | [guides/ACTION_HANDLERS_GUIDE.md](guides/ACTION_HANDLERS_GUIDE.md) |
| **Testing** | [guides/TESTING_GUIDE.md](guides/TESTING_GUIDE.md) |
| **Evidence System** | [EVIDENCE_TRACKING.md](EVIDENCE_TRACKING.md) |
| **Trust System** | [TRUST_FLOW.md](TRUST_FLOW.md) |
| **Examples** | [examples/README.md](../examples/README.md) |

---

## 🏛️ Architecture Decision Records (ADRs)

Located in [`adr/`](adr/) - Documents significant architectural and design decisions:

- **[ADR-00001](adr/ADR-00001-event-without-visitor.md)** - Events without visitor identity
- **[ADR-00002](adr/ADR-00002-plate-privacy-hmac.md)** - Plate privacy via HMAC
- **[ADR-00003](adr/ADR-00003-plates-as-events-not-identity.md)** - Plates as evidence, not identity
- **[ADR-0004](adr/ADR-0004-vehicle-role-inference.md)** - Vehicle role inference
- **[ADR-0005](adr/ADR-0005-scene-awareness-temporal-tracking.md)** - Scene awareness & tracking
- **[ADR-0011](adr/ADR-0011-vehicle-type-preservation-and-size-aware-linkage.md)** - Vehicle type preservation

---

## 🔄 Documentation Updates

This documentation was consolidated on **January 26, 2026**:
- Created unified guides in `guides/` directory
- Moved old/overlapping docs to `archive/`
- **28 files → 15 core files** (46% reduction)
- Improved organization and discoverability

If you find outdated information or need clarification, please create an issue!

---

**Happy coding! 🚀**

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

**Setting up Telegram notifications**:
1. Create bot via @BotFather on Telegram
2. Get chat ID from @userinfobot
3. Set environment variables (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)
4. Test with `pytest tests/test_telegram_integration.py -v -s`
5. See [Architecture: Integrations](ARCHITECTURE.md#integrations)

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
