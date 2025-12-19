import torch
import numpy as np
from torchreid.utils import FeatureExtractor

class ReIDModel:
    def __init__(self, model_name="osnet_x0_5", device=None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")

        self.extractor = FeatureExtractor(
            model_name=model_name,
            device=self.device
        )

    def extract(self, bgr_crop) -> np.ndarray:
        """
        Input: BGR image crop (numpy)
        Output: L2-normalized embedding (float32)
        """
        # torchreid expects RGB
        rgb = bgr_crop[:, :, ::-1]

        feat = self.extractor([rgb])[0]   # shape (D,)
        feat = feat.astype("float32")

        # Normalize for cosine similarity
        norm = np.linalg.norm(feat)
        if norm > 0:
            feat /= norm

        return feat
