from huggingface_hub import hf_hub_download

det_path = hf_hub_download(
    repo_id="Genius-Society/MiVOLO",
    filename="yolov8x_person_face.pt",
    local_dir="models",
)
ckpt_path = hf_hub_download(
    repo_id="Genius-Society/MiVOLO",
    filename="model_imdb_cross_person_4.22_99.46.pth.tar",
    local_dir="models",
)