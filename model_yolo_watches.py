from pathlib import Path
from ultralytics import YOLO
import torch

class WatchSegmentationTrainer:
    def __init__(self, data_yaml="yolo_dataset/data.yaml"):
        self.data_yaml = data_yaml
        self.device = '0' if torch.cuda.is_available() else 'cpu'

        if not Path(data_yaml).exists():
            raise FileNotFoundError(f"{data_yaml} не найден")

    def train(self, epochs=100, patience=20, project='segment', name='watch_yolo'):
        model = YOLO('yolo11l-seg.pt')

        results = model.train(
            data=self.data_yaml,
            epochs=epochs,
            imgsz=1280,
            batch=4,
            device=self.device,
            project=project,
            name=name,
            exist_ok=True,

            optimizer='AdamW', lr0=0.001, lrf=0.01, momentum=0.937,
            weight_decay=0.0005, warmup_epochs=3.0, warmup_momentum=0.8,
            warmup_bias_lr=0.1, patience=patience,

            hsv_h=0.015, hsv_s=0.7, hsv_v=0.4, degrees=10.0, translate=0.1,
            scale=0.5, shear=5.0, perspective=0.0, flipud=0.0, fliplr=0.5,
            mosaic=1.0, mixup=0.1, copy_paste=0.0,

            box=7.5, cls=0.5, dfl=1.5,

            workers=8, seed=42, verbose=True,
            save=True, save_period=10, val=True, plots=True, amp=True,
            fraction=1.0, close_mosaic=10,
        )

        best_model = Path(project) / name / 'weights' / 'best.pt'
        return results, str(best_model)

    def validate(self, model_path):
        model = YOLO(model_path)
        results = model.val(data=self.data_yaml, split='val', verbose=True)

        print(f"Box mAP50:    {results.box.map50:.4f}")
        print(f"Box mAP50-95: {results.box.map:.4f}")
        print(f"Mask mAP50:   {results.seg.map50:.4f}")
        print(f"Mask mAP50-95:{results.seg.map:.4f}")

        return results


def main():
    trainer = WatchSegmentationTrainer(data_yaml="yolo_dataset/data.yaml")

    results, best_model_path = trainer.train(epochs=100, patience=40)

    val_results = trainer.validate(best_model_path)

    print(f"Лучшая модель: {best_model_path}")
    print(f"Box mAP50:     {val_results.box.map50:.4f}")
    print(f"Mask mAP50:    {val_results.seg.map50:.4f}")

    return results, best_model_path

if __name__ == "__main__":
    main()