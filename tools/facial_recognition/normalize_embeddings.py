import numpy as np

def l2_normalize_rows(X: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(X, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return X / n

def select_prototypes_farthest_first(embs: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """
    embs: (N, D) float32 face embeddings (preferably already L2 normalized)
    returns (prototypes, indices)
    """
    X = l2_normalize_rows(embs.astype("float32"))
    N = X.shape[0]
    if N == 0:
        return X[:0], np.array([], dtype=int)
    if k >= N:
        return X, np.arange(N, dtype=int)

    mean = l2_normalize_rows(X.mean(axis=0, keepdims=True))[0]
    sims_to_mean = X @ mean
    first = int(np.argmax(sims_to_mean))
    idxs = [first]

    # distance = 1 - cosine_similarity
    min_dist = 1.0 - (X @ X[first])
    for _ in range(1, k):
        next_i = int(np.argmax(min_dist))
        idxs.append(next_i)
        dist_to_new = 1.0 - (X @ X[next_i])
        min_dist = np.minimum(min_dist, dist_to_new)

    return X[idxs], np.array(idxs, dtype=int)
