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
