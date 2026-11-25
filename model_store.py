import urllib.request
from pathlib import Path

MODEL_DIR = Path(__file__).with_name("models")
MODELS = {
    "hand_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
    ),
    "face_landmarker.task": (
        "https://storage.googleapis.com/mediapipe-models/"
        "face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
    ),
}


def ensure_models():
    MODEL_DIR.mkdir(exist_ok=True)
    paths = {}
    for name, url in MODELS.items():
        dest = MODEL_DIR / name
        if not dest.exists() or dest.stat().st_size < 10000:
            print(f"Скачиваю модель {name}...")
            urllib.request.urlretrieve(url, dest)
        paths[name] = dest
    return paths
