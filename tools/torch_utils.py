"""
Utilities for safe PyTorch model loading.
"""
import importlib
import torch


def allowlist_checkpoint_globals(weights_path: str) -> None:
    """
    Allowlist all globals required by a checkpoint for torch.load(weights_only=True) mode.
    Only do this if you trust the checkpoint source.
    
    This is necessary for PyTorch 2.6+ when loading YOLO models with weights_only=True.
    
    Args:
        weights_path: Path to the .pt weights file
        
    Example:
        allowlist_checkpoint_globals("yolov8n.pt")
        model = YOLO("yolov8n.pt")
    """
    unsafe = torch.serialization.get_unsafe_globals_in_checkpoint(weights_path)
    safe_objs = []
    for qualname in unsafe:
        mod_name, obj_name = qualname.rsplit(".", 1)
        mod = importlib.import_module(mod_name)
        safe_objs.append(getattr(mod, obj_name))
    torch.serialization.add_safe_globals(safe_objs)


def enable_ultralytics_safe_load():
    """
    Enable safe loading of Ultralytics YOLO models in PyTorch 2.6+ by creating
    module aliases that match the expected fully-qualified names in older checkpoints.
    
    This handles cases where checkpoint expects 'ultralytics.nn.modules.X' but the
    real implementation has moved to 'ultralytics.nn.modules.submodule.X'.
    
    Call this once before loading any Ultralytics models (YOLO, MiVOLO, etc.)
    
    Example:
        enable_ultralytics_safe_load()
        model = YOLO("yolov8x_person_face.pt")
    """
    def _alias(real_module: str, class_name: str, expected_module: str = "ultralytics.nn.modules"):
        """
        Create an alias class whose fully-qualified name matches expected_module.class_name,
        backed by the real implementation from real_module.class_name.
        """
        try:
            Real = getattr(importlib.import_module(real_module), class_name)
            target_mod = importlib.import_module(expected_module)

            Alias = type(class_name, (Real,), {})
            Alias.__module__ = expected_module
            Alias.__name__ = class_name
            Alias.__qualname__ = class_name

            setattr(target_mod, class_name, Alias)
            return Alias
        except Exception:
            return None

    safe = []

    # DetectionModel (sometimes required)
    try:
        DetectionModel = importlib.import_module("ultralytics.nn.tasks").DetectionModel
        safe.append(DetectionModel)
    except Exception:
        pass

    # Map: checkpoint expects ultralytics.nn.modules.<Name>
    # to the real places in modern ultralytics
    candidates = [
        ("ultralytics.nn.modules.conv",  "Conv"),
        ("ultralytics.nn.modules.conv",  "Concat"),
        ("ultralytics.nn.modules.block", "C2f"),
        ("ultralytics.nn.modules.block", "Bottleneck"),
        # likely next ones (harmless if they don't exist in your install):
        ("ultralytics.nn.modules.block", "SPPF"),
        ("ultralytics.nn.modules.head",  "Detect"),
        ("ultralytics.nn.modules.block", "C3"),
        ("ultralytics.nn.modules.block", "C3k2"),
        ("ultralytics.nn.modules.block", "BottleneckCSP"),
        ("ultralytics.nn.modules.block", "DFL"),
    ]

    for mod, name in candidates:
        alias = _alias(mod, name)
        if alias is not None:
            safe.append(alias)

    if safe:
        torch.serialization.add_safe_globals(safe)
